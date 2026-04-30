from __future__ import annotations

import re
from collections import Counter

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
