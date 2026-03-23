from __future__ import annotations

import sys


def test_db():
    """DB 연결 테스트"""
    from shared.db import execute_query
    from shared.mock_data import create_mock_db

    print("[DB] mock DB 생성...")
    print(create_mock_db())

    rows = execute_query("SELECT COUNT(*) AS cnt FROM antsdb.PAVE_PPA_DATA_VIEW d WHERE d.PDK_ID = 900 FETCH FIRST 1 ROWS ONLY")
    print(f"[DB] PDK 900 행 수: {rows[0]['cnt']}")
    print("[DB] OK\n")


def test_llm():
    """LLM 연결 테스트"""
    from shared.llm import get_llm
    from langchain_core.messages import HumanMessage

    for tier in ("light", "heavy"):
        llm = get_llm(tier)
        resp = llm.invoke([HumanMessage(content="Say 'OK' only.")])
        print(f"[LLM-{tier}] {resp.content[:50]}")
    print("[LLM] OK\n")


def test_graph():
    """E2E 그래프 테스트 (SF2 — project 1개, interrupt 없음)"""
    from langgraph.checkpoint.memory import MemorySaver
    from graph import build_graph

    checkpointer = MemorySaver()

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

    graph = builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "e2e-test"}}

    print("[E2E] 'Thetis INV D1 LVT 데이터 보여줘' 실행 중...")
    graph.invoke({
        "user_question": "Thetis INV D1 LVT 데이터 보여줘",
        "conversation_id": "e2e",
        "conversation_history": [],
        "screen_context": None,
    }, config)

    snapshot = graph.get_state(config)
    if snapshot.next:
        print(f"[E2E] interrupt 발생: {snapshot.next}")
    else:
        final = snapshot.values
        if final.get("error"):
            print(f"[E2E] ERROR: {final['error']}")
        elif final.get("final_response"):
            resp = final["final_response"]
            print(f"[E2E] 응답:\n{resp['text'][:300]}")
            print(f"[E2E] 차트: {len(resp.get('charts', []))}개")
            print(f"[E2E] 기본값: {resp.get('applied_defaults', {})}")
        print("[E2E] OK\n")


if __name__ == "__main__":
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["db", "llm", "graph"]

    if "db" in targets:
        test_db()
    if "llm" in targets:
        test_llm()
    if "graph" in targets:
        test_graph()
