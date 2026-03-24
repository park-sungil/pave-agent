from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """pave-agent 환경 설정"""

    # LLM 공통
    llm_provider: Literal["openai_compat", "anthropic"] = "openai_compat"

    # OpenAI 호환 API (prod: 사내 모델)
    llm_base_url: str = "http://localhost:8000/v1"
    llm_api_key: str = "no-key"
    llm_model_heavy: str = "GLM4.7"
    llm_model_light: str = "MiniMax-M2.1"

    # Anthropic (dev)
    anthropic_api_key: str = ""
    anthropic_model_heavy: str = "claude-sonnet-4-20250514"
    anthropic_model_light: str = "claude-haiku-4-5-20251001"

    # Oracle DB
    oracle_dsn: str = ""
    oracle_user: str = "antsdb"
    oracle_password: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
