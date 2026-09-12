"""Configuration constants for the AI module."""

# Model settings (modern backend: 8B excluded, reasoning = 1.5B)
MODEL_NAME: str = 'qwen-local:latest'
LLM_MAIN_MODEL: str = 'qwen3:latest'
DEEPSEEK_MODEL_NAME: str = 'deepseek-r1-1.5b:latest'
VISION_MODEL_NAME: str = 'moondream:latest'
LIGHT_MODEL_NAME: str = 'qwen-local:latest'
RERANK_MODEL_NAME: str = 'ExpedientFalcon/qwen3-reranker:0.6b-q4_k_m'
WHISPER_BACKEND: str = 'faster-whisper'
WHISPER_MODEL_SIZE: str = 'small'
TEMPERATURE: float = 0.3
TIMEOUT: int = 480  # seconds (8 minutes for large documents)

# Text processing
MAX_TEXT_CHUNK: int = 12000  # maximum characters sent to the model

# Prompt metadata
PROMPT_VERSION: str = '1.0'

# Ollama server
OLLAMA_BASE_URL: str = 'http://localhost:11434'
