from __future__ import annotations

import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from graph import build_graph


def main():
    """디버깅용 대화형 CLI (interrupt 지원)"""
    print("=== pave-agent v8 CLI ===")
    print("종료: quit / exit\n")

    checkpointer = MemorySaver()
    graph = build_graph().with_config(checkpointer=checkpointer) if False else None
    # compile with checkpointer for interrupt support
    graph = build_graph()
    graph = graph.graph if hasattr(graph, "graph") else None

    # rebuild with checkpointer
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

    conversation_id = str(uuid.uuid4())[:8]
    history: list[dict] = []
    thread_counter = 0

    while True:
        try:
            question = input("질문> ").strip()
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
            result = graph.invoke(state, config)

            # interrupt 처리 루프
            while True:
                snapshot = graph.get_state(config)
                if not snapshot.next:
                    break

                # interrupt 질문 표시
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

                # 사용자 응답
                try:
                    answer = input("응답> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n취소합니다.")
                    break

                if not answer:
                    break

                result = graph.invoke(Command(resume=answer), config)

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
