from __future__ import annotations

import logging

from shared.db import execute_query

logger = logging.getLogger(__name__)

_SQL = """
    SELECT PDK_ID, PROCESS, PROJECT, PROJECT_NAME, MASK,
           DK_GDS, HSPICE, LVS, PEX, IS_GOLDEN, VDD_NOMINAL
    FROM antsdb.PAVE_PDK_VERSION_VIEW
    WHERE PROCESS IS NOT NULL
    ORDER BY PROCESS, PROJECT, MASK, IS_GOLDEN DESC
"""

_cache: list[dict] = []


def load() -> None:
    """앱 기동 시 PDK 목록 1회 로드"""
    global _cache
    try:
        _cache = execute_query(_SQL)
        logger.info("PDK 캐시 로드 완료: %d개", len(_cache))
    except Exception as e:
        logger.error("PDK 캐시 로드 실패: %s", e)
        _cache = []


def get() -> list[dict]:
    """캐시된 PDK 목록 반환. 미로드 시 자동 로드."""
    if not _cache:
        load()
    return list(_cache)


def reload() -> list[dict]:
    """강제 갱신 (수동 호출용)"""
    load()
    return list(_cache)
