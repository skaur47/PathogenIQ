import asyncio
import re

import structlog
from langchain_openai import ChatOpenAI

from app.config import get_settings

logger = structlog.get_logger(__name__)


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


def _parse_groq_retry_wait(error_str: str, default: int = 900) -> int:
    """Parse 'try again in Xm Y.Zs' from Groq 429 error message. Default 15 min."""
    m = re.search(r"try again in (?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", error_str)
    if m and (m.group(1) or m.group(2)):
        minutes = int(m.group(1) or 0)
        seconds = float(m.group(2) or 0)
        return max(int(minutes * 60 + seconds) + 10, 60)
    return default


async def llm_invoke_with_retry(llm, messages: list, max_attempts: int = 3, **log_kwargs) -> str:
    """Invoke LLM and retry on Groq 429 rate-limit errors. Returns response.content."""
    for attempt in range(max_attempts):
        try:
            response = await llm.ainvoke(messages)
            return response.content
        except Exception as exc:
            if "429" not in str(exc) or attempt >= max_attempts - 1:
                raise
            wait = _parse_groq_retry_wait(str(exc))
            logger.warning("groq_rate_limit_retry", attempt=attempt + 1, wait_s=wait, **log_kwargs)
            await asyncio.sleep(wait)
    raise RuntimeError("unreachable")
