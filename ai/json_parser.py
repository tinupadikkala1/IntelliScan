"""JSON parser for extracting and validating AI model responses."""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Required fields and their expected types
REQUIRED_FIELDS: dict[str, type] = {
    "summary": str,
    "keywords": list,
    "tags": list,
    "category": str,
    "language": str,
}


class JsonParser:
    """Parses and validates JSON responses from the AI model.

    Handles common issues like markdown code blocks, leading text,
    trailing commas, and single quotes.
    """

    def parse(self, raw_response: str) -> dict:
        """Parse a raw model response into a validated dictionary.

        Extracts JSON from the response, handles common formatting issues,
        and validates all required fields are present with correct types.

        Args:
            raw_response: The raw text response from the AI model.

        Returns:
            A validated dictionary with all required fields.

        Raises:
            ValueError: If the response cannot be parsed or validated.
        """
        logger.info("Parsing AI response (%d chars)", len(raw_response))

        if not raw_response or not raw_response.strip():
            logger.error("Empty response received")
            raise ValueError("Empty response from AI model - no content to parse.")

        # Extract JSON content from the response
        json_text = self._extract_json_text(raw_response)

        # Attempt to parse the JSON
        parsed = self._parse_json(json_text)

        # Validate required fields
        self._validate_fields(parsed)

        logger.info("JSON parsing and validation completed successfully")
        return parsed

    def _extract_json_text(self, raw: str) -> str:
        """Extract JSON text from a raw response.

        Handles markdown code blocks and leading/trailing non-JSON text.

        Args:
            raw: The raw response text.

        Returns:
            The extracted JSON string.
        """
        text = raw.strip()

        # Handle markdown code blocks: ```json ... ``` or ``` ... ```
        code_block_pattern = r'```(?:json)?\s*\n?(.*?)\n?\s*```'
        match = re.search(code_block_pattern, text, re.DOTALL)
        if match:
            logger.debug("Extracted JSON from markdown code block")
            return match.group(1).strip()

        # Try to find a JSON object by locating the first { and last }
        first_brace = text.find('{')
        last_brace = text.rfind('}')

        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            extracted = text[first_brace:last_brace + 1]
            logger.debug("Extracted JSON object from position %d to %d", first_brace, last_brace)
            return extracted

        # Return the original text as a last resort
        logger.debug("No JSON boundaries found, returning raw text")
        return text

    def _parse_json(self, json_text: str) -> dict:
        """Attempt to parse JSON text, with repair for common issues.

        Args:
            json_text: The JSON string to parse.

        Returns:
            The parsed dictionary.

        Raises:
            ValueError: If JSON cannot be parsed even after repairs.
        """
        # First attempt: direct parse
        try:
            result = json.loads(json_text)
            if isinstance(result, dict):
                return result
            raise ValueError(
                f"Expected a JSON object (dict), got {type(result).__name__}."
            )
        except json.JSONDecodeError:
            logger.debug("Direct JSON parse failed, attempting repairs")

        # Repair attempt: fix trailing commas
        repaired = self._fix_trailing_commas(json_text)

        # Repair attempt: replace single quotes with double quotes
        repaired = self._fix_single_quotes(repaired)

        # Second attempt after repairs
        try:
            result = json.loads(repaired)
            if isinstance(result, dict):
                logger.info("JSON parsed successfully after repairs")
                return result
            raise ValueError(
                f"Expected a JSON object (dict), got {type(result).__name__}."
            )
        except json.JSONDecodeError as exc:
            logger.error("JSON parsing failed after repair attempts: %s", exc)
            raise ValueError(
                f"Unable to parse AI response as JSON: {exc}. "
                f"Raw content (first 200 chars): {json_text[:200]}"
            ) from exc

    def _fix_trailing_commas(self, text: str) -> str:
        """Remove trailing commas before closing braces/brackets.

        Args:
            text: JSON text potentially containing trailing commas.

        Returns:
            Text with trailing commas removed.
        """
        # Remove trailing commas before } or ]
        return re.sub(r',\s*([}\]])', r'\1', text)

    def _fix_single_quotes(self, text: str) -> str:
        """Replace single quotes with double quotes for JSON compatibility.

        Only performs replacement if no double quotes are found (to avoid
        breaking strings that intentionally contain single quotes).

        Args:
            text: JSON text potentially using single quotes.

        Returns:
            Text with single quotes replaced by double quotes.
        """
        if '"' not in text and "'" in text:
            return text.replace("'", '"')
        return text

    def _validate_fields(self, data: dict) -> None:
        """Validate that all required fields exist with correct types.

        Args:
            data: The parsed dictionary to validate.

        Raises:
            ValueError: If any required field is missing or has wrong type.
        """
        missing_fields: list[str] = []
        type_errors: list[str] = []

        for field, expected_type in REQUIRED_FIELDS.items():
            if field not in data:
                missing_fields.append(field)
            elif not isinstance(data[field], expected_type):
                type_errors.append(
                    f"'{field}' must be {expected_type.__name__}, "
                    f"got {type(data[field]).__name__}"
                )

        errors: list[str] = []
        if missing_fields:
            errors.append(f"Missing required fields: {', '.join(missing_fields)}")
        if type_errors:
            errors.append(f"Type errors: {'; '.join(type_errors)}")

        if errors:
            error_msg = "; ".join(errors)
            logger.error("Validation failed: %s", error_msg)
            raise ValueError(f"Response validation failed: {error_msg}")
