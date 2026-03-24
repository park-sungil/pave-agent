from __future__ import annotations

from typing import Literal

from langchain_openai import ChatOpenAI

from config import settings


def get_llm(tier: Literal["heavy", "light"]) -> ChatOpenAI:
    """heavy/light 2-tier LLM 클라이언트 반환 (사내 OpenAI 호환 API)"""
    model = settings.llm_model_heavy if tier == "heavy" else settings.llm_model_light
    return ChatOpenAI(
        model=model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=0,
    )
