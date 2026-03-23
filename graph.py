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
    """intent_parser 후 분기: distributed / fallback"""
    return state.get("route", "distributed")


def build_graph():
    """LangGraph 그래프 빌드"""
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

    # 조건부 분기: intent_parser → distributed / fallback
    builder.add_conditional_edges(
        "intent_parser",
        _route_after_intent,
        {
            "distributed": "pdk_resolver",
            "fallback": "fallback_agent",
        },
    )

    # 분산 파이프라인 엣지
    builder.add_edge("pdk_resolver", "query_builder")
    builder.add_edge("query_builder", "data_executor")
    builder.add_edge("data_executor", "analyzer")
    builder.add_edge("analyzer", "interpreter")
    builder.add_edge("interpreter", "visualizer")

    # fallback → visualizer (공유)
    builder.add_edge("fallback_agent", "visualizer")

    # 공유 엣지
    builder.add_edge("visualizer", "response_formatter")
    builder.add_edge("response_formatter", END)

    return builder.compile()


# 컴파일된 그래프 싱글턴
graph = build_graph()
