from __future__ import annotations

import os

from research_lab.models import Candidate, QueryRecord, ResearchBrief
from research_lab.sources import (
    HttpClient,
    SourceError,
    fetch_semantic_scholar_references,
    search_arxiv,
    search_duckduckgo,
    search_google_scholar,
    search_openalex,
    search_semantic_scholar,
)


class RetrievalPolicy:
    def __init__(self, client: HttpClient | None = None, scholar_per_query: int = 0) -> None:
        semantic_scholar_api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
        self.client = client or HttpClient()
        self.warnings: list[str] = []
        self._state: dict[str, object] = {
            "arxiv_enabled": True,
            "arxiv_requests_remaining": 6,
            "semanticscholar_enabled": bool(semantic_scholar_api_key),
            "semanticscholar_has_api_key": bool(semantic_scholar_api_key),
            "semanticscholar_requests_remaining": 999 if semantic_scholar_api_key else 0,
            "googlescholar_enabled": scholar_per_query > 0,
            "googlescholar_requests_remaining": 3 if scholar_per_query > 0 else 0,
        }

    def search(self, query: QueryRecord, brief: ResearchBrief) -> list[Candidate]:
        collected: list[Candidate] = []
        if self._should_use_arxiv(query):
            try:
                self._state["arxiv_requests_remaining"] = int(self._state["arxiv_requests_remaining"]) - 1
                collected.extend(self._annotate(query, search_arxiv(query.query, brief.per_query, brief.since_year, self.client)))
            except SourceError as exc:
                self._handle_arxiv_error(exc)
        try:
            collected.extend(self._annotate(query, search_openalex(query.query, brief.per_query, brief.since_year, self.client)))
        except SourceError as exc:
            self.warnings.append(str(exc))
        if self._should_use_semantic_scholar(query):
            try:
                self._state["semanticscholar_requests_remaining"] = int(self._state["semanticscholar_requests_remaining"]) - 1
                collected.extend(self._annotate(query, search_semantic_scholar(query.query, brief.per_query, brief.since_year, self.client)))
            except SourceError as exc:
                self._handle_semantic_scholar_error(exc)
        try:
            collected.extend(self._annotate(query, search_duckduckgo(query.query, brief.web_per_query, self.client)))
        except SourceError as exc:
            self.warnings.append(str(exc))
        if self._should_use_google_scholar(query):
            try:
                self._state["googlescholar_requests_remaining"] = int(self._state["googlescholar_requests_remaining"]) - 1
                collected.extend(self._annotate(query, search_google_scholar(query.query, brief.scholar_per_query, self.client)))
            except SourceError as exc:
                self._handle_google_scholar_error(exc)
        return collected

    def fetch_references(self, candidate: Candidate, per_query: int) -> list[Candidate]:
        if not self._should_use_semantic_scholar(None):
            return []
        if not candidate.source_id or not candidate.source.startswith("semanticscholar"):
            return []
        try:
            self._state["semanticscholar_requests_remaining"] = int(self._state["semanticscholar_requests_remaining"]) - 1
            references = fetch_semantic_scholar_references(candidate.source_id, per_query, self.client)
        except SourceError as exc:
            self._handle_semantic_scholar_error(exc)
            return []
        for reference in references:
            reference.matched_queries.append(f"references:{candidate.title}")
        return references

    def _annotate(self, query: QueryRecord, candidates: list[Candidate]) -> list[Candidate]:
        for candidate in candidates:
            candidate.matched_queries.append(query.query)
        return candidates

    def _handle_arxiv_error(self, exc: SourceError) -> None:
        message = str(exc)
        if "HTTP Error 429" in message or "timed out" in message:
            if self._state["arxiv_enabled"]:
                self.warnings.append("arxiv disabled after rate limit")
            self._state["arxiv_enabled"] = False
            return
        self.warnings.append(message)

    def _handle_semantic_scholar_error(self, exc: SourceError) -> None:
        if "HTTP Error 429" in str(exc):
            if self._state["semanticscholar_enabled"]:
                self.warnings.append("semantic scholar disabled after rate limit")
            self._state["semanticscholar_enabled"] = False
            return
        self.warnings.append(str(exc))

    def _handle_google_scholar_error(self, exc: SourceError) -> None:
        if "google scholar blocked automated access" in str(exc):
            if self._state["googlescholar_enabled"]:
                self.warnings.append("google scholar disabled after block")
            self._state["googlescholar_enabled"] = False
            return
        self.warnings.append(str(exc))

    def _should_use_arxiv(self, query: QueryRecord) -> bool:
        if not self._state["arxiv_enabled"]:
            return False
        if int(self._state["arxiv_requests_remaining"]) <= 0:
            return False
        return query.origin not in {"author_expansion", "title_expansion"}

    def _should_use_semantic_scholar(self, query: QueryRecord | None) -> bool:
        if not self._state["semanticscholar_enabled"]:
            return False
        if int(self._state["semanticscholar_requests_remaining"]) <= 0:
            return False
        if bool(self._state["semanticscholar_has_api_key"]):
            return True
        if query is None:
            return True
        return query.origin not in {"author_expansion", "title_expansion"}

    def _should_use_google_scholar(self, query: QueryRecord) -> bool:
        if not self._state["googlescholar_enabled"]:
            return False
        if int(self._state["googlescholar_requests_remaining"]) <= 0:
            return False
        return query.origin not in {"author_expansion", "title_expansion"}
