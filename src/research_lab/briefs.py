from __future__ import annotations

import json
import re
from pathlib import Path

from research_lab.models import ResearchBrief

SECTION_ALIASES = {
    "topic": "topic",
    "research topic": "topic",
    "question": "topic",
    "context": "context",
    "what i have done so far": "context",
    "progress so far": "context",
    "domains": "domains",
    "domain": "domains",
    "must include": "must_include",
    "must-use": "must_include",
    "must exclude": "must_exclude",
    "must-avoid": "must_exclude",
    "since year": "since_year",
    "iterations": "iterations",
    "per query": "per_query",
    "web per query": "web_per_query",
    "scholar per query": "scholar_per_query",
    "full text top n": "full_text_top_n",
    "llm rerank top n": "llm_rerank_top_n",
    "llm summary top n": "llm_summary_top_n",
    "top k": "top_k",
}

LIST_FIELDS = {"domains", "must_include", "must_exclude"}
INT_FIELDS = {
    "since_year",
    "iterations",
    "per_query",
    "web_per_query",
    "scholar_per_query",
    "full_text_top_n",
    "llm_rerank_top_n",
    "llm_summary_top_n",
    "top_k",
}


def parse_brief_markdown(text: str) -> ResearchBrief:
    sections = _parse_sections(text)
    payload: dict[str, object] = {}
    for section_name, body in sections.items():
        canonical = SECTION_ALIASES.get(section_name)
        if canonical is None:
            continue
        if canonical in LIST_FIELDS:
            payload[canonical] = _parse_list(body)
        elif canonical in INT_FIELDS:
            payload[canonical] = _parse_int(body)
        else:
            payload[canonical] = _normalize_block(body)

    topic = str(payload.get("topic", "")).strip()
    if not topic:
        raise ValueError(
            "brief markdown is missing a 'Topic' section "
            "(use a Markdown heading like '# Topic' or a label line like 'Topic:')"
        )

    return ResearchBrief.from_dict(payload)


def load_brief_json(path: Path) -> ResearchBrief:
    return ResearchBrief.from_dict(json.loads(path.read_text(encoding="utf-8")))


def load_brief_markdown(path: Path) -> ResearchBrief:
    return parse_brief_markdown(path.read_text(encoding="utf-8"))


def write_brief_json(path: Path, brief: ResearchBrief) -> None:
    path.write_text(json.dumps(brief.to_dict(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        heading = _parse_heading(line)
        if heading is not None:
            current = heading
            sections.setdefault(current, [])
            continue
        label = _parse_label(line)
        if label is not None:
            current = label
            sections.setdefault(current, [])
            continue
        if current is None:
            continue
        sections[current].append(raw_line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def _parse_heading(line: str) -> str | None:
    match = re.match(r"^#{1,6}\s+(.+?)\s*$", line.strip())
    if not match:
        return None
    heading = match.group(1).strip().lower()
    return re.sub(r"\s+", " ", heading)


def _parse_label(line: str) -> str | None:
    match = re.match(r"^([A-Za-z][A-Za-z0-9 :\-]+?):\s*$", line.strip())
    if not match:
        return None
    label = match.group(1).strip().lower()
    label = re.sub(r"\s+", " ", label)
    if label not in SECTION_ALIASES:
        return None
    return label


def _normalize_block(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    cleaned = [line for line in lines if line]
    return "\n".join(cleaned).strip()


def _parse_list(text: str) -> list[str]:
    items: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("- ", "* ")):
            items.append(line[2:].strip())
            continue
        if re.match(r"^\d+\.\s+", line):
            items.append(re.sub(r"^\d+\.\s+", "", line).strip())
            continue
        for piece in line.split(","):
            cleaned = piece.strip()
            if cleaned:
                items.append(cleaned)
    return items


def _parse_int(text: str) -> int | None:
    match = re.search(r"-?\d+", text)
    if not match:
        return None
    return int(match.group(0))
