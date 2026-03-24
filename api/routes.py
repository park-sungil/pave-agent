from __future__ import annotations

import json
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from graph import build_graph
import shared.pdk_cache as pdk_cache

logger = logging.getLogger(__name__)

app = FastAPI(title="pave-agent", version="0.8.0")

# 앱 기동 시 PDK 카탈로그 1회 로드
pdk_cache.load()

# 체크포인터 (prod에서는 persistent store 사용)
_checkpointer = MemorySaver()
_graph = build_graph().compile(checkpointer=_checkpointer) if False else None


def _get_graph():
    global _graph
    if _graph is None:
        from langgraph.graph import StateGraph, START, END
        from state import PaveAgentState
        from nodes.intent_parser import intent_parser
        from nodes.pdk_resolver import pdk_resolver
        from nodes.query_builder import query_builder
        from nodes.data_executor import data_executor
        from nodes.analyzer import analyzer
        from nodes.interpreter import interpreter
        from nodes.visualizer import visualizer
        from nodes.response_formatter import response_formatter
        from nodes.fallback_agent import fallback_agent

        def _route(state):
            return state.get("route", "distributed")

        builder = StateGraph(PaveAgentState)
        builder.add_node("intent_parser", intent_parser)
        builder.add_node("pdk_resolver", pdk_resolver)
        builder.add_node("query_builder", query_builder)
        builder.add_node("data_executor", data_executor)
        builder.add_node("analyzer", analyzer)
        builder.add_node("interpreter", interpreter)
        builder.add_node("visualizer", visualizer)
        builder.add_node("response_formatter", response_formatter)
        builder.add_node("fallback_agent", fallback_agent)

        builder.add_edge(START, "intent_parser")
        builder.add_conditional_edges("intent_parser", _route, {
            "distributed": "pdk_resolver",
            "fallback": "fallback_agent",
        })
        builder.add_edge("pdk_resolver", "query_builder")
        builder.add_edge("query_builder", "data_executor")
        builder.add_edge("data_executor", "analyzer")
        builder.add_edge("analyzer", "interpreter")
        builder.add_edge("interpreter", "visualizer")
        builder.add_edge("fallback_agent", "visualizer")
        builder.add_edge("visualizer", "response_formatter")
        builder.add_edge("response_formatter", END)

        _graph = builder.compile(checkpointer=_checkpointer)
    return _graph


# --- Request/Response models ---

class AnalyzeRequest(BaseModel):
    question: str
    conversation_id: str = ""
    conversation_history: list[dict] = []
    screen_context: dict | None = None


class ClarifyRequest(BaseModel):
    conversation_id: str
    response: str


# --- Endpoints ---

@app.get("/api/v1/health")
async def health():
    return {"status": "healthy", "version": "0.8.0"}


@app.post("/api/v1/analyze")
async def analyze(req: AnalyzeRequest):
    """분석 요청 → SSE 스트리밍 응답"""
    graph = _get_graph()
    conv_id = req.conversation_id or str(uuid.uuid4())[:8]
    thread_id = f"{conv_id}-{uuid.uuid4().hex[:6]}"
    config = {"configurable": {"thread_id": thread_id}}

    state = {
        "user_question": req.question,
        "conversation_id": conv_id,
        "conversation_history": req.conversation_history,
        "screen_context": req.screen_context,
        "available_pdks": pdk_cache.get(),
    }

    async def event_stream():
        try:
            yield {"event": "progress", "data": json.dumps(
                {"stage": "parsing", "message": "질문 분석 중..."},
                ensure_ascii=False,
            )}

            graph.invoke(state, config)

            # interrupt 체크
            snapshot = graph.get_state(config)
            if snapshot.next:
                for task in snapshot.tasks:
                    if task.interrupts:
                        for intr in task.interrupts:
                            yield {"event": "clarification", "data": json.dumps(
                                {
                                    "question": intr.value.get("question", ""),
                                    "options": intr.value.get("options", []),
                                    "thread_id": thread_id,
                                },
                                ensure_ascii=False,
                            )}
                return

            # 완료
            final = snapshot.values
            if final.get("error"):
                yield {"event": "error", "data": json.dumps(
                    {"message": final["error"], "stage": "pipeline"},
                    ensure_ascii=False,
                )}
            elif final.get("final_response"):
                yield {"event": "result", "data": json.dumps(
                    final["final_response"], ensure_ascii=False, default=str,
                )}

            yield {"event": "done", "data": "{}"}

        except Exception as e:
            logger.error("analyze 에러: %s", e)
            yield {"event": "error", "data": json.dumps(
                {"message": str(e), "stage": "unknown"},
                ensure_ascii=False,
            )}

    return EventSourceResponse(event_stream())


@app.post("/api/v1/clarify")
async def clarify(req: ClarifyRequest):
    """interrupt resume — 사용자 응답 처리"""
    graph = _get_graph()

    # thread_id 찾기: conversation_id에서 가장 최근 thread
    # 간단 구현: clarify 요청에 thread_id를 포함하도록 프론트엔드에서 전달
    # 여기서는 conversation_id를 thread_id로 사용
    thread_id = req.conversation_id
    config = {"configurable": {"thread_id": thread_id}}

    async def event_stream():
        try:
            graph.invoke(Command(resume=req.response), config)

            snapshot = graph.get_state(config)

            # 추가 interrupt 체크
            if snapshot.next:
                for task in snapshot.tasks:
                    if task.interrupts:
                        for intr in task.interrupts:
                            yield {"event": "clarification", "data": json.dumps(
                                {
                                    "question": intr.value.get("question", ""),
                                    "options": intr.value.get("options", []),
                                    "thread_id": thread_id,
                                },
                                ensure_ascii=False,
                            )}
                return

            final = snapshot.values
            if final.get("error"):
                yield {"event": "error", "data": json.dumps(
                    {"message": final["error"]}, ensure_ascii=False,
                )}
            elif final.get("final_response"):
                yield {"event": "result", "data": json.dumps(
                    final["final_response"], ensure_ascii=False, default=str,
                )}

            yield {"event": "done", "data": "{}"}

        except Exception as e:
            logger.error("clarify 에러: %s", e)
            yield {"event": "error", "data": json.dumps(
                {"message": str(e)}, ensure_ascii=False,
            )}

    return EventSourceResponse(event_stream())
