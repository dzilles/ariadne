import os
import logging
from typing import Union
from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_env_config():
    """Loads environment variables from .config/.env or .env"""
    # Try loading from .config/.env first as seen in existing config.py
    config_path = os.path.join(os.getcwd(), ".config", ".env")
    if os.path.exists(config_path):
        load_dotenv(config_path)
    else:
        # Fallback to standard .env
        load_dotenv()

def get_llm() -> BaseChatModel:
    """
    Factory function to get the configured LLM instance.
    
    Returns:
        BaseChatModel: The configured LangChain chat model.
    
    Raises:
        ValueError: If the LLM provider is unknown or configuration is missing.
    """
    load_env_config()
    
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    
    if provider == "gemini":
        api_key = os.getenv("GOOGLE_API_KEY")
        model = os.getenv("GEMINI_MODEL", "gemini-pro")
        
        if not api_key:
            raise ValueError("GOOGLE_API_KEY is required for Gemini provider.")
            
        logger.info(f"Initializing Gemini LLM with model: {model}")
        
        # Configure with max_retries to enable exponential backoff for quota errors
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=0.7,
            max_retries=10,    # Retry up to 10 times
            request_timeout=60 # 60 seconds timeout per request
        )
        
    elif provider == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "llama2")
        
        logger.info(f"Initializing Ollama LLM with model: {model} at {base_url}")
        return ChatOllama(
            base_url=base_url,
            model=model,
            temperature=0.7
        )
        
    else:
        raise ValueError(f"Unknown LLM provider: {provider}. Supported: 'gemini', 'ollama'")
