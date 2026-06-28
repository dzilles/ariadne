import os
import logging
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from src.ariadne.config.settings import settings
from src.ariadne.config.vault import Vault

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_llm() -> BaseChatModel:
    """
    Factory function to get the configured LLM instance.
    
    Returns:
        BaseChatModel: The configured LangChain chat model.
    
    Raises:
        ValueError: If the LLM provider is unknown or configuration is missing.
    """
    provider = settings.llm_backend.lower()
    
    if provider == "gemini":
        api_key = Vault.get_secret("LLM_API_KEY")
        model = settings.model

        if not api_key:
            raise ValueError("LLM_API_KEY is required for Gemini. Use '/secret LLM_API_KEY <key>'")

        if not model:
            raise ValueError("MODEL is not configured. Use '/settings model <model_name>'")

        logger.info(f"Initializing Gemini LLM with model: {model}")

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=0.7,
            max_retries=10,
            request_timeout=60
        )

    elif provider == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        model = settings.model

        if not model:
            raise ValueError("MODEL is not configured. Use '/settings model <model_name>'")

        logger.info(f"Initializing Ollama LLM with model: {model} at {base_url}")
        return ChatOllama(
            base_url=base_url,
            model=model,
            temperature=0.7
        )
        
    else:
        raise ValueError(f"Unknown LLM provider: {provider}. Supported: 'gemini', 'ollama'")
