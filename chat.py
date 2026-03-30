from __future__ import annotations

import sys
import time
import traceback
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.theme import Theme
from rich import box

from graph import build_graph
import shared.pdk_cache as pdk_cache


_THEME = Theme({
    "node":    "bold white",
    "key":     "dim white",
    "val":     "white",
    "error":   "bold red",
    "warn":    "yellow",
    "prompt":  "bold white",
    "header":  "bold white",
    "default": "dim white",
    "info":    "dim white",
    "timing":  "dim cyan",
    "sql":     "dim yellow",
    "sample":  "dim green",
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
    """state 값을 간결하게 포맷 (debug 요약용)"""
    if val is None:
        return "None"

    if key == "parsed_intent":
        intent = val.get("intent", "?")
        entities = val.get("entities", {})
        missing = val.get("missing_params", [])
        hint = entities.get("analysis_hint")
        parts = [f"intent={intent}"]
        if hint:
            parts.append(f"hint={hint}")
        parts.append(f"entities={entities}")
        if missing:
            parts.append(f"missing={missing}")
        return ", ".join(parts)

    if key == "pdk_resolution":
        pdks = val.get("target_pdks", [])
        mode = val.get("comparison_mode", "?")
        defaults = val.get("applied_defaults", {})
        params = val.get("resolved_params", {})
        pdk_names = [f"{p.get('project_name','?')}(id={p.get('pdk_id','?')})" for p in pdks]
        parts = [f"mode={mode}", f"pdks={pdk_names}"]
        if params:
            parts.append(f"params={params}")
        if defaults:
            parts.append(f"defaults={defaults}")
        return ", ".join(parts)

    if key == "query_plan":
        queries = val.get("queries", [])
        is_bulk = val.get("is_bulk", False)
        purposes = [q.get("purpose", "?") for q in queries]
        return f"queries={len(queries)}개 {purposes}, is_bulk={is_bulk}"

    if key == "query_result":
        total = val.get("total_rows", 0)
        per_pdk = {str(k): v for k, v in val.get("rows_per_pdk", {}).items()}
        warnings = val.get("warnings", [])
        parts = [f"total_rows={total}"]
        if per_pdk:
            parts.append(f"per_pdk={per_pdk}")
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
        preview = insights[0][:80] + "…" if insights else "(없음)"
        return f"insights={len(insights)}개, recs={len(recs)}개, charts={len(charts)}개 | {preview}"

    if key == "chart_specs":
        if isinstance(val, list):
            titles = [c.get("title", "?") for c in val]
            return f"{len(val)}개: {titles}"
        return str(val)

    if key == "final_response":
        text_preview = (val.get("text", "") or "")[:100].replace("\n", " ")
        tables = val.get("data_tables", [])
        charts = val.get("charts", [])
        return f"tables={len(tables)}개, charts={len(charts)}개 | {text_preview}…"

    if key == "fallback_result":
        if isinstance(val, dict):
            return str({k: str(v)[:60] for k, v in val.items()})
        return str(val)[:120]

    return str(val)[:120]


def _print_verbose_extras(node_name: str, node_output: dict) -> None:
    """--verbose 시 노드별 심층 정보 추가 출력"""

    if node_name == "query_builder":
        queries = (node_output.get("query_plan") or {}).get("queries", [])
        for i, q in enumerate(queries, 1):
            sql = q.get("sql", "")
            purpose = q.get("purpose", "")
            if sql:
                console.print(f"  [sql]▸ SQL #{i} — {purpose}[/sql]")
                console.print(Syntax(sql, "sql", theme="monokai", word_wrap=True,
                                     background_color="default"))

    elif node_name == "data_executor":
        result = node_output.get("query_result") or {}
        rows_per_pdk = result.get("rows_per_pdk", {})
        for pdk_id, rows in rows_per_pdk.items():
            sample = rows[:3]  # 최대 3행
            if sample and isinstance(sample[0], dict):
                cols = list(sample[0].keys())
                tbl = Table(
                    title=f"[sample]PDK {pdk_id} 샘플 ({len(rows)}행 중 최대 3행)[/sample]",
                    box=box.MINIMAL,
                    header_style="dim green",
                    show_lines=False,
                    expand=False,
                )
                for c in cols:
                    tbl.add_column(c, max_width=14, overflow="fold")
                for row in sample:
                    tbl.add_row(*[str(row.get(c, "")) for c in cols])
                console.print(tbl)

    elif node_name == "analyzer":
        result = node_output.get("analysis_result") or {}
        findings = result.get("findings", [])
        if findings:
            console.print("  [key]findings:[/key]")
            for f in findings:
                console.print(f"    [val]• {f}[/val]")
        summary = result.get("summary_table", [])
        if summary and isinstance(summary[0], dict):
            cols = list(summary[0].keys())
            tbl = Table(
                title="summary_table",
                box=box.MINIMAL,
                header_style="dim white",
                show_lines=False,
                expand=False,
            )
            for c in cols:
                tbl.add_column(c, max_width=18, overflow="fold")
            for row in summary[:10]:
                tbl.add_row(*[str(row.get(c, "")) for c in cols])
            console.print(tbl)

    elif node_name == "interpreter":
        interp = node_output.get("interpretation") or {}
        narrative = interp.get("narrative", "")
        if narrative:
            console.print("  [key]narrative (전체):[/key]")
            console.print(Panel(narrative, border_style="dim", expand=False, padding=(0, 1)))
        recs = interp.get("recommendations", [])
        if recs:
            console.print("  [key]recommendations:[/key]")
            for r in recs:
                console.print(f"    [val]• {r}[/val]")

    elif node_name == "pdk_resolver":
        resolution = node_output.get("pdk_resolution") or {}
        pdks = resolution.get("target_pdks", [])
        if pdks:
            tbl = Table(
                title="target_pdks",
                box=box.MINIMAL,
                header_style="dim white",
                show_lines=False,
                expand=False,
            )
            for col in ["pdk_id", "process", "project_name", "mask", "dk_gds", "vdd_nominal"]:
                tbl.add_column(col, max_width=18, overflow="fold")
            for p in pdks:
                tbl.add_row(*[str(p.get(c, "")) for c in ["pdk_id", "process", "project_name", "mask", "dk_gds", "vdd_nominal"]])
            console.print(tbl)


def _print_node_debug(chunk: dict, verbose: bool, elapsed: float | None = None) -> None:
    """stream chunk(노드 업데이트) 디버그 출력"""
    for node_name, node_output in chunk.items():
        lines = []
        if elapsed is not None:
            lines.append(f"[timing]{elapsed:.2f}s[/timing]")

        if not isinstance(node_output, dict):
            lines.append(str(node_output))
        else:
            keys = _NODE_DEBUG_KEYS.get(node_name, list(node_output.keys()))
            for key in keys:
                if key in node_output:
                    lines.append(
                        f"[key]{key}:[/key] [val]{_fmt_value(key, node_output[key])}[/val]"
                    )
            if "error" in node_output and node_output["error"]:
                lines.append(f"[error]error: {node_output['error']}[/error]")

        console.print(Panel(
            "\n".join(lines) if lines else "(출력 없음)",
            title=f"[node]{node_name}[/node]",
            border_style="white",
            expand=False,
        ))

        if verbose and isinstance(node_output, dict):
            _print_verbose_extras(node_name, node_output)


def _print_data_table(dt: dict) -> None:
    """data_tables 항목을 rich Table로 렌더링"""
    headers = dt.get("headers", [])
    rows = dt.get("rows", [])
    title = dt.get("title", "")
    if not headers or not rows:
        return
    table = Table(title=title, box=box.SIMPLE_HEAVY, header_style="bold white", show_lines=False)
    for h in headers:
        table.add_column(h, overflow="fold")
    for row in rows:
        table.add_row(*[str(c) for c in row])
    console.print(table)


def _stream_run(graph, state_or_cmd, config, debug: bool, verbose: bool) -> list[str]:
    """graph.stream()으로 실행. 실행된 노드 이름 목록 반환."""
    t0 = time.monotonic()
    prev_t = t0
    executed: list[str] = []
    for chunk in graph.stream(state_or_cmd, config, stream_mode="updates"):
        now = time.monotonic()
        elapsed = now - prev_t
        prev_t = now
        executed.extend(chunk.keys())
        if debug:
            _print_node_debug(chunk, verbose, elapsed=elapsed)
    return executed


_input_history = InMemoryHistory()


def _safe_input(prompt: str) -> str:
    """한국어/영문 입력 — prompt_toolkit으로 IME 백스페이스 문제 해소"""
    return pt_prompt(prompt, history=_input_history)


def main():
    """디버깅용 대화형 CLI (interrupt 지원)

    사용법:
        python chat.py              # 일반 모드
        python chat.py --debug      # 노드 흐름 + state 요약 출력
        python chat.py --verbose    # --debug + SQL/데이터샘플/findings 전체 출력
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    verbose = "--verbose" in sys.argv
    debug = verbose or "--debug" in sys.argv

    console.rule("[header]pave-agent v8 CLI[/header]")
    if verbose:
        console.print("[warn][VERBOSE MODE] SQL · 데이터샘플 · findings 전체 출력 활성화[/warn]")
    elif debug:
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
            executed_nodes: list[str] = []
            executed_nodes += _stream_run(graph, state, config, debug, verbose)

            # interrupt 처리 루프
            while True:
                snapshot = graph.get_state(config)
                if not snapshot.next:
                    break

                for task in snapshot.tasks:
                    if task.interrupts:
                        for intr in task.interrupts:
                            val = intr.value
                            q = val.get("question", str(val)) if isinstance(val, dict) else str(val)
                            options = val.get("options", []) if isinstance(val, dict) else []
                            table_headers = val.get("table_headers") if isinstance(val, dict) else None
                            table_rows_data = val.get("table_rows", []) if isinstance(val, dict) else []
                            console.print(Panel(q, title="[warn]질문[/warn]", border_style="yellow"))
                            if table_headers:
                                tbl = Table(box=box.SIMPLE_HEAVY, show_header=True,
                                            header_style="bold white", show_lines=False)
                                tbl.add_column("#", style="bold white", width=3, justify="right")
                                for h in table_headers:
                                    tbl.add_column(h, style="white")
                                for i, row in enumerate(table_rows_data, 1):
                                    tbl.add_row(str(i), *[str(c) for c in row])
                                console.print(tbl)
                            elif options:
                                tbl = Table(box=box.SIMPLE_HEAVY, show_header=True,
                                            header_style="bold white", show_lines=False)
                                tbl.add_column("#", style="bold white", width=3, justify="right")
                                tbl.add_column("선택지", style="white")
                                for i, opt in enumerate(options, 1):
                                    tbl.add_row(str(i), opt)
                                console.print(tbl)

                try:
                    answer = _safe_input("응답> ").strip()
                except (EOFError, KeyboardInterrupt):
                    console.print("\n[info]취소합니다.[/info]")
                    break

                if not answer:
                    break

                executed_nodes += _stream_run(graph, Command(resume=answer), config, debug, verbose)

            # 최종 결과 출력
            final_snapshot = graph.get_state(config)
            final = final_snapshot.values
            console.rule()

            # 그래프가 interrupt 상태로 중단됨 (사용자가 입력 없이 종료)
            if final_snapshot.next:
                console.print("[warn]입력이 없어 취소되었습니다.[/warn]")
                if debug:
                    console.print(f"[key]중단 위치:[/key] [val]{final_snapshot.next}[/val]")
                console.rule()
                continue

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
                console.print("[error]응답 없음 — response_formatter가 호출되지 않았습니다.[/error]")
                # 항상 진단 정보 출력 (debug 불필요)
                console.print(f"[key]실행된 노드:[/key] [val]{executed_nodes or '없음'}[/val]")
                # LangGraph 태스크 오류 확인
                for task in final_snapshot.tasks:
                    err = getattr(task, "error", None)
                    if err:
                        console.print(f"[error]태스크 오류 [{task.name}]: {err}[/error]")
                if debug:
                    console.print("[warn]최종 state (None 제외):[/warn]")
                    for k, v in final.items():
                        if v is not None:
                            console.print(f"  [key]{k}:[/key] [val]{str(v)[:200]}[/val]")
            console.rule()

            history.append({"question": question, "summary": "..."})

        except Exception as e:
            console.print(Panel(
                traceback.format_exc(),
                title=f"[error]EXCEPTION: {type(e).__name__}[/error]",
                border_style="red",
            ))


if __name__ == "__main__":
    main()
