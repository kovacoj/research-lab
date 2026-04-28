from __future__ import annotations

import re
from collections import Counter

from research_lab.models import QueryRecord, ResearchBrief

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "by",
    "for",
    "from",
    "have",
    "how",
    "in",
    "into",
    "is",
    "it",
    "looked",
    "looking",
    "main",
    "methods",
    "notes",
    "of",
    "open",
    "on",
    "or",
    "papers",
    "paper",
    "practical",
    "question",
    "recent",
    "research",
    "smoke",
    "source",
    "sources",
    "strongest",
    "support",
    "supporting",
    "that",
    "the",
    "their",
    "this",
    "to",
    "using",
    "view",
    "we",
    "what",
    "with",
    "working",
    "your",
}

EXPANSION_STOPWORDS = {
    "accelerated",
    "analysis",
    "approach",
    "approaches",
    "benchmark",
    "benchmarks",
    "compilation",
    "deep",
    "distributed",
    "efficient",
    "exploring",
    "framework",
    "frameworks",
    "guide",
    "holistic",
    "inference",
    "learning",
    "model",
    "models",
    "modern",
    "neural",
    "novel",
    "review",
    "study",
    "studies",
    "system",
    "systems",
    "training",
}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]+", text.lower())


def extract_keywords(text: str, limit: int = 10) -> list[str]:
    counts = Counter(
        token
        for token in tokenize(text)
        if token not in STOPWORDS and len(token) > 3 and not token.isdigit()
    )
    return [token for token, _ in counts.most_common(limit)]


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
