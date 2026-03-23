from __future__ import annotations

import re
from pathlib import Path

RESOURCES_DIR = Path(__file__).parent


def load_resource(name: str) -> str:
    """리소스 파일 전체 로딩"""
    path = RESOURCES_DIR / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def load_domain_sections(*keywords: str) -> str:
    """pave_domain.md에서 키워드에 매칭되는 섹션만 추출"""
    text = load_resource("pave_domain.md")
    if not text:
        return ""

    sections = _parse_sections(text)
    matched = []
    for title, content in sections:
        title_lower = title.lower()
        for kw in keywords:
            if kw.lower() in title_lower:
                matched.append(content)
                break

    return "\n".join(matched)


def _parse_sections(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"^## .+", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        return [("", text)]
    sections = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = m.group().lstrip("# ").strip()
        sections.append((title, text[start:end].rstrip()))
    return sections
