from __future__ import annotations

import sys
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from graph import build_graph


def main():
    """디버깅용 대화형 CLI (interrupt 지원)"""
    # Windows 터미널 UTF-8 처리
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("=== pave-agent v8 CLI ===")
    print("종료: quit / exit\n")

    graph = build_graph(checkpointer=MemorySaver())

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
            graph.invoke(state, config)

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
                    answer = input("응답> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n취소합니다.")
                    break

                if not answer:
                    break

                graph.invoke(Command(resume=answer), config)

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
