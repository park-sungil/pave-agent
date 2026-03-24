from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """pave-agent 환경 설정"""

    # LLM — 사내 OpenAI 호환 API
    llm_base_url: str = "http://localhost:8000/v1"
    llm_api_key: str = "no-key"
    llm_model_heavy: str = "GLM4.7"
    llm_model_light: str = "MiniMax-M2.1"

    # Oracle DB
    oracle_dsn: str = ""
    oracle_user: str = "antsdb"
    oracle_password: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
