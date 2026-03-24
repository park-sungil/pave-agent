from __future__ import annotations

import sys


def test_db():
    """Oracle DB 연결 테스트"""
    from config import settings
    from shared.db import execute_query

    print(f"[DB] DSN={settings.oracle_dsn}, USER={settings.oracle_user}")

    # PDK 버전 뷰 접속 확인
    rows = execute_query(
        "SELECT COUNT(*) AS CNT FROM antsdb.PAVE_PDK_VERSION_VIEW"
        " FETCH FIRST 1 ROWS ONLY"
    )
    print(f"[DB] PAVE_PDK_VERSION_VIEW 행 수: {rows[0]['CNT']}")

    # PPA 데이터 뷰 접속 확인
    rows = execute_query(
        "SELECT COUNT(*) AS CNT FROM antsdb.PAVE_PPA_DATA_VIEW d"
        " WHERE d.PDK_ID IS NOT NULL FETCH FIRST 1 ROWS ONLY"
    )
    print(f"[DB] PAVE_PPA_DATA_VIEW 행 수: {rows[0]['CNT']}")

    # 최신 PDK 샘플 조회
    rows = execute_query(
        "SELECT PAVE_PDK_ID, PROCESS, PROJECT_NAME, MASK, IS_GOLDEN"
        " FROM antsdb.PAVE_PDK_VERSION_VIEW"
        " ORDER BY PAVE_PDK_ID DESC"
        " FETCH FIRST 5 ROWS ONLY"
    )
    print("[DB] 최근 PDK 5건:")
    for r in rows:
        golden = "★" if r["IS_GOLDEN"] else " "
        print(f"  {golden} ID={r['PAVE_PDK_ID']}  {r['PROCESS']:<6}  {r['PROJECT_NAME']:<12}  {r['MASK']}")

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
    """E2E 그래프 테스트"""
    from langgraph.checkpoint.memory import MemorySaver
    from graph import build_graph

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "e2e-test"}}

    # DB에 실제 존재하는 project_name으로 교체 필요 시 .env에 TEST_PROJECT_NAME 지정
    import os
    question = os.getenv("TEST_QUESTION", "SF2 INV D1 LVT TT 데이터 보여줘")
    print(f"[E2E] 질문: '{question}'")

    graph.invoke({
        "user_question": question,
        "conversation_id": "e2e",
        "conversation_history": [],
        "screen_context": None,
    }, config)

    snapshot = graph.get_state(config)
    if snapshot.next:
        print(f"[E2E] interrupt 발생 (PDK 선택 필요): {snapshot.next}")
        print("[E2E] interrupt는 정상 동작입니다. /clarify 로 계속할 수 있습니다.")
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
