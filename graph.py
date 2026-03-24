from __future__ import annotations

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


def _route_after_intent(state: PaveAgentState) -> str:
    """intent_parser 후 분기: distributed / list / fallback"""
    return state.get("route", "distributed")


def build_graph(checkpointer=None):
    """LangGraph 그래프 빌드

    Args:
        checkpointer: LangGraph checkpointer (interrupt/resume 지원 시 필요)
    """
    builder = StateGraph(PaveAgentState)

    # 노드 등록
    builder.add_node("intent_parser", intent_parser)
    builder.add_node("pdk_resolver", pdk_resolver)
    builder.add_node("query_builder", query_builder)
    builder.add_node("data_executor", data_executor)
    builder.add_node("analyzer", analyzer)
    builder.add_node("interpreter", interpreter)
    builder.add_node("visualizer", visualizer)
    builder.add_node("response_formatter", response_formatter)
    builder.add_node("fallback_agent", fallback_agent)

    # 엣지: START → intent_parser
    builder.add_edge(START, "intent_parser")

    # 조건부 분기: intent_parser → distributed / list / fallback
    builder.add_conditional_edges(
        "intent_parser",
        _route_after_intent,
        {
            "distributed": "pdk_resolver",
            "list": "response_formatter",
            "fallback": "fallback_agent",
        },
    )

    # 분산 파이프라인 엣지
    builder.add_edge("pdk_resolver", "query_builder")
    builder.add_edge("query_builder", "data_executor")
    builder.add_edge("data_executor", "analyzer")
    builder.add_edge("analyzer", "interpreter")
    builder.add_edge("interpreter", "visualizer")

    # fallback → visualizer
    builder.add_edge("fallback_agent", "visualizer")

    # 공유 엣지
    builder.add_edge("visualizer", "response_formatter")
    builder.add_edge("response_formatter", END)

    return builder.compile(checkpointer=checkpointer)


# 컴파일된 그래프 싱글턴 (checkpointer 없음 — API에서 별도 주입)
graph = build_graph()
