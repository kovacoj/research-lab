from __future__ import annotations

from research_lab.lex import EXPANSION_STOPWORDS, extract_keywords, normalize_text
from research_lab.models import QueryRecord, ResearchBrief


def build_seed_queries(brief: ResearchBrief) -> list[QueryRecord]:
    topic = normalize_text(brief.topic)
    context = normalize_text(brief.context)
    topic_keywords = extract_keywords(topic, limit=6)
    context_keywords = extract_keywords(context, limit=8)

    raw_queries: list[tuple[str, str]] = [(topic, "topic")]
    if topic_keywords:
        raw_queries.append((" ".join(topic_keywords[:4]), "topic_keywords"))
    if context_keywords:
        raw_queries.append((f"{topic} {' '.join(context_keywords[:3])}", "topic_plus_context"))
    if brief.must_include:
        raw_queries.append((f"{topic} {' '.join(brief.must_include[:3])}", "must_include"))
    raw_queries.append((f"{topic} survey review", "survey"))
    raw_queries.append((f"{topic} benchmark", "benchmark"))

    seen: set[str] = set()
    queries: list[QueryRecord] = []
    for query, origin in raw_queries:
        normalized = normalize_text(query)
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        queries.append(QueryRecord(query=normalized, origin=origin, iteration=0))
    return queries


def build_expansion_queries(
    brief: ResearchBrief,
    top_titles: list[str],
    top_authors: list[str],
    iteration: int,
) -> list[QueryRecord]:
    raw_queries: list[tuple[str, str]] = []
    topic_keywords = set(extract_keywords(brief.topic, limit=8))
    for title in top_titles[:3]:
        title_keywords = [
            keyword
            for keyword in extract_keywords(title, limit=6)
            if keyword not in topic_keywords and keyword not in EXPANSION_STOPWORDS
        ]
        if title_keywords:
            raw_queries.append((f"{brief.topic} {' '.join(title_keywords[:2])}", "title_expansion"))
    for author in top_authors[:2]:
        raw_queries.append((f'"{author}" {brief.topic}', "author_expansion"))

    seen: set[str] = set()
    queries: list[QueryRecord] = []
    for query, origin in raw_queries:
        normalized = normalize_text(query)
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        queries.append(QueryRecord(query=normalized, origin=origin, iteration=iteration))
    return queries
