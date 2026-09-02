"""Prompt builder for constructing AI analysis prompts."""

import logging

from .config import MAX_TEXT_CHUNK, PROMPT_VERSION

logger = logging.getLogger(__name__)

# Detail level configurations enforcing scaling and structured headings
DETAIL_LEVELS = {
    "low": {
        "about_instruction": "A brief overview explaining what the file is about (2-3 sentences).",
        "takeaways_instruction": "A JSON list of 2-3 important, concrete key takeaways from the document.",
        "keywords_instruction": "A list of 3-5 important keywords from the document.",
        "tags_instruction": "A list of 2-3 classification tags for the document.",
    },
    "medium": {
        "about_instruction": (
            "A detailed explanation of what the file is about, its purpose, scope, and subject matter "
            "(scales with text length: 3-5 sentences for short text, 1-2 paragraphs for longer text)."
        ),
        "takeaways_instruction": (
            "A JSON list of 4-6 detailed key takeaways of concrete findings, facts, figures, and decisions. "
            "Scale the count to match document length."
        ),
        "keywords_instruction": (
            "A list of 6-10 important keywords and key phrases from the document. "
            "Include technical terms and specific topics discussed."
        ),
        "tags_instruction": "A list of 4-6 classification tags for the document.",
    },
    "high": {
        "about_instruction": (
            "A comprehensive, deep-dive explanation of what the file is about, its purpose, background, "
            "and core themes (scales with text length: 1-2 paragraphs for short text, 3-4 paragraphs for longer text)."
        ),
        "takeaways_instruction": (
            "A JSON list of 8-15 highly specific, factual key takeaways extracting all key data points, "
            "names, dates, metrics, conclusions, and actions."
        ),
        "keywords_instruction": (
            "A list of 10-20 important keywords and key phrases from the document. "
            "Include technical terms, proper nouns, concepts, methodologies, "
            "and all specific topics discussed."
        ),
        "tags_instruction": (
            "A list of 5-10 classification tags for the document. "
            "Include document type, subject area, audience, purpose, and relevant domains."
        ),
    },
}


class PromptBuilder:
    """Builds structured prompts for document analysis.

    Constructs prompts that instruct the model to return
    structured JSON responses with specific fields.
    Supports detail levels: low, medium, high.
    """

    def build_analysis_prompt(self, text: str, detail_level: str = "medium") -> str:
        """Build a document analysis prompt for the given text.

        Truncates text to MAX_TEXT_CHUNK characters and constructs a prompt
        that requests structured JSON output at the specified detail level.

        Args:
            text: The document text to analyze.
            detail_level: One of 'low', 'medium', 'high'. Defaults to 'medium'.

        Returns:
            A formatted prompt string ready to send to the model.
        """
        logger.info(
            "Building analysis prompt (input length=%d chars, max=%d, level=%s)",
            len(text),
            MAX_TEXT_CHUNK,
            detail_level,
        )

        # Truncate text if it exceeds the maximum chunk size
        if len(text) > MAX_TEXT_CHUNK:
            truncated_text = text[:MAX_TEXT_CHUNK]
            logger.info(
                "Text truncated from %d to %d characters",
                len(text),
                MAX_TEXT_CHUNK,
            )
        else:
            truncated_text = text

        # Get detail level config
        level_config = DETAIL_LEVELS.get(detail_level, DETAIL_LEVELS["medium"])

        prompt = (
            f"# Document Analysis Task (prompt_version={PROMPT_VERSION})\n\n"
            "Analyze the following document text and return ONLY a valid JSON object.\n"
            "Do NOT include any explanation, commentary, or markdown formatting.\n"
            "Return ONLY the raw JSON object with these exact fields:\n\n"
            f"- \"about\": {level_config['about_instruction']}\n"
            f"- \"key_takeaways\": {level_config['takeaways_instruction']}\n"
            "- \"summary\": A brief 2-3 sentence overview summary paragraph of the file content.\n"
            f"- \"keywords\": {level_config['keywords_instruction']}\n"
            f"- \"tags\": {level_config['tags_instruction']}\n"
            "- \"category\": A single category that best describes the document type "
            "(e.g., \"technical\", \"legal\", \"financial\", \"medical\", \"academic\", "
            "\"presentation\", \"report\", \"tutorial\", \"research\", \"general\").\n"
            "- \"language\": The language the document is written in (e.g., \"English\", \"Spanish\").\n\n"
            "Expected JSON format:\n"
            "{\n"
            "  \"about\": \"...\",\n"
            "  \"key_takeaways\": [\"...\", \"...\", ...],\n"
            "  \"summary\": \"...\",\n"
            "  \"keywords\": [\"...\", \"...\", ...],\n"
            "  \"tags\": [\"...\", \"...\", ...],\n"
            "  \"category\": \"...\",\n"
            "  \"language\": \"...\"\n"
            "}\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Do NOT write generic abstract sentences or conversational introductions/conclusions ('trash talk').\n"
            "2. Focus strictly on extracting and presenting concrete, specific facts, proper nouns, data points, and key outcomes from the text.\n"
            "3. IMPORTANT: Scale the length and detail of your 'about' and 'key_takeaways' fields proportionally to the size of the input document (longer documents must receive much more detailed and thorough coverage).\n\n"
            "IMPORTANT: Return ONLY the JSON object. No other text before or after.\n\n"
            "--- DOCUMENT TEXT ---\n"
            f"{truncated_text}\n"
            "--- END OF DOCUMENT ---\n"
        )

        logger.info("Analysis prompt built successfully (%d chars total)", len(prompt))
        return prompt
