from __future__ import annotations

from typing import Literal

from langchain_openai import ChatOpenAI

from app.core.config import get_settings

Provider = Literal["deepseek", "mimo"]


def get_langchain_chat_model(
    provider: Provider = "deepseek",
    temperature: float = 0.3,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    """
    Create a LangChain chat model using the project's existing model settings.

    This is intentionally low-intrusion:
    - it reuses existing environment variables from app.core.config
    - it does not replace app.services.llm_service
    - it is meant for new LangChain-based chains/agents only
    """
    settings = get_settings()

    if provider == "mimo":
        return ChatOpenAI(
            model=settings.MIMO_MODEL,
            api_key=settings.MIMO_API_KEY,
            base_url=settings.MIMO_BASE_URL,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    return ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
    )
