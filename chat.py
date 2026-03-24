from __future__ import annotations

import sys
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme
from rich import box

from graph import build_graph
import shared.pdk_cache as pdk_cache


_THEME = Theme({
    "node":    "bold bright_cyan",
    "key":     "bright_blue",
    "val":     "white",
    "error":   "bold bright_red",
    "warn":    "bold yellow",
    "prompt":  "bold bright_green",
    "header":  "bold bright_magenta",
    "default": "bright_yellow",
    "info":    "bright_black",
})
console = Console(theme=_THEME, highlight=False)


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
        lines = []
        if not isinstance(node_output, dict):
            lines.append(str(node_output))
        else:
            keys = _NODE_DEBUG_KEYS.get(node_name, list(node_output.keys()))
            for key in keys:
                if key in node_output:
                    lines.append(f"[key]{key}:[/key] [val]{_fmt_value(key, node_output[key])}[/val]")
            if "error" in node_output and node_output["error"]:
                lines.append(f"[error]error: {node_output['error']}[/error]")
        console.print(Panel(
            "\n".join(lines) if lines else "(출력 없음)",
            title=f"[node]{node_name}[/node]",
            border_style="cyan",
            expand=False,
        ))


def _print_data_table(dt: dict) -> None:
    """data_tables 항목을 rich Table로 렌더링"""
    headers = dt.get("headers", [])
    rows = dt.get("rows", [])
    title = dt.get("title", "")
    if not headers or not rows:
        return
    table = Table(title=title, box=box.SIMPLE_HEAVY, header_style="bold magenta", show_lines=False)
    for h in headers:
        table.add_column(h, overflow="fold")
    for row in rows:
        table.add_row(*[str(c) for c in row])
    console.print(table)


def _stream_run(graph, state_or_cmd, config, debug: bool) -> None:
    """graph.stream()으로 실행. debug=True 시 노드 진행상황 출력"""
    for chunk in graph.stream(state_or_cmd, config, stream_mode="updates"):
        if debug:
            _print_node_debug(chunk)


def _safe_input(prompt: str) -> str:
    """인코딩 무관하게 한국어 입력을 안전하게 읽기"""
    console.print(f"[prompt]{prompt}[/prompt]", end="")
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

    console.rule("[header]pave-agent v8 CLI[/header]")
    if debug:
        console.print("[warn][DEBUG MODE] 노드 흐름 출력 활성화[/warn]")
    console.print("[info]종료: quit / exit[/info]\n")

    pdk_cache.load()
    graph = build_graph(checkpointer=MemorySaver())

    conversation_id = str(uuid.uuid4())[:8]
    history: list[dict] = []
    thread_counter = 0

    while True:
        try:
            question = _safe_input("질문> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[info]종료합니다.[/info]")
            break

        if not question or question.lower() in ("quit", "exit"):
            console.print("[info]종료합니다.[/info]")
            break

        thread_counter += 1
        thread_id = f"{conversation_id}-{thread_counter}"
        config = {"configurable": {"thread_id": thread_id}}

        state = {
            "user_question": question,
            "conversation_id": conversation_id,
            "conversation_history": history,
            "screen_context": None,
            "available_pdks": pdk_cache.get(),
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
                            opts_text = "\n".join(f"  {i}. {o}" for i, o in enumerate(options, 1))
                            body = q + (f"\n{opts_text}" if opts_text else "")
                            console.print(Panel(body, title="[warn]질문[/warn]", border_style="yellow"))

                try:
                    answer = _safe_input("응답> ").strip()
                except (EOFError, KeyboardInterrupt):
                    console.print("\n[info]취소합니다.[/info]")
                    break

                if not answer:
                    break

                _stream_run(graph, Command(resume=answer), config, debug)

            # 최종 결과 출력
            final = graph.get_state(config).values
            console.rule()
            if final.get("error"):
                console.print(Panel(final["error"], title="[error]ERROR[/error]", border_style="red"))
            elif final.get("final_response"):
                resp = final["final_response"]
                # 본문 마크다운 렌더링
                console.print(Markdown(resp["text"]))
                # data_tables (text에 없는 경우 대비)
                for dt in resp.get("data_tables") or []:
                    _print_data_table(dt)
                # 적용 기본값
                if resp.get("applied_defaults"):
                    defaults = ", ".join(f"{k}={v}" for k, v in resp["applied_defaults"].items())
                    console.print(f"[default]적용 기본값: {defaults}[/default]")
                # 차트
                if resp.get("charts"):
                    console.print(f"[info]차트 {len(resp['charts'])}개 생성됨[/info]")
            else:
                console.print("[warn]응답 없음[/warn]")
            console.rule()

            history.append({"question": question, "summary": "..."})

        except Exception as e:
            console.print(Panel(f"{type(e).__name__}: {e}", title="[error]EXCEPTION[/error]", border_style="red"))


if __name__ == "__main__":
    main()
