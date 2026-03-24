from __future__ import annotations

import sys
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from graph import build_graph


# 노드별 출력할 state 키 및 포맷 정의
_NODE_DEBUG_KEYS: dict[str, list[str]] = {
    "intent_parser":      ["parsed_intent", "route"],
    "pdk_resolver":       ["pdk_resolution"],
    "query_builder":      ["query_plan"],
    "data_executor":      ["query_result"],
    "analyzer":           ["analysis_result"],
    "interpreter":        ["interpretation"],
    "visualizer":         ["chart_specs"],
    "response_formatter": ["final_response"],
    "fallback_agent":     ["fallback_result", "route"],
}


def _fmt_value(key: str, val) -> str:
    """state 값을 간결하게 포맷"""
    if val is None:
        return "None"

    if key == "parsed_intent":
        intent = val.get("intent", "?")
        entities = val.get("entities", {})
        missing = val.get("missing_params", [])
        parts = [f"intent={intent}", f"entities={entities}"]
        if missing:
            parts.append(f"missing={missing}")
        return ", ".join(parts)

    if key == "pdk_resolution":
        pdks = val.get("target_pdks", [])
        mode = val.get("comparison_mode", "?")
        defaults = val.get("applied_defaults", {})
        pdk_names = [f"{p.get('project_name','?')}(id={p.get('pdk_id','?')})" for p in pdks]
        parts = [f"mode={mode}", f"pdks={pdk_names}"]
        if defaults:
            parts.append(f"defaults={defaults}")
        return ", ".join(parts)

    if key == "query_plan":
        queries = val.get("queries", [])
        is_bulk = val.get("is_bulk", False)
        return f"queries={len(queries)}개, is_bulk={is_bulk}"

    if key == "query_result":
        total = val.get("total_rows", 0)
        warnings = val.get("warnings", [])
        parts = [f"total_rows={total}"]
        if warnings:
            parts.append(f"warnings={warnings}")
        return ", ".join(parts)

    if key == "analysis_result":
        mode = val.get("mode", "?")
        findings = val.get("findings", [])
        summary = val.get("summary_table", [])
        return f"mode={mode}, findings={len(findings)}개, summary_rows={len(summary)}"

    if key == "interpretation":
        insights = val.get("key_insights", [])
        recs = val.get("recommendations", [])
        charts = val.get("suggested_charts", [])
        preview = insights[0][:60] + "…" if insights else "(없음)"
        return f"insights={len(insights)}개, recs={len(recs)}개, charts={len(charts)}개 | 첫번째: {preview}"

    if key == "chart_specs":
        if isinstance(val, list):
            titles = [c.get("title", "?") for c in val]
            return f"{len(val)}개: {titles}"
        return str(val)

    if key == "final_response":
        text_preview = (val.get("text", "") or "")[:80].replace("\n", " ")
        tables = val.get("data_tables", [])
        charts = val.get("charts", [])
        return f"tables={len(tables)}개, charts={len(charts)}개 | {text_preview}…"

    if key == "fallback_result":
        if isinstance(val, dict):
            return str({k: str(v)[:60] for k, v in val.items()})
        return str(val)[:120]

    return str(val)[:120]


def _print_node_debug(chunk: dict) -> None:
    """stream chunk(노드 업데이트) 디버그 출력"""
    for node_name, node_output in chunk.items():
        print(f"\n  ┌─[NODE] {node_name}")
        if not isinstance(node_output, dict):
            print(f"  │  {node_output}")
        else:
            keys = _NODE_DEBUG_KEYS.get(node_name, list(node_output.keys()))
            for key in keys:
                if key in node_output:
                    print(f"  │  {key}: {_fmt_value(key, node_output[key])}")
            # error가 있으면 항상 표시
            if "error" in node_output and node_output["error"]:
                print(f"  │  error: {node_output['error']}")
        print(f"  └{'─' * 40}")


def _stream_run(graph, state_or_cmd, config, debug: bool) -> None:
    """graph.stream()으로 실행. debug=True 시 노드 진행상황 출력"""
    for chunk in graph.stream(state_or_cmd, config, stream_mode="updates"):
        if debug:
            _print_node_debug(chunk)


def _safe_input(prompt: str) -> str:
    """인코딩 무관하게 한국어 입력을 안전하게 읽기 (UTF-8 → CP949 → EUC-KR 순 시도)"""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    if hasattr(sys.stdin, "buffer"):
        raw = sys.stdin.buffer.readline()
        if not raw:
            raise EOFError
        raw = raw.rstrip(b"\r\n")
        for enc in ("utf-8", "cp949", "euc-kr"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")
    return input()


def main():
    """디버깅용 대화형 CLI (interrupt 지원)

    사용법:
        python chat.py           # 일반 모드
        python chat.py --debug   # 노드 흐름 + state 출력
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    debug = "--debug" in sys.argv

    print("=== pave-agent v8 CLI ===")
    if debug:
        print("[DEBUG MODE] 노드 흐름 출력 활성화")
    print("종료: quit / exit\n")

    graph = build_graph(checkpointer=MemorySaver())

    conversation_id = str(uuid.uuid4())[:8]
    history: list[dict] = []
    thread_counter = 0

    while True:
        try:
            question = _safe_input("질문> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break

        if not question or question.lower() in ("quit", "exit"):
            print("종료합니다.")
            break

        thread_counter += 1
        thread_id = f"{conversation_id}-{thread_counter}"
        config = {"configurable": {"thread_id": thread_id}}

        state = {
            "user_question": question,
            "conversation_id": conversation_id,
            "conversation_history": history,
            "screen_context": None,
        }

        try:
            _stream_run(graph, state, config, debug)

            # interrupt 처리 루프
            while True:
                snapshot = graph.get_state(config)
                if not snapshot.next:
                    break

                for task in snapshot.tasks:
                    if task.interrupts:
                        for intr in task.interrupts:
                            val = intr.value
                            q = val.get("question", str(val))
                            options = val.get("options", [])
                            print(f"\n[질문] {q}")
                            if options:
                                for i, opt in enumerate(options, 1):
                                    print(f"  {i}. {opt}")

                try:
                    answer = _safe_input("응답> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n취소합니다.")
                    break

                if not answer:
                    break

                _stream_run(graph, Command(resume=answer), config, debug)

            # 최종 결과 출력
            final = graph.get_state(config).values
            if final.get("error"):
                print(f"\n[ERROR] {final['error']}\n")
            elif final.get("final_response"):
                resp = final["final_response"]
                print(f"\n{resp['text']}")
                if resp.get("applied_defaults"):
                    defaults = ", ".join(
                        f"{k}={v}" for k, v in resp["applied_defaults"].items()
                    )
                    print(f"\n[적용 기본값] {defaults}")
                if resp.get("charts"):
                    print(f"[차트] {len(resp['charts'])}개 생성")
                print()
            else:
                print("\n[응답 없음]\n")

            history.append({"question": question, "summary": "..."})

        except Exception as e:
            print(f"\n[EXCEPTION] {type(e).__name__}: {e}\n")


if __name__ == "__main__":
    main()
