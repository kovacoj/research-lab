from __future__ import annotations

import os
from collections.abc import MutableMapping

from research_lab.models import Candidate, QueryRecord, ResearchBrief
from research_lab.retrieval_plan import RetrievalPlan
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
        self.plan = RetrievalPlan(
            has_semantic_scholar_api_key=bool(semantic_scholar_api_key),
            scholar_per_query=scholar_per_query,
        )
        self._state = _RetrievalStateView(self.plan)

    def search(self, query: QueryRecord, brief: ResearchBrief) -> list[Candidate]:
        collected: list[Candidate] = []
        if self.plan.should_use_arxiv(query):
            try:
                self.plan.arxiv.consume()
                collected.extend(self._annotate(query, search_arxiv(query.query, brief.per_query, brief.since_year, self.client)))
            except SourceError as exc:
                self._handle_arxiv_error(exc)
        try:
            collected.extend(self._annotate(query, search_openalex(query.query, brief.per_query, brief.since_year, self.client)))
        except SourceError as exc:
            self.warnings.append(str(exc))
        if self.plan.should_use_semantic_scholar(query):
            try:
                self.plan.semantic_scholar.consume()
                collected.extend(self._annotate(query, search_semantic_scholar(query.query, brief.per_query, brief.since_year, self.client)))
            except SourceError as exc:
                self._handle_semantic_scholar_error(exc)
        try:
            collected.extend(self._annotate(query, search_duckduckgo(query.query, brief.web_per_query, self.client)))
        except SourceError as exc:
            self.warnings.append(str(exc))
        if self.plan.should_use_google_scholar(query):
            try:
                self.plan.google_scholar.consume()
                collected.extend(self._annotate(query, search_google_scholar(query.query, brief.scholar_per_query, self.client)))
            except SourceError as exc:
                self._handle_google_scholar_error(exc)
        return collected

    def fetch_references(self, candidate: Candidate, per_query: int) -> list[Candidate]:
        if not self.plan.should_use_semantic_scholar(None):
            return []
        if not candidate.source_id or not candidate.source.startswith("semanticscholar"):
            return []
        try:
            self.plan.semantic_scholar.consume()
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
            if self.plan.arxiv.enabled:
                self.warnings.append("arxiv disabled after rate limit")
            self.plan.arxiv.disable()
            return
        self.warnings.append(message)

    def _handle_semantic_scholar_error(self, exc: SourceError) -> None:
        if "HTTP Error 429" in str(exc):
            if self.plan.semantic_scholar.enabled:
                self.warnings.append("semantic scholar disabled after rate limit")
            self.plan.semantic_scholar.disable()
            return
        self.warnings.append(str(exc))

    def _handle_google_scholar_error(self, exc: SourceError) -> None:
        if "google scholar blocked automated access" in str(exc):
            if self.plan.google_scholar.enabled:
                self.warnings.append("google scholar disabled after block")
            self.plan.google_scholar.disable()
            return
        self.warnings.append(str(exc))


class _RetrievalStateView(MutableMapping[str, object]):
    def __init__(self, plan: RetrievalPlan) -> None:
        self.plan = plan

    def __getitem__(self, key: str) -> object:
        return self.plan.state()[key]

    def __setitem__(self, key: str, value: object) -> None:
        state = self.plan.state()
        state[key] = value
        self.plan.load_state(state)

    def __delitem__(self, key: str) -> None:
        raise KeyError(key)

    def __iter__(self):
        return iter(self.plan.state())

    def __len__(self) -> int:
        return len(self.plan.state())
