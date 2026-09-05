"""Configuration constants for the AI module."""

# Model settings
MODEL_NAME: str = 'qwen-local:latest'
DEEPSEEK_MODEL_NAME: str = 'deepseek-r1-1.5b:latest'
TEMPERATURE: float = 0.3
TIMEOUT: int = 480  # seconds (8 minutes for large documents)

# Text processing
MAX_TEXT_CHUNK: int = 12000  # maximum characters sent to the model

# Prompt metadata
PROMPT_VERSION: str = '1.0'

# Ollama server
OLLAMA_BASE_URL: str = 'http://localhost:11434'
