from langchain_openai import ChatOpenAI

from app.config import get_settings


def get_llm(max_tokens: int = 2048) -> ChatOpenAI:
    """
    Return a configured LLM client from environment settings.

    Uses langchain-openai's ChatOpenAI, which speaks the OpenAI HTTP spec and
    works with any compatible endpoint: Ollama (default, free), Groq free tier,
    LM Studio, OpenRouter, or the real OpenAI API.

    Provider selection is controlled entirely by three env vars:
      LLM_BASE_URL  — API endpoint (default: http://ollama:11434/v1)
      LLM_MODEL     — model name as the provider expects it (default: llama3.2)
      LLM_API_KEY   — API key (Ollama ignores it; required non-empty by the HTTP client)
    """
    settings = get_settings()
    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=0,
        max_tokens=max_tokens,
        request_timeout=300,
        max_retries=0,
    )
