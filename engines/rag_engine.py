"""Basic RAG Engine — Retrieval-Augmented Generation with citations.

Combines the Retrieval Engine with Qwen LLM to produce grounded answers
based on retrieved evidence. All answers include citations pointing back
to the source evidence (page, slide, section).
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

import requests

from ai.hallucination_detector import HallucinationDetector
from .config import (
    DIRECT_MAX_CONTEXT,
    LLM_MODEL,
    OLLAMA_BASE_URL,
    RAG_MAX_CONTEXT,
    RAG_TEMPERATURE,
    RAG_TIMEOUT,
    TOP_K_DEFAULT,
    VISION_MODEL,
)
from .retrieval_engine import RetrievalEngine, RetrievalResponse, RetrievalResult, RetrievalScope

try:  # Batch 4 M0-08 — bounded AI concurrency (optional dependency)
    from services.ai_resource_manager import AIResourceUnavailable
except ImportError:  # pragma: no cover - services always present
    class AIResourceUnavailable(Exception):  # type: ignore[no-redef]
        pass

logger = logging.getLogger(__name__)

# RAG-specific configuration (values centralized in engines/config.py)
RAG_MODEL = LLM_MODEL


@dataclass
class Citation:
    """A citation pointing to a source evidence chunk."""
    source_label: str
    file_path: str
    text_snippet: str
    score: float


@dataclass
class RAGResponse:
    """Response from the RAG engine."""
    question: str
    answer: str
    citations: List[Citation]
    retrieval_results: int
    elapsed_ms: float
    model: str = RAG_MODEL
    grounded: bool = True


def format_reasoning_answer(raw_answer: str) -> str:
    """Format an LLM response containing <think>...</think> into clean structured display."""
    if not raw_answer:
        return ""
    import re
    match = re.search(r'<think>(.*?)</think>', raw_answer, flags=re.DOTALL)
    if not match:
        return raw_answer.strip()

    thought = match.group(1).strip()
    clean_answer = re.sub(r'<think>.*?</think>', '', raw_answer, flags=re.DOTALL).strip()

    if not thought:
        return clean_answer
    if not clean_answer:
        return f"💭 Reasoning Process:\n{thought}"

    return f"💭 Reasoning Process:\n{thought}\n\n{'─' * 45}\n\n🎯 Answer:\n{clean_answer}"


class RAGEngine:
    """Basic Retrieval-Augmented Generation engine.

    Workflow:
    1. Retrieve relevant evidence via RetrievalEngine
    2. Build a grounded prompt with evidence context
    3. Call Qwen LLM for answer generation
    4. Return answer with citations

    Used by: Ask Selected File, Semantic Q&A
    """

    def __init__(
        self,
        retrieval_engine: RetrievalEngine,
        model: str = RAG_MODEL,
        base_url: str = OLLAMA_BASE_URL,
        temperature: float = RAG_TEMPERATURE,
        timeout: int = RAG_TIMEOUT,
        resources=None,
        session_factory=None,
    ) -> None:
        """Initialize the RAG engine.

        Args:
            retrieval_engine: The retrieval engine for evidence lookup.
            model: Ollama model name for generation.
            base_url: Ollama server URL.
            temperature: Generation temperature.
            timeout: Request timeout in seconds.
            resources: Optional AIResourceManager to bound LLM generation.
            session_factory: Optional SQLAlchemy session factory for user metadata.
        """
        self._retrieval = retrieval_engine
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._temperature = temperature
        self._timeout = timeout
        self._resources = resources
        self._session_factory = session_factory
        # Wire embedding engine so semantic alignment is real (was None → 0.5 always).
        try:
            _emb = getattr(retrieval_engine, "_embedding", None)
        except Exception:
            _emb = None
        self._hallucination_detector = HallucinationDetector(embedding_engine=_emb)

    def _get_user_metadata_text(self, file_path: str) -> str:
        """Fetch user-curated metadata/notes from database if available."""
        if not self._session_factory:
            return ""
        try:
            import json
            from services.sqlite_indexer import IndexedFile
            with self._session_factory() as session:
                row = session.query(IndexedFile).filter_by(
                    absolute_path=os.path.abspath(file_path)
                ).first()
                if not row or not row.user_metadata_json:
                    return ""
                meta = json.loads(row.user_metadata_json)
                lines = []
                if meta.get("title"):
                    lines.append(f"Title: {meta['title']}")
                if meta.get("description"):
                    lines.append(f"Description: {meta['description']}")
                if meta.get("notes"):
                    lines.append(f"Notes: {meta['notes']}")
                if meta.get("user_tags"):
                    tags = meta["user_tags"]
                    lines.append(f"User Tags: {', '.join(tags) if isinstance(tags, list) else tags}")
                if meta.get("custom"):
                    lines.append(f"Custom Metadata: {json.dumps(meta['custom'], ensure_ascii=False)}")
                if lines:
                    return "[User-Provided Metadata & Notes]\n" + "\n".join(lines)
        except Exception as exc:
            logger.debug("Failed reading user metadata for RAG: %s", exc)
        return ""

    # ============ PHASE 3.2: HALLUCINATION DETECTION SAFETY ============
    
    def _check_answer_safety(self, question: str, answer: str, context_blocks: List[str] = None) -> Dict:
        """Check if answer is safe (not hallucinated) before returning to user."""
        try:
            if context_blocks is None:
                context_blocks = []

            # Strip chain-of-thought blocks before hallucination validation
            import re
            clean_eval_answer = re.sub(r'<think>.*?</think>', '', answer, flags=re.DOTALL).strip() or answer
            
            hallucination_check = self._hallucination_detector.detect_hallucination(
                question=question,
                answer=clean_eval_answer,
                context=context_blocks,
                model_name=self._model
            )
            
            return {
                'safe': not hallucination_check.is_hallucinated,
                'confidence': hallucination_check.confidence,
                'issues': hallucination_check.issues,
                'recommendation': hallucination_check.recommendation,
                'scores': hallucination_check.scores
            }
        
        except Exception as e:
            logger.warning(f"Error in hallucination check: {e}")
            return {
                'safe': True,
                'confidence': 0.5,
                'issues': [f'Safety check error: {str(e)}'],
                'recommendation': 'Could not verify answer safety',
                'scores': {}
            }
    
    def _wrap_answer_with_safety_notice(self, answer: str, safety_check: Dict) -> str:
        """Wrap answer with safety notices if needed."""
        if safety_check['safe']:
            return answer
        
        confidence = safety_check['confidence']
        
        if confidence > 0.8:
            warning = (
                "🚨 HIGH RISK - LIKELY HALLUCINATION 🚨\n"
                f"{safety_check['recommendation']}\n\n"
                "ORIGINAL ANSWER (DO NOT TRUST):\n"
                f"{answer}\n\n"
                "ISSUES:\n"
                + "\n".join(f"• {issue}" for issue in safety_check['issues'])
            )
        elif confidence > 0.6:
            warning = (
                "⚠️ MODERATE RISK - VERIFY BEFORE USE ⚠️\n"
                f"{safety_check['recommendation']}\n\n"
                "ANSWER:\n"
                f"{answer}\n\n"
                "POTENTIAL ISSUES:\n"
                + "\n".join(f"• {issue}" for issue in safety_check['issues'])
            )
        else:
            warning = answer
        
        return warning

    def ask(
        self,
        question: str,
        scope: RetrievalScope = RetrievalScope.WORKSPACE,
        file_filter: Optional[List[str]] = None,
        top_k: int = TOP_K_DEFAULT,
    ) -> RAGResponse:
        """Ask a question and get a grounded answer with citations.

        Args:
            question: The user's question.
            scope: Search scope for evidence retrieval.
            file_filter: Optional file paths to restrict evidence to.
            top_k: Number of evidence chunks to retrieve.

        Returns:
            RAGResponse with answer and citations.
        """
        logger.info("RAG ask: '%s' scope=%s", question[:50], scope.value)
        start = time.time()

        # Step 1: Retrieve relevant evidence
        retrieval = self._retrieval.retrieve(
            query=question,
            scope=scope,
            top_k=top_k,
            file_filter=file_filter,
        )

        if not retrieval.results:
            elapsed = (time.time() - start) * 1000
            return RAGResponse(
                question=question,
                answer="I couldn't find relevant information to answer this question. "
                       "Please ensure the relevant files have been indexed.",
                citations=[],
                retrieval_results=0,
                elapsed_ms=elapsed,
                grounded=False,
            )

        # Step 2: Build context from evidence
        context, citations = self._build_context(retrieval.results)

        # Step 3: Build RAG prompt
        prompt = self._build_rag_prompt(question, context)

        # Step 4: Generate answer
        answer = self._generate(prompt)
        if not answer:
            elapsed = (time.time() - start) * 1000
            return RAGResponse(
                question=question,
                answer="Failed to generate an answer. Please check that Ollama is running.",
                citations=citations,
                retrieval_results=len(retrieval.results),
                elapsed_ms=elapsed,
                grounded=False,
            )

        # Step 5: Check for hallucination (Phase 3.2)
        context_texts = [r.text for r in retrieval.results]
        safety_check = self._check_answer_safety(question, answer, context_texts)
        answer = self._wrap_answer_with_safety_notice(answer, safety_check)

        elapsed = (time.time() - start) * 1000
        logger.info("RAG answer generated in %.1fms (%d citations)", elapsed, len(citations))

        return RAGResponse(
            question=question,
            answer=answer,
            citations=citations,
            retrieval_results=len(retrieval.results),
            elapsed_ms=elapsed,
            grounded=True,
        )

    def ask_file(
        self,
        question: str,
        file_path: str,
        top_k: int = TOP_K_DEFAULT,
    ) -> RAGResponse:
        """Ask a question about a specific file.

        Convenience method that sets scope to SELECTED_FILE.

        Args:
            question: The user's question about the file.
            file_path: Path to the file to query.
            top_k: Number of evidence chunks to use.

        Returns:
            RAGResponse grounded in the file's content.
        """
        return self.ask(
            question=question,
            scope=RetrievalScope.SELECTED_FILE,
            file_filter=[file_path],
            top_k=top_k,
        )

    def ask_file_direct(self, question: str, file_path: str, model: Optional[str] = None) -> RAGResponse:
        """Ask a question about a file using full-file context (Tier 1).

        Extracts all text from the file and sends it directly to the LLM
        without chunking or vector search. Faster and more accurate for
        files that fit in the context window.

        For audio/video files, forces Whisper transcription to ensure
        content is available for the LLM to reason about.

        Args:
            question: The user's question about the file.
            file_path: Path to the file to query.
            model: Optional model name to override the default LLM.

        Returns:
            RAGResponse with the answer.
        """
        import os
        logger.info("RAG direct ask: '%s' about '%s' (model=%s)", question[:50], file_path, model or self._model)
        start = time.time()

        file_path = os.path.abspath(file_path)

        # Detect modality using magic bytes + extension (handles extensionless files)
        from engines.config import detect_modality_and_ext
        modality, _detected_ext = detect_modality_and_ext(file_path)

        user_meta_text = self._get_user_metadata_text(file_path)

        if modality == "image":
            # For images: send directly to vision model (moondream) or LLM
            return self._ask_image_direct(question, file_path, start, user_meta_text=user_meta_text, model=model)
        elif modality in ("audio", "media"):
            full_text = self._extract_audio_text(file_path)
        elif modality == "video":
            full_text = self._extract_video_text(file_path)
        else:
            # Documents and other text-based files
            from .content_engine import UniversalContentEngine
            engine = UniversalContentEngine()
            full_text = engine.extract_full_text(file_path)

        if user_meta_text:
            full_text = f"{user_meta_text}\n\n{full_text}" if full_text else user_meta_text

        if not full_text or not full_text.strip():
            elapsed = (time.time() - start) * 1000
            error_msg = "Could not extract text from this file. "
            if modality in ("audio", "media"):
                error_msg += "Audio transcription failed. Ensure the file is a valid audio file."
            elif modality == "video":
                error_msg += "Video transcription failed. Ensure ffmpeg is installed and the file is valid."
            else:
                error_msg += "The file may be empty or in an unsupported format."
            return RAGResponse(
                question=question,
                answer=error_msg,
                citations=[],
                retrieval_results=0,
                elapsed_ms=elapsed,
                grounded=False,
            )

        # Bound very long transcripts so huge recordings do not blow the
        # LLM context window (hardware-conscious: 6.9 GiB RAM / CPU-only).
        if len(full_text) > DIRECT_MAX_CONTEXT:
            logger.info(
                "Direct context truncated from %d to %d chars",
                len(full_text), DIRECT_MAX_CONTEXT,
            )
            full_text = full_text[:DIRECT_MAX_CONTEXT] + "\n...[truncated]"

        # Build the direct prompt (more permissive than RAG prompt)
        file_name = os.path.basename(file_path)
        if modality in ("audio", "media"):
            prompt = self._build_audio_prompt(question, full_text, file_name)
        elif modality == "video":
            prompt = self._build_video_prompt(question, full_text, file_name)
        else:
            prompt = self._build_direct_prompt(question, full_text, file_name)

        # Generate answer
        answer = self._generate(prompt, model=model)
        if not answer:
            elapsed = (time.time() - start) * 1000
            return RAGResponse(
                question=question,
                answer="Failed to generate an answer. Please check that Ollama is running.",
                citations=[],
                retrieval_results=0,
                elapsed_ms=elapsed,
                grounded=False,
            )

        # Format reasoning tokens (<think>...</think>) into clean structured display
        formatted_answer = format_reasoning_answer(answer)

        elapsed = (time.time() - start) * 1000
        logger.info("Direct answer generated in %.1fms", elapsed)

        # Create a single citation for the whole file
        citations = [Citation(
            source_label=file_name,
            file_path=file_path,
            text_snippet=full_text[:100] + "..." if len(full_text) > 100 else full_text,
            score=1.0,
        )]

        # Phase 3.2: Check hallucination safety
        context_blocks = [full_text[:2000]]
        safety_check = self._check_answer_safety(question, answer, context_blocks)
        safe_answer = self._wrap_answer_with_safety_notice(formatted_answer, safety_check)

        return RAGResponse(
            question=question,
            answer=safe_answer,
            citations=citations,
            retrieval_results=1,
            elapsed_ms=elapsed,
            model=model or self._model,
            grounded=True,
        )

        elapsed = (time.time() - start) * 1000
        logger.info("Direct answer generated in %.1fms", elapsed)

        # Create a single citation for the whole file
        citations = [Citation(
            source_label=file_name,
            file_path=file_path,
            text_snippet=full_text[:100] + "..." if len(full_text) > 100 else full_text,
            score=1.0,
        )]

        return RAGResponse(
            question=question,
            answer=answer,
            citations=citations,
            retrieval_results=1,
            elapsed_ms=elapsed,
            grounded=True,
        )

    def _build_direct_prompt(self, question: str, full_text: str, file_name: str) -> str:
        """Build prompt for direct full-file context approach.

        This prompt encourages the LLM to reason, infer, count, and
        deduce rather than only reporting explicitly stated facts.

        Args:
            question: User's question.
            full_text: Complete extracted text of the file.
            file_name: Name of the source file.

        Returns:
            Complete prompt string.
        """
        return (
            "You are an intelligent assistant analyzing a document. "
            "Answer the user's question based on the document content below.\n\n"
            "INSTRUCTIONS:\n"
            "- Read the entire document carefully before answering.\n"
            "- Answer the question thoroughly and accurately.\n"
            "- If the answer is not stated directly, REASON and INFER from "
            "the available information. Count items, identify patterns, "
            "summarize themes, and draw logical conclusions.\n"
            "- Reference specific parts of the document when relevant "
            "(e.g., 'On Slide 3...', 'In Section 2...').\n"
            "- If you truly cannot find any relevant information, explain "
            "what the document does contain instead.\n"
            "- Be specific, detailed, and helpful.\n"
            "- Do NOT refuse to answer. Always provide the best possible "
            "response using the available content.\n\n"
            f"DOCUMENT: {file_name}\n"
            f"{'=' * 60}\n"
            f"{full_text}\n"
            f"{'=' * 60}\n\n"
            f"QUESTION: {question}\n\n"
            "ANSWER:"
        )

    # ------------------------------------------------------------------ #
    # Batch 4: multi-document reasoning + conversation follow-up resolution
    # ------------------------------------------------------------------ #
    _MULTI_DOC_INSTRUCTIONS = (
        "You are an assistant analyzing documents in the user's workspace.\n"
        "Your task is to identify and list every document from the CONTEXT that answers or matches the user's question.\n"
        "Rules:\n"
        "1. Recognize synonyms and semantic equivalencies: 'humans' or 'people' includes men, women, a couple, individuals, persons. A couple (man and woman) represents two humans. Numbers like 'two' include 2, pair, couple, both.\n"
        "2. For every matching file in CONTEXT, output a bullet point in the format:\n"
        "   - DOCUMENT: <filename> - <description of what is depicted and why it matches>\n"
        "3. List ALL matching files found from the CONTEXT. Do not output single words like '(Yes)'. Always describe each matching document.\n"
        "4. Base your answer strictly on the facts in the CONTEXT. Do not invent details not present in the CONTEXT.\n"
        "5. Treat all transcript, vision caption, and document evidence as authoritative."
    )

    def answer_multi(self, question: str, context: str, extra_instructions: str = None, use_cot: bool = False) -> str:
        """Generate a grounded answer from cross-document evidence context.

        Args:
            question: The user's question.
            context: Evidence context built by MultiDocumentContextBuilder.
            extra_instructions: Optional additional prompt guidance.
            use_cot: When True, append chain-of-thought instruction (reasoning
                lane). Fixes `build_rag_prompt() got unexpected use_cot` crash
                pattern from complementary project.

        Returns:
            Generated answer text, or empty string on failure.
        """
        if not context or not context.strip():
            return "No files closely related to your query were found in the indexed workspace."

        system = self._MULTI_DOC_INSTRUCTIONS
        if extra_instructions:
            system = f"{system}\n{extra_instructions}"
        user_prompt = f"CONTEXT:\n{context}\n\nQUESTION: {question}"
        if use_cot:
            user_prompt += (
                "\n\nThink step by step: identify relevant passages, extract key facts, "
                "combine across sources, then answer with [n] citations. Internal reasoning only."
            )
        ans = self._generate(user_prompt, system_prompt=system)
        try:
            from conversation.groundedness import strip_think

            ans = strip_think(ans or "")
        except Exception:
            pass
        return ans or "No files closely related to your query were found in the indexed workspace."

    def resolve_followup(self, question: str, history: str) -> str:
        """Rewrite a conversational follow-up into a standalone query.

        Args:
            question: The user's follow-up question.
            history: Serialized recent conversation history (or "").

        Returns:
            Standalone query text. Falls back to the original question when
            there is no history or the LLM is unavailable.
        """
        if not history or not history.strip():
            return question
        prompt = (
            "You rewrite conversational follow-up questions into standalone, "
            "self-contained search queries.\n\n"
            f"CONVERSATION HISTORY:\n{history}\n\n"
            f"FOLLOW-UP QUESTION: {question}\n\n"
            "TASK: Rewrite the follow-up as a standalone question that a search "
            "engine can answer without the history. Reply with ONLY the rewritten "
            "question, nothing else."
        )
        answer = self._generate(prompt)
        try:
            from conversation.groundedness import strip_think

            resolved = strip_think(answer or "")
        except Exception:
            resolved = (answer or "").strip().strip('"')
        if not resolved:
            return question
        return resolved

    def rerank_results(
        self, query: str, results: list
    ) -> list:
        """Use LLM to re-rank search results by relevance to the query.

        Sends the query and candidate results to the LLM and asks it
        to identify ALL results that answer the question.

        Args:
            query: The user's original search query.
            results: List of result dicts with 'text', 'file_path', 'score'.

        Returns:
            Filtered and re-ranked list of results (most relevant first).
        """
        if not results:
            return results

        # If only 1-2 results after modality filtering, skip re-ranking
        if len(results) <= 2:
            return results

        # Build a prompt asking the LLM to rank results
        candidates = ""
        for i, r in enumerate(results[:15]):  # Max 15 candidates
            text_snippet = r.get("text", "")[:150].replace("\n", " ")
            file_name = os.path.basename(r.get("file_path", ""))
            candidates += f"[{i+1}] File: {file_name} | Content: {text_snippet}\n"

        prompt = (
            "You are a search relevance judge. Given a user's search query and "
            "a list of candidate results, identify ALL results that are relevant "
            "to the query. Include every result that matches, not just the best one.\n\n"
            f"QUERY: {query}\n\n"
            f"CANDIDATES:\n{candidates}\n"
            "TASK: Return the numbers of ALL relevant results, comma-separated, "
            "in order of relevance (most relevant first).\n"
            "Include every result that could answer the query.\n"
            "If none are relevant, return: NONE\n\n"
            "RELEVANT RESULTS:"
        )

        answer = self._generate(prompt)
        if not answer or "NONE" in answer.upper():
            # LLM says none relevant — return all results as fallback
            return results[:5]

        # Parse the LLM's ranking
        try:
            import re
            numbers = [int(n.strip()) for n in re.findall(r'\d+', answer)]
            reranked = []
            seen = set()
            for n in numbers:
                if 1 <= n <= len(results) and n not in seen:
                    reranked.append(results[n - 1])
                    seen.add(n)
            if reranked:
                return reranked
        except Exception:
            pass

        # Fallback: return all results
        return results[:5]

    def _extract_audio_text(self, file_path: str) -> str:
        """Extract transcription from audio file using Whisper.

        Args:
            file_path: Path to the audio file.

        Returns:
            Transcribed text with timestamps, or empty string on failure.
        """
        try:
            from speech.speech_engine import SpeechEngine
            engine = SpeechEngine(model_size="base")
            result = engine.transcribe(file_path)

            if not result or not result.text:
                return ""

            # Build formatted transcript with timestamps
            if result.segments:
                parts = []
                for seg in result.segments:
                    if seg.text.strip():
                        time_label = self._format_timestamp(seg.start, seg.end)
                        parts.append(f"[{time_label}] {seg.text.strip()}")
                return "\n".join(parts)
            else:
                return result.text

        except Exception as e:
            logger.error("Audio text extraction failed: %s", e)
            return ""

    def _extract_video_text(self, file_path: str) -> str:
        """Extract transcription from video file (audio track via Whisper).

        Args:
            file_path: Path to the video file.

        Returns:
            Transcribed text with timestamps, or empty string on failure.
        """
        try:
            from video.video_engine import VideoEngine
            engine = VideoEngine()

            # Extract audio track
            audio_path = engine.extract_audio_track(file_path)
            if not audio_path:
                logger.error("Could not extract audio from video: %s", file_path)
                return ""

            try:
                # Transcribe the extracted audio
                text = self._extract_audio_text(audio_path)
                return text
            finally:
                import os
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass

        except Exception as e:
            logger.error("Video text extraction failed: %s", e)
            return ""

    def _build_audio_prompt(self, question: str, transcript: str, file_name: str) -> str:
        """Build prompt for asking questions about audio content.

        Args:
            question: User's question.
            transcript: Full transcript with timestamps.
            file_name: Audio file name.

        Returns:
            Complete prompt string.
        """
        return (
            "You are an intelligent assistant analyzing an audio recording transcript. "
            "Answer the user's question based on the transcript below.\n\n"
            "INSTRUCTIONS:\n"
            "- Read the entire transcript carefully before answering.\n"
            "- The transcript includes timestamps [MM:SS - MM:SS] for reference.\n"
            "- Answer the question thoroughly and accurately.\n"
            "- If the answer is not stated directly, REASON and INFER from "
            "what was said. Identify speakers, topics, key points, and conclusions.\n"
            "- Reference timestamps when relevant (e.g., 'At 2:30...').\n"
            "- If you truly cannot find relevant information, explain "
            "what the audio does contain instead.\n"
            "- Be specific, detailed, and helpful.\n"
            "- Do NOT refuse to answer.\n\n"
            f"AUDIO FILE: {file_name}\n"
            f"{'=' * 60}\n"
            f"TRANSCRIPT:\n{transcript}\n"
            f"{'=' * 60}\n\n"
            f"QUESTION: {question}\n\n"
            "ANSWER:"
        )

    def _build_video_prompt(self, question: str, transcript: str, file_name: str) -> str:
        """Build prompt for asking questions about video content.

        Args:
            question: User's question.
            transcript: Full transcript with timestamps.
            file_name: Video file name.

        Returns:
            Complete prompt string.
        """
        return (
            "You are an intelligent assistant analyzing a video recording transcript. "
            "Answer the user's question based on the transcript below.\n\n"
            "INSTRUCTIONS:\n"
            "- Read the entire transcript carefully before answering.\n"
            "- The transcript includes timestamps [MM:SS - MM:SS] for reference.\n"
            "- Answer the question thoroughly and accurately.\n"
            "- If the answer is not stated directly, REASON and INFER from "
            "what was said. Identify speakers, topics, key points, and conclusions.\n"
            "- Reference timestamps when relevant (e.g., 'At 5:15...').\n"
            "- If you truly cannot find relevant information, explain "
            "what the video discusses instead.\n"
            "- Be specific, detailed, and helpful.\n"
            "- Do NOT refuse to answer.\n\n"
            f"VIDEO FILE: {file_name}\n"
            f"{'=' * 60}\n"
            f"TRANSCRIPT:\n{transcript}\n"
            f"{'=' * 60}\n\n"
            f"QUESTION: {question}\n\n"
            "ANSWER:"
        )

    @staticmethod
    def _format_timestamp(start: float, end: float) -> str:
        """Format start-end timestamps as MM:SS - MM:SS."""
        def _fmt(s):
            s = int(s)
            if s >= 3600:
                return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
            return f"{s // 60}:{s % 60:02d}"
        return f"{_fmt(start)} - {_fmt(end)}"

    def _ask_image_direct(
        self, question: str, file_path: str, start_time: float, user_meta_text: str = "", model: Optional[str] = None
    ) -> RAGResponse:
        """Ask a question about an image using OCR + vision combined.

        Strategy:
        1. Try OCR first (fast, accurate for screenshots/text images)
        2. If OCR gets good text (>50 chars), use it directly — skip moondream
        3. If OCR fails, use moondream for visual understanding (slower)

        Args:
            question: The user's question about the image.
            file_path: Path to the image file.
            start_time: When processing started.
            user_meta_text: Optional user-curated metadata/notes text.
            model: Optional model name to override the default LLM.

        Returns:
            RAGResponse with the answer.
        """
        file_name = os.path.basename(file_path)
        ocr_text = ""
        image_description = ""

        if not user_meta_text:
            user_meta_text = self._get_user_metadata_text(file_path)

        # Step 1: Try OCR first (fast & bilingual for characters + digits)
        try:
            from vision.ocr_engine import OCREngine
            engine = OCREngine()
            res = engine.extract_text(file_path)
            if res and res.text:
                ocr_text = res.text.strip()
                logger.info("OCR extracted: %d chars (lang: %s, conf: %.2f)", len(ocr_text), res.language, res.confidence)
        except Exception as e:
            logger.debug("OCR failed: %s", e)

        # Step 2: If OCR got good text, use it directly (skip moondream)
        # For screenshots, signs, and text-heavy images, OCR is more accurate and faster
        if ocr_text and len(ocr_text) >= 20:
            combined_context = f"[Exact Text & Digits Extracted from Image]\n{ocr_text}"
        else:
            # Step 3: OCR failed or got little text — use moondream vision
            try:
                import base64
                with open(file_path, "rb") as f:
                    image_b64 = base64.b64encode(f.read()).decode("utf-8")

                response = requests.post(
                    f"{self._base_url}/api/generate",
                    json={
                        "model": VISION_MODEL,
                        "prompt": "Describe everything you see in this image in detail. Include all text, numbers, labels, objects, diagrams, code, people, colors, and layout.",
                        "images": [image_b64],
                        "stream": False,
                        "options": {"temperature": 0.2},
                    },
                    timeout=90,
                )

                if response.status_code == 200:
                    image_description = response.json().get("response", "").strip()
            except Exception as e:
                logger.debug("moondream failed: %s", e)

            # Build context from whatever we got
            if image_description and ocr_text:
                combined_context = f"[Visual Description]\n{image_description}\n\n[Partial Text Found]\n{ocr_text}"
            elif image_description:
                combined_context = f"[Visual Description of Image]\n{image_description}"
            elif ocr_text:
                combined_context = f"[Text Found in Image]\n{ocr_text}"
            elif user_meta_text:
                combined_context = ""
            else:
                elapsed = (time.time() - start_time) * 1000
                return RAGResponse(
                    question=question,
                    answer="Could not extract any content from this image. "
                           "The image may be too complex or contain no recognizable text/objects.",
                    citations=[],
                    retrieval_results=0,
                    elapsed_ms=elapsed,
                    grounded=False,
                )

        if user_meta_text:
            combined_context = f"{user_meta_text}\n\n{combined_context}".strip()

        prompt = (
            "You are analyzing an image. Below is the content extracted from the image. "
            "Answer the user's question based ONLY on this extracted content.\n\n"
            f"IMAGE FILE: {file_name}\n"
            f"{'=' * 50}\n"
            f"{combined_context}\n"
            f"{'=' * 50}\n\n"
            f"QUESTION: {question}\n\n"
            "INSTRUCTIONS:\n"
            "- Answer based ONLY on the extracted content above.\n"
            "- The 'Exact Text Content' section contains the actual text from the image — trust it.\n"
            "- Quote text directly when relevant.\n"
            "- Be specific, detailed, and accurate.\n"
            "- Do NOT make up information that isn't in the extracted content.\n\n"
            "ANSWER:"
        )

        answer = self._generate(prompt, model=model)
        elapsed = (time.time() - start_time) * 1000

        if not answer:
            return RAGResponse(
                question=question,
                answer="Failed to generate an answer. Please check that Ollama is running.",
                citations=[],
                retrieval_results=0,
                elapsed_ms=elapsed,
                grounded=False,
            )

        formatted_answer = format_reasoning_answer(answer)
        snippet = (ocr_text[:100] if ocr_text else (image_description[:100] if image_description else user_meta_text[:100]))
        return RAGResponse(
            question=question,
            answer=formatted_answer,
            citations=[Citation(
                source_label=file_name,
                file_path=file_path,
                text_snippet=(snippet + "...") if snippet else file_name,
                score=1.0,
            )],
            retrieval_results=1,
            elapsed_ms=elapsed,
            model=model or self._model,
            grounded=True,
        )

    def _ask_image_fallback(self, question: str, file_path: str, start_time: float) -> RAGResponse:
        """Fallback for image Q&A when moondream is unavailable.

        Uses OCR text extraction + qwen-local to answer.

        Args:
            question: The user's question.
            file_path: Path to the image.
            start_time: When processing started.

        Returns:
            RAGResponse (may be less accurate without vision).
        """
        from .content_engine import UniversalContentEngine
        engine = UniversalContentEngine()
        full_text = engine.extract_full_text(file_path)

        if not full_text or not full_text.strip():
            elapsed = (time.time() - start_time) * 1000
            return RAGResponse(
                question=question,
                answer="Could not extract content from this image. "
                       "Ensure Ollama is running with the moondream model for image analysis.",
                citations=[],
                retrieval_results=0,
                elapsed_ms=elapsed,
                grounded=False,
            )

        file_name = os.path.basename(file_path)
        prompt = self._build_direct_prompt(question, full_text, file_name)
        answer = self._generate(prompt)

        elapsed = (time.time() - start_time) * 1000
        if not answer:
            return RAGResponse(
                question=question,
                answer="Failed to generate an answer. Please check that Ollama is running.",
                citations=[],
                retrieval_results=0,
                elapsed_ms=elapsed,
                grounded=False,
            )

        return RAGResponse(
            question=question,
            answer=answer,
            citations=[Citation(
                source_label=file_name,
                file_path=file_path,
                text_snippet=full_text[:100] + "..." if len(full_text) > 100 else full_text,
                score=1.0,
            )],
            retrieval_results=1,
            elapsed_ms=elapsed,
            grounded=True,
        )

    def _build_context(self, results: List[RetrievalResult]) -> tuple:
        """Build context string and citations from retrieval results.

        Truncates to RAG_MAX_CONTEXT characters total.

        Args:
            results: Ranked retrieval results.

        Returns:
            Tuple of (context_string, citations_list).
        """
        context_parts = []
        citations = []
        total_chars = 0

        for r in results:
            if total_chars >= RAG_MAX_CONTEXT:
                break

            # Truncate individual chunk if needed
            remaining = RAG_MAX_CONTEXT - total_chars
            text = r.text[:remaining] if len(r.text) > remaining else r.text

            # Format evidence with source reference (OS-safe basename)
            from services.path_utils import basename as _base

            source_ref = f"[{r.source_label} | {_base(r.file_path)}]"
            context_parts.append(f"{source_ref}:\n{text}")
            total_chars += len(text)

            citations.append(Citation(
                source_label=r.source_label,
                file_path=r.file_path,
                text_snippet=text[:100] + "..." if len(text) > 100 else text,
                score=r.score,
            ))

        context = "\n\n---\n\n".join(context_parts)
        return context, citations

    def _build_rag_prompt(self, question: str, context: str) -> str:
        """Build the RAG prompt with question and evidence context.

        Args:
            question: User's question.
            context: Formatted evidence context.

        Returns:
            Complete prompt string.
        """
        return (
            "You are a helpful assistant that answers questions based ONLY on the "
            "provided context. If the context does not contain enough information "
            "to answer the question, say so clearly.\n\n"
            "RULES:\n"
            "- Answer ONLY based on the provided context below.\n"
            "- Be specific and detailed in your answer.\n"
            "- Reference the source when relevant (e.g., 'According to Page 3...').\n"
            "- If the context doesn't contain the answer, say 'The available "
            "documents do not contain this information.'\n"
            "- Do NOT make up information.\n\n"
            f"CONTEXT:\n{context}\n\n"
            f"QUESTION: {question}\n\n"
            "ANSWER:"
        )

    def _generate(self, prompt: str, system_prompt: Optional[str] = None, model: Optional[str] = None) -> str:
        """Call Ollama to generate a response using the chat API.

        Args:
            prompt: The complete user prompt to send.
            system_prompt: Optional system instruction prompt.
            model: Optional model name to override self._model.

        Returns:
            Generated text, or empty string on failure.
        """
        try:
            if self._resources is not None:
                with self._resources.llm():
                    response = self._post_generate(prompt, system_prompt=system_prompt, model=model)
            else:
                response = self._post_generate(prompt, system_prompt=system_prompt, model=model)

            if response.status_code != 200:
                logger.error(
                    "Ollama RAG generation failed (status %d): %s",
                    response.status_code,
                    response.text[:200],
                )
                return ""

            data = response.json()
            # Try to get chat message content first, then fallback to standard generate
            answer = ""
            if "message" in data:
                answer = data.get("message", {}).get("content", "").strip()
            if not answer:
                answer = data.get("response", "").strip()
            return answer

        except AIResourceUnavailable:
            logger.error("RAG generation skipped: AI resources busy or cancelled")
            return ""
        except requests.ConnectionError:
            logger.error("Cannot connect to Ollama at %s", self._base_url)
            return ""
        except requests.Timeout:
            logger.error("Ollama RAG request timed out after %ds", self._timeout)
            return ""
        except Exception as e:
            logger.error("RAG generation error: %s", e)
            return ""

    def _post_generate(self, prompt: str, system_prompt: Optional[str] = None, model: Optional[str] = None):
        """Raw POST to Ollama /api/chat (runs under the LLM resource slot) for chat template wrapping."""
        target_model = model or self._model
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            from core.config import Config

            from services.compute import ollama_options

            _opts = ollama_options(Config())
        except Exception:
            _opts = {}
        _opts = {**_opts, "temperature": self._temperature}
        return requests.post(
            f"{self._base_url}/api/chat",
            json={
                "model": target_model,
                "messages": messages,
                "stream": False,
                "options": _opts,
            },
            timeout=self._timeout,
        )
