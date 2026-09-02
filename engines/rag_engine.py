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
    ) -> None:
        """Initialize the RAG engine.

        Args:
            retrieval_engine: The retrieval engine for evidence lookup.
            model: Ollama model name for generation.
            base_url: Ollama server URL.
            temperature: Generation temperature.
            timeout: Request timeout in seconds.
            resources: Optional AIResourceManager to bound LLM generation.
        """
        self._retrieval = retrieval_engine
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._temperature = temperature
        self._timeout = timeout
        self._resources = resources

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

    def ask_file_direct(self, question: str, file_path: str) -> RAGResponse:
        """Ask a question about a file using full-file context (Tier 1).

        Extracts all text from the file and sends it directly to the LLM
        without chunking or vector search. Faster and more accurate for
        files that fit in the context window.

        For audio/video files, forces Whisper transcription to ensure
        content is available for the LLM to reason about.

        Args:
            question: The user's question about the file.
            file_path: Path to the file to query.

        Returns:
            RAGResponse with the answer.
        """
        import os
        logger.info("RAG direct ask: '%s' about '%s'", question[:50], file_path)
        start = time.time()

        file_path = os.path.abspath(file_path)

        # Detect modality using magic bytes + extension (handles extensionless files)
        from engines.config import detect_modality_and_ext
        modality, _detected_ext = detect_modality_and_ext(file_path)

        if modality == "image":
            # For images: send directly to vision model (moondream)
            return self._ask_image_direct(question, file_path, start)
        elif modality in ("audio", "media"):
            full_text = self._extract_audio_text(file_path)
        elif modality == "video":
            full_text = self._extract_video_text(file_path)
        else:
            # Documents and other text-based files
            from .content_engine import UniversalContentEngine
            engine = UniversalContentEngine()
            full_text = engine.extract_full_text(file_path)

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
        answer = self._generate(prompt)
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
        "You are an intelligent workspace AI assistant analyzing documents, images, audio transcripts, and video transcripts.\n"
        "INSTRUCTIONS:\n"
        "- The EVIDENCE below contains full extracted body text, OCR, vision captions, and complete Whisper speech transcripts from audio (.mp3, .wav) and video (.mp4, .mkv) files.\n"
        "- Treat audio and video transcripts as the complete, authoritative content of those media files.\n"
        "- NEVER claim that you cannot analyze audio or video files. NEVER issue disclaimers or refusals.\n"
        "- Provide a direct, thorough, comprehensive, and detailed answer using all available transcript and document evidence.\n"
        "- Reference source labels when attributing details."
    )


    def answer_multi(self, question: str, context: str, extra_instructions: str = None) -> str:
        """Generate a grounded answer from cross-document evidence context.

        Args:
            question: The user's question.
            context: Evidence context built by MultiDocumentContextBuilder.
            extra_instructions: Optional additional prompt guidance.

        Returns:
            Generated answer text, or empty string on failure.
        """
        instructions = self._MULTI_DOC_INSTRUCTIONS
        if extra_instructions:
            instructions = f"{instructions}\n{extra_instructions}"
        prompt = (
            f"{instructions}\n\n"
            f"CONTEXT:\n{context}\n\n"
            f"QUESTION: {question}\n\n"
            "ANSWER:"
        )
        return self._generate(prompt)

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
        resolved = answer.strip().strip('"')
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

    def _ask_image_direct(self, question: str, file_path: str, start_time: float) -> RAGResponse:
        """Ask a question about an image using OCR + vision combined.

        Strategy:
        1. Try OCR first (fast, accurate for screenshots/text images)
        2. If OCR gets good text (>50 chars), use it directly — skip moondream
        3. If OCR fails, use moondream for visual understanding (slower)

        Args:
            question: The user's question about the image.
            file_path: Path to the image file.
            start_time: When processing started.

        Returns:
            RAGResponse with the answer.
        """
        file_name = os.path.basename(file_path)
        ocr_text = ""
        image_description = ""

        # Step 1: Try OCR first (fast)
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(file_path)
            ocr_text = pytesseract.image_to_string(img).strip()
            if ocr_text:
                logger.info("OCR extracted: %d chars", len(ocr_text))
        except Exception as e:
            logger.debug("OCR failed: %s", e)

        # Step 2: If OCR got good text, use it directly (skip moondream)
        # For screenshots and text-heavy images, OCR is more accurate and faster
        if ocr_text and len(ocr_text) > 50:
            combined_context = f"[Exact Text Content from Image]\n{ocr_text}"
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
                text_snippet=(ocr_text[:100] if ocr_text else image_description[:100]) + "...",
                score=1.0,
            )],
            retrieval_results=1,
            elapsed_ms=elapsed,
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

            # Format evidence with source reference
            source_ref = f"[{r.source_label} | {r.file_path.split('/')[-1]}]"
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

    def _generate(self, prompt: str) -> str:
        """Call Ollama to generate a response using the chat API.

        Args:
            prompt: The complete prompt to send.

        Returns:
            Generated text, or empty string on failure.
        """
        try:
            if self._resources is not None:
                with self._resources.llm():
                    response = self._post_generate(prompt)
            else:
                response = self._post_generate(prompt)

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

    def _post_generate(self, prompt: str):
        """Raw POST to Ollama /api/chat (runs under the LLM resource slot) for chat template wrapping."""
        return requests.post(
            f"{self._base_url}/api/chat",
            json={
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": self._temperature},
            },
            timeout=self._timeout,
        )
