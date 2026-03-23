from __future__ import annotations

from langchain_core.tools import tool
from langgraph.types import interrupt


@tool
def ask_user(question: str) -> str:
    """분석에 필요한 정보가 부족할 때 사용자에게 질문한다.

    Args:
        question: 사용자에게 물어볼 질문. 구체적으로 작성.

    Returns:
        사용자의 응답 문자열.
    """
    response = interrupt({"question": question})
    if isinstance(response, dict):
        return response.get("clarification_response", str(response))
    return str(response)
