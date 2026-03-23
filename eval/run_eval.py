"""intent_parser eval runner — cases.json 기반 자동 채점"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from nodes.intent_parser import intent_parser

CASES_PATH = Path(__file__).parent / "cases.json"
RESULTS_DIR = Path(__file__).parent / "results"


def _check_intent(expected: dict, actual_intent: str) -> tuple[bool, str]:
    if "intent" not in expected:
        return True, ""
    exp = expected["intent"]
    # 복수 정답 허용
    if isinstance(exp, list):
        if actual_intent in exp:
            return True, ""
        return False, f"intent: {actual_intent} (expected: {exp})"
    if exp == actual_intent:
        return True, ""
    return False, f"intent: {actual_intent} (expected: {exp})"


def _check_list_field(expected: dict, entities: dict,
                      expected_key: str, entity_key: str) -> tuple[bool, str]:
    """expected의 리스트 필드가 entities에 포함되어 있는지"""
    if expected_key not in expected:
        return True, ""
    exp_vals = set(v.upper() if isinstance(v, str) else v for v in expected[expected_key])
    act_vals = set(v.upper() if isinstance(v, str) else v for v in entities.get(entity_key, []))
    if exp_vals.issubset(act_vals):
        return True, ""
    missing = exp_vals - act_vals
    return False, f"{entity_key}: missing {missing}"


def _check_metrics_contains(expected: dict, entities: dict) -> tuple[bool, str]:
    if "metrics_contains" not in expected:
        return True, ""
    exp = set(m.lower() for m in expected["metrics_contains"])
    act = set(m.lower() for m in entities.get("metrics", []))
    if exp.issubset(act):
        return True, ""
    missing = exp - act
    return False, f"metrics: missing {missing}"


def _check_missing_contains(expected: dict, missing_params: list[str]) -> tuple[bool, str]:
    """missing_params에 expected 항목이 포함되어 있는지"""
    if "missing_contains" not in expected:
        return True, ""
    exp = set(expected["missing_contains"])
    act = set(missing_params)
    if exp.issubset(act):
        return True, ""
    missing = exp - act
    return False, f"missing_params: {list(missing)} 누락 (actual: {missing_params})"


def _check_hint(expected: dict, entities: dict) -> tuple[bool, str]:
    if "hint" not in expected:
        return True, ""
    actual = entities.get("analysis_hint")
    if expected["hint"] == actual:
        return True, ""
    return False, f"hint: {actual} (expected: {expected['hint']})"


def evaluate_case(case: dict) -> dict:
    """단일 케이스 평가"""
    question = case["question"]
    expected = case["expected"]

    state = {
        "user_question": question,
        "conversation_id": "eval",
        "conversation_history": [],
        "screen_context": None,
    }

    start = time.time()
    try:
        result = intent_parser(state)
    except Exception as e:
        return {
            "id": case["id"],
            "question": question,
            "pass": False,
            "errors": [f"exception: {e}"],
            "duration_ms": round((time.time() - start) * 1000),
        }
    duration = round((time.time() - start) * 1000)

    pi = result["parsed_intent"]
    actual_intent = pi["intent"]
    entities = pi["entities"]

    errors = []

    # 채점
    missing_params = pi.get("missing_params", [])
    checks = [
        _check_intent(expected, actual_intent),
        _check_list_field(expected, entities, "processes", "processes"),
        _check_list_field(expected, entities, "vths", "vths"),
        _check_list_field(expected, entities, "cells", "cells"),
        _check_list_field(expected, entities, "drive_strengths", "drive_strengths"),
        _check_list_field(expected, entities, "cell_heights", "cell_heights"),
        _check_metrics_contains(expected, entities),
        _check_hint(expected, entities),
        _check_missing_contains(expected, missing_params),
    ]

    for passed, msg in checks:
        if not passed:
            errors.append(msg)

    return {
        "id": case["id"],
        "question": question,
        "pass": len(errors) == 0,
        "errors": errors,
        "actual": {
            "intent": actual_intent,
            "hint": entities.get("analysis_hint"),
            "missing": missing_params,
            "key_entities": {
                k: v for k, v in entities.items()
                if v and k != "analysis_hint"
            },
        },
        "duration_ms": duration,
    }


def main():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))

    # 특정 케이스만 실행: python run_eval.py IP-05 IP-11
    filter_ids = set(sys.argv[1:]) if len(sys.argv) > 1 else None

    results = []
    passed = 0
    failed = 0

    print(f"=== intent_parser eval ({len(cases)} cases) ===\n")

    for case in cases:
        if filter_ids and case["id"] not in filter_ids:
            continue

        r = evaluate_case(case)
        results.append(r)

        status = "PASS" if r["pass"] else "FAIL"
        if r["pass"]:
            passed += 1
        else:
            failed += 1

        print(f"[{status}] {r['id']}: {r['question'][:40]}")
        if r["errors"]:
            for e in r["errors"]:
                print(f"       {e}")
        print(f"       → intent={r['actual']['intent']}, hint={r['actual']['hint']}, {r['duration_ms']}ms")

    total = passed + failed
    print(f"\n{'='*50}")
    print(f"결과: {passed}/{total} ({round(passed/total*100) if total else 0}%)")
    print(f"PASS: {passed}, FAIL: {failed}")

    # 결과 저장
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = RESULTS_DIR / f"eval_{timestamp}.json"
    result_path.write_text(
        json.dumps({
            "timestamp": timestamp,
            "total": total,
            "passed": passed,
            "failed": failed,
            "accuracy": round(passed / total * 100, 1) if total else 0,
            "results": results,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n결과 저장: {result_path}")


if __name__ == "__main__":
    main()
