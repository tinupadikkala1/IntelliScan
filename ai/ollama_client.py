"""Ollama API client for communicating with the local Ollama server."""

import logging
from typing import Optional

import requests

from .config import MODEL_NAME, OLLAMA_BASE_URL, TEMPERATURE, TIMEOUT

logger = logging.getLogger(__name__)


class OllamaClient:
    """Client for interacting with the Ollama REST API.

    Handles HTTP communication with the Ollama server, including
    text generation requests and availability checks.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
    ) -> None:
        """Initialize the Ollama client.

        Args:
            base_url: Ollama server URL. Defaults to config OLLAMA_BASE_URL.
            model: Model name to use. Defaults to config MODEL_NAME.
            temperature: Sampling temperature. Defaults to config TEMPERATURE.
            timeout: Request timeout in seconds. Defaults to config TIMEOUT.
        """
        self.base_url = (base_url or OLLAMA_BASE_URL).rstrip('/')
        self.model = model or MODEL_NAME
        self.temperature = temperature if temperature is not None else TEMPERATURE
        self.timeout = timeout if timeout is not None else TIMEOUT

        logger.info(
            "OllamaClient initialized: base_url=%s, model=%s, temperature=%s, timeout=%ds",
            self.base_url,
            self.model,
            self.temperature,
            self.timeout,
        )

    def generate(self, prompt: str, model: Optional[str] = None) -> str:
        """Generate a response from the Ollama model.

        Args:
            prompt: The text prompt to send to the model.
            model: Optional model name to override default self.model.

        Returns:
            The raw response text from Ollama.

        Raises:
            ConnectionError: If unable to connect to Ollama server.
            TimeoutError: If the request exceeds the timeout.
            RuntimeError: If the API returns a non-200 status code.
        """
        target_model = model or self.model
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": target_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a precise document analyzer. Your task is to output valid JSON ONLY. "
                        "Do not include any chat filler, intros, markdown code block wrappers (do not wrap in ```json), or extra text."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "stream": False,
            "options": {
                "temperature": self.temperature,
            },
        }

        logger.info("Starting chat generation request to %s (model=%s)", url, target_model)

        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
        except requests.exceptions.ConnectionError as exc:
            logger.error("Connection error to Ollama at %s: %s", url, exc)
            raise ConnectionError(
                f"Cannot connect to Ollama server at {self.base_url}. "
                "Ensure Ollama is running."
            ) from exc
        except requests.exceptions.Timeout as exc:
            logger.error("Timeout after %ds waiting for Ollama response", self.timeout)
            raise TimeoutError(
                f"Ollama request timed out after {self.timeout} seconds."
            ) from exc
        except requests.exceptions.RequestException as exc:
            logger.error("Unexpected request error: %s", exc)
            raise RuntimeError(f"Ollama request failed: {exc}") from exc

        if response.status_code != 200:
            logger.error(
                "Ollama returned status %d: %s",
                response.status_code,
                response.text[:200],
            )
            raise RuntimeError(
                f"Ollama API error (status {response.status_code}): {response.text[:200]}"
            )

        data = response.json()
        result = data.get("message", {}).get("content", "")
        if not result and "response" in data:
            result = data["response"]

        logger.info("Generation completed successfully (%d chars)", len(result))
        return result

    def is_available(self) -> bool:
        """Check if the Ollama server is running and reachable.

        Returns:
            True if Ollama server responds, False otherwise.
        """
        url = f"{self.base_url}/api/tags"
        logger.debug("Checking Ollama availability at %s", url)

        try:
            response = requests.get(url, timeout=5)
            available = response.status_code == 200
            logger.info("Ollama availability check: %s", available)
            return available
        except requests.exceptions.RequestException as exc:
            logger.warning("Ollama not available: %s", exc)
            return False
