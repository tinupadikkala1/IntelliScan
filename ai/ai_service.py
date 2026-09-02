"""AI service module orchestrating text analysis through Ollama."""

import logging
import time

from .json_parser import JsonParser
from .ollama_client import OllamaClient
from .prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


class AIService:
    """Orchestrates the AI analysis pipeline.

    Coordinates between prompt building, Ollama generation,
    and JSON parsing to produce structured analysis results.
    """

    def __init__(
        self,
        ollama_client: OllamaClient,
        prompt_builder: PromptBuilder,
        json_parser: JsonParser,
    ) -> None:
        """Initialize the AI service.

        Args:
            ollama_client: Client for communicating with Ollama.
            prompt_builder: Builder for constructing analysis prompts.
            json_parser: Parser for extracting and validating JSON responses.
        """
        self.ollama_client = ollama_client
        self.prompt_builder = prompt_builder
        self.json_parser = json_parser

        logger.info("AIService initialized")

    def analyze_text(self, text: str, detail_level: str = "medium") -> dict:
        """Analyze text and return structured metadata.

        Orchestrates the full pipeline: build prompt → call Ollama → parse JSON.

        Args:
            text: The document text to analyze.
            detail_level: One of 'low', 'medium', 'high'. Controls summary depth
                and keyword/tag count. Defaults to 'medium'.

        Returns:
            A dictionary with keys: summary, keywords, tags, category, language.
            On error, returns a dict with an 'error' key describing the failure.
        """
        logger.info("Starting text analysis (%d chars, level=%s)", len(text), detail_level)
        start_time = time.time()

        try:
            # Validate input
            if not text or not text.strip():
                logger.error("Empty text provided for analysis")
                return {"error": "Cannot analyze empty text."}

            # Step 1: Build the prompt (respect caller's requested detail level)
            prompt = self.prompt_builder.build_analysis_prompt(text, detail_level)

            # Step 2: Call Ollama
            raw_response = self.ollama_client.generate(prompt)

            if not raw_response or not raw_response.strip():
                logger.error("Ollama returned an empty response")
                return {"error": "AI model returned an empty response."}

            # Step 3: Parse and validate JSON
            result = self.json_parser.parse(raw_response)

            # Programmatically build structured summary from separate fields if present
            about = result.get("about", "")
            takeaways = result.get("key_takeaways", [])
            if about or takeaways:
                summary_parts = []
                if about:
                    summary_parts.append(f"### What the File is About\n{about.strip()}")
                if takeaways:
                    takeaways_formatted = "\n".join(f"- {t.strip()}" for t in takeaways if str(t).strip())
                    summary_parts.append(f"### Key Takeaways\n{takeaways_formatted}")
                if summary_parts:
                    result["summary"] = "\n\n".join(summary_parts)

            elapsed = time.time() - start_time
            logger.info("Text analysis completed in %.2fs", elapsed)
            return result

        except ConnectionError as exc:
            elapsed = time.time() - start_time
            logger.error("Connection error during analysis (%.2fs): %s", elapsed, exc)
            return {"error": f"Connection error: {exc}"}

        except TimeoutError as exc:
            elapsed = time.time() - start_time
            logger.error("Timeout during analysis (%.2fs): %s", elapsed, exc)
            return {"error": f"Timeout error: {exc}"}

        except ValueError as exc:
            elapsed = time.time() - start_time
            logger.error("Parse error during analysis (%.2fs): %s", elapsed, exc)
            return {"error": f"Response parsing error: {exc}"}

        except Exception as exc:
            elapsed = time.time() - start_time
            logger.error("Unexpected error during analysis (%.2fs): %s", elapsed, exc)
            return {"error": f"Unexpected error: {exc}"}
