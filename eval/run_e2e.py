"""E2E eval runner — 전체 파이프라인 시나리오 테스트

interrupt 없는 케이스만 자동 실행. interrupt 필요한 케이스는 수동 테스트 가이드 출력.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from langgraph.checkpoint.memory import MemorySaver
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
from nodes.pdk_lister import pdk_lister

RESULTS_DIR = Path(__file__).parent / "results"

# interrupt 없이 끝까지 가는 케이스 (SF2/Thetis = project 1개, 자동 특정)
E2E_CASES = [
    {
        "id": "E2E-01",
        "question": "Thetis INV D1 LVT 데이터 보여줘",
        "checks": {
            "has_response": True,
            "route": "distributed",
            "analysis_mode": "summarize",
            "has_charts": True,
        },
    },
    {
        "id": "E2E-02",
        "question": "Thetis에서 LVT랑 RVT 차이 얼마나 돼?",
        "checks": {
            "has_response": True,
            "route": "distributed",
            "analysis_mode": "compare",
        },
    },
    {
        "id": "E2E-03",
        "question": "Thetis에서 온도 올리면 leakage 얼마나 변해?",
        "checks": {
            "has_response": True,
            "route": "distributed",
            "analysis_mode": "sensitivity",
        },
    },
    {
        "id": "E2E-04",
        "question": "Thetis에서 가장 느린 조건이 뭐야?",
        "checks": {
            "has_response": True,
            "route": "distributed",
            "analysis_mode": "worst_case",
        },
    },
    {
        "id": "E2E-05",
        "question": "Thetis에서 freq_ghz랑 s_power 상관관계 보여줘",
        "checks": {
            "has_response": True,
            "route": "distributed",
            "analysis_mode": "correlation",
        },
    },
    {
        "id": "E2E-06",
        "question": "Thetis에서 low power에 어떤 Vth가 좋을까?",
        "checks": {
            "has_response": True,
            "route": "distributed",
            "analysis_mode": "tradeoff",
        },
    },
    {
        "id": "E2E-07",
        "question": "오늘 날씨 어때?",
        "checks": {
            "has_response": True,
            "route": "fallback",
        },
    },
    {
        "id": "E2E-08",
        "question": "DB에 어떤 PDK가 있어?",
        "checks": {
            "has_response": True,
            "route": "list",
        },
    },
    {
        "id": "E2E-09",
        "question": "SF3 버전 목록 보여줘",
        "checks": {
            "has_response": True,
            "route": "list",
        },
    },
]


def _build_graph():
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
    builder.add_node("pdk_lister", pdk_lister)

    builder.add_edge(START, "intent_parser")
    builder.add_conditional_edges("intent_parser", _route, {
        "distributed": "pdk_resolver",
        "list": "pdk_lister",
        "fallback": "fallback_agent",
    })
    builder.add_edge("pdk_resolver", "query_builder")
    builder.add_edge("query_builder", "data_executor")
    builder.add_edge("data_executor", "analyzer")
    builder.add_edge("analyzer", "interpreter")
    builder.add_edge("interpreter", "visualizer")
    builder.add_edge("fallback_agent", "visualizer")
    builder.add_edge("pdk_lister", "visualizer")
    builder.add_edge("visualizer", "response_formatter")
    builder.add_edge("response_formatter", END)

    return builder.compile(checkpointer=MemorySaver())


def run_case(graph, case: dict, idx: int) -> dict:
    config = {"configurable": {"thread_id": f"e2e-{idx}"}}
    checks = case["checks"]
    errors = []

    start = time.time()
    try:
        graph.invoke({
            "user_question": case["question"],
            "conversation_id": "e2e",
            "conversation_history": [],
            "screen_context": None,
        }, config)
    except Exception as e:
        return {
            "id": case["id"],
            "question": case["question"],
            "pass": False,
            "errors": [f"exception: {type(e).__name__}: {e}"],
            "duration_ms": round((time.time() - start) * 1000),
        }
    duration = round((time.time() - start) * 1000)

    snapshot = graph.get_state(config)
    if snapshot.next:
        # interrupt 발생 — 이 테스트에서는 실패
        return {
            "id": case["id"],
            "question": case["question"],
            "pass": False,
            "errors": [f"unexpected interrupt at {snapshot.next}"],
            "duration_ms": duration,
        }

    vals = snapshot.values

    # 체크: has_response
    if checks.get("has_response"):
        if not vals.get("final_response") or not vals["final_response"].get("text"):
            errors.append("final_response 없음")

    # 체크: error 없음
    if vals.get("error"):
        errors.append(f"error: {vals['error']}")

    # 체크: route
    if checks.get("route"):
        actual_route = vals.get("route")
        if actual_route != checks["route"]:
            errors.append(f"route: {actual_route} (expected: {checks['route']})")

    # 체크: analysis_mode
    if checks.get("analysis_mode") and vals.get("analysis_result"):
        actual_mode = vals["analysis_result"].get("mode")
        if actual_mode != checks["analysis_mode"]:
            errors.append(f"analysis_mode: {actual_mode} (expected: {checks['analysis_mode']})")

    # 체크: has_charts
    if checks.get("has_charts"):
        charts = vals.get("chart_specs") or []
        if not charts:
            errors.append("차트 없음")

    # 요약 수집
    summary = {
        "route": vals.get("route"),
        "analysis_mode": vals.get("analysis_result", {}).get("mode") if vals.get("analysis_result") else None,
        "charts": len(vals.get("chart_specs") or []),
        "response_len": len(vals.get("final_response", {}).get("text", "")),
        "findings": len(vals.get("analysis_result", {}).get("findings", [])) if vals.get("analysis_result") else 0,
    }

    return {
        "id": case["id"],
        "question": case["question"],
        "pass": len(errors) == 0,
        "errors": errors,
        "summary": summary,
        "duration_ms": duration,
    }


def main():
    graph = _build_graph()

    filter_ids = set(sys.argv[1:]) if len(sys.argv) > 1 else None
    results = []
    passed = failed = 0

    print(f"=== E2E eval ({len(E2E_CASES)} cases) ===\n")

    for i, case in enumerate(E2E_CASES):
        if filter_ids and case["id"] not in filter_ids:
            continue

        r = run_case(graph, case, i)
        results.append(r)

        status = "PASS" if r["pass"] else "FAIL"
        if r["pass"]:
            passed += 1
        else:
            failed += 1

        s = r.get("summary", {})
        print(f"[{status}] {r['id']}: {r['question'][:45]}")
        if r["errors"]:
            for e in r["errors"]:
                print(f"       {e}")
        print(f"       route={s.get('route')}, mode={s.get('analysis_mode')}, "
              f"charts={s.get('charts')}, resp={s.get('response_len')}자, {r['duration_ms']}ms")

    total = passed + failed
    print(f"\n{'='*50}")
    print(f"결과: {passed}/{total} ({round(passed/total*100) if total else 0}%)")

    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = RESULTS_DIR / f"e2e_{timestamp}.json"
    result_path.write_text(
        json.dumps({
            "timestamp": timestamp,
            "total": total, "passed": passed, "failed": failed,
            "results": results,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"결과 저장: {result_path}")


if __name__ == "__main__":
    main()
