from __future__ import annotations

from dataclasses import dataclass

from research_lab.models import QueryRecord


@dataclass(slots=True)
class SourceBudget:
    enabled: bool
    requests_remaining: int

    def can_use(self) -> bool:
        return self.enabled and self.requests_remaining > 0

    def consume(self) -> None:
        self.requests_remaining -= 1

    def disable(self) -> None:
        self.enabled = False


class RetrievalPlan:
    def __init__(self, has_semantic_scholar_api_key: bool, scholar_per_query: int) -> None:
        self.arxiv = SourceBudget(enabled=True, requests_remaining=6)
        self.semantic_scholar = SourceBudget(
            enabled=has_semantic_scholar_api_key,
            requests_remaining=999 if has_semantic_scholar_api_key else 0,
        )
        self.google_scholar = SourceBudget(
            enabled=scholar_per_query > 0,
            requests_remaining=3 if scholar_per_query > 0 else 0,
        )
        self.has_semantic_scholar_api_key = has_semantic_scholar_api_key

    def should_use_arxiv(self, query: QueryRecord) -> bool:
        return self.arxiv.can_use() and query.origin not in {"author_expansion", "title_expansion"}

    def should_use_semantic_scholar(self, query: QueryRecord | None) -> bool:
        if not self.semantic_scholar.can_use():
            return False
        if self.has_semantic_scholar_api_key or query is None:
            return True
        return query.origin not in {"author_expansion", "title_expansion"}

    def should_use_google_scholar(self, query: QueryRecord) -> bool:
        return self.google_scholar.can_use() and query.origin not in {"author_expansion", "title_expansion"}

    def state(self) -> dict[str, object]:
        return {
            "arxiv_enabled": self.arxiv.enabled,
            "arxiv_requests_remaining": self.arxiv.requests_remaining,
            "semanticscholar_enabled": self.semantic_scholar.enabled,
            "semanticscholar_has_api_key": self.has_semantic_scholar_api_key,
            "semanticscholar_requests_remaining": self.semantic_scholar.requests_remaining,
            "googlescholar_enabled": self.google_scholar.enabled,
            "googlescholar_requests_remaining": self.google_scholar.requests_remaining,
        }

    def load_state(self, state: dict[str, object]) -> None:
        self.arxiv.enabled = bool(state["arxiv_enabled"])
        self.arxiv.requests_remaining = int(state["arxiv_requests_remaining"])
        self.has_semantic_scholar_api_key = bool(state["semanticscholar_has_api_key"])
        self.semantic_scholar.enabled = bool(state["semanticscholar_enabled"])
        self.semantic_scholar.requests_remaining = int(state["semanticscholar_requests_remaining"])
        self.google_scholar.enabled = bool(state["googlescholar_enabled"])
        self.google_scholar.requests_remaining = int(state["googlescholar_requests_remaining"])
