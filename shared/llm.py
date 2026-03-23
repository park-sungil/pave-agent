from __future__ import annotations

from typing import Literal

from config import settings


def get_llm(tier: Literal["heavy", "light"]):
    """heavy/light 2-tier LLM 클라이언트 반환

    Returns:
        ChatOpenAI 또는 ChatAnthropic 인스턴스
    """
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        model = (
            settings.anthropic_model_heavy
            if tier == "heavy"
            else settings.anthropic_model_light
        )
        return ChatAnthropic(
            model=model,
            api_key=settings.anthropic_api_key,
            temperature=0,
        )
    else:
        from langchain_openai import ChatOpenAI

        model = (
            settings.llm_model_heavy
            if tier == "heavy"
            else settings.llm_model_light
        )
        return ChatOpenAI(
            model=model,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            temperature=0,
        )
