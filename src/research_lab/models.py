from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class ResearchBrief:
    topic: str
    context: str
    domains: list[str] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)
    must_exclude: list[str] = field(default_factory=list)
    since_year: int | None = None
    iterations: int = 2
    per_query: int = 8
    web_per_query: int = 3
    scholar_per_query: int = 0
    full_text_top_n: int = 5
    llm_rerank_top_n: int = 8
    llm_summary_top_n: int = 5
    top_k: int = 20

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "ResearchBrief":
        return cls(
            topic=str(payload.get("topic", "")).strip(),
            context=str(payload.get("context", "")).strip(),
            domains=[str(item).strip() for item in payload.get("domains", []) if str(item).strip()],
            must_include=[str(item).strip() for item in payload.get("must_include", []) if str(item).strip()],
            must_exclude=[str(item).strip() for item in payload.get("must_exclude", []) if str(item).strip()],
            since_year=_parse_optional_int(payload.get("since_year")),
            iterations=max(_parse_optional_int(payload.get("iterations")) or 2, 0),
            per_query=max(_parse_optional_int(payload.get("per_query")) or 8, 1),
            web_per_query=max(_parse_optional_int(payload.get("web_per_query")) or 3, 0),
            scholar_per_query=max(_parse_optional_int(payload.get("scholar_per_query")) or 0, 0),
            full_text_top_n=max(_parse_optional_int(payload.get("full_text_top_n")) or 5, 0),
            llm_rerank_top_n=max(_parse_optional_int(payload.get("llm_rerank_top_n")) or 8, 0),
            llm_summary_top_n=max(_parse_optional_int(payload.get("llm_summary_top_n")) or 5, 0),
            top_k=max(_parse_optional_int(payload.get("top_k")) or 20, 1),
        )


@dataclass(slots=True)
class QueryRecord:
    query: str
    origin: str
    iteration: int

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "QueryRecord":
        return cls(
            query=str(payload.get("query", "")).strip(),
            origin=str(payload.get("origin", "")).strip(),
            iteration=_parse_optional_int(payload.get("iteration")) or 0,
        )


@dataclass(slots=True)
class PaperCandidate:
    title: str
    abstract: str
    url: str
    source: str
    source_id: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""
    citation_count: int = 0
    open_access_url: str = ""
    document_kind: str = "paper"
    snippet: str = ""
    full_text: str = ""
    full_text_source: str = ""
    access_status: str = ""
    access_url: str = ""
    fields_of_study: list[str] = field(default_factory=list)
    matched_queries: list[str] = field(default_factory=list)
    source_names: list[str] = field(default_factory=list)
    score: float = 0.0
    llm_score: float | None = None
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    llm_reasons: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "PaperCandidate":
        return cls(
            title=str(payload.get("title", "")).strip(),
            abstract=str(payload.get("abstract", "")).strip(),
            url=str(payload.get("url", "")).strip(),
            source=str(payload.get("source", "")).strip(),
            source_id=str(payload.get("source_id", "")).strip(),
            authors=[str(item).strip() for item in payload.get("authors", []) if str(item).strip()],
            year=_parse_optional_int(payload.get("year")),
            venue=str(payload.get("venue", "")).strip(),
            doi=str(payload.get("doi", "")).strip(),
            citation_count=max(_parse_optional_int(payload.get("citation_count")) or 0, 0),
            open_access_url=str(payload.get("open_access_url", "")).strip(),
            document_kind=str(payload.get("document_kind", "paper")).strip() or "paper",
            snippet=str(payload.get("snippet", "")).strip(),
            full_text=str(payload.get("full_text", "")).strip(),
            full_text_source=str(payload.get("full_text_source", "")).strip(),
            access_status=str(payload.get("access_status", "")).strip(),
            access_url=str(payload.get("access_url", "")).strip(),
            fields_of_study=[str(item).strip() for item in payload.get("fields_of_study", []) if str(item).strip()],
            matched_queries=[str(item).strip() for item in payload.get("matched_queries", []) if str(item).strip()],
            source_names=[str(item).strip() for item in payload.get("source_names", []) if str(item).strip()],
            score=float(payload.get("score", 0.0) or 0.0),
            llm_score=float(payload["llm_score"]) if payload.get("llm_score") is not None else None,
            reasons=[str(item).strip() for item in payload.get("reasons", []) if str(item).strip()],
            flags=[str(item).strip() for item in payload.get("flags", []) if str(item).strip()],
            llm_reasons=[str(item).strip() for item in payload.get("llm_reasons", []) if str(item).strip()],
            evidence=[str(item).strip() for item in payload.get("evidence", []) if str(item).strip()],
        )


@dataclass(slots=True)
class RetrievalCandidate:
    title: str
    abstract: str
    url: str
    source: str
    source_id: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""
    citation_count: int = 0
    open_access_url: str = ""
    document_kind: str = "paper"
    snippet: str = ""
    fields_of_study: list[str] = field(default_factory=list)
    matched_queries: list[str] = field(default_factory=list)
    source_names: list[str] = field(default_factory=list)

    def to_paper_candidate(self) -> PaperCandidate:
        return PaperCandidate(
            title=self.title,
            abstract=self.abstract,
            url=self.url,
            source=self.source,
            source_id=self.source_id,
            authors=list(self.authors),
            year=self.year,
            venue=self.venue,
            doi=self.doi,
            citation_count=self.citation_count,
            open_access_url=self.open_access_url,
            document_kind=self.document_kind,
            snippet=self.snippet,
            fields_of_study=list(self.fields_of_study),
            matched_queries=list(self.matched_queries),
            source_names=list(self.source_names),
        )

    @classmethod
    def from_paper_candidate(cls, candidate: PaperCandidate) -> "RetrievalCandidate":
        return cls(
            title=candidate.title,
            abstract=candidate.abstract,
            url=candidate.url,
            source=candidate.source,
            source_id=candidate.source_id,
            authors=list(candidate.authors),
            year=candidate.year,
            venue=candidate.venue,
            doi=candidate.doi,
            citation_count=candidate.citation_count,
            open_access_url=candidate.open_access_url,
            document_kind=candidate.document_kind,
            snippet=candidate.snippet,
            fields_of_study=list(candidate.fields_of_study),
            matched_queries=list(candidate.matched_queries),
            source_names=list(candidate.source_names),
        )


@dataclass(slots=True)
class ScoredCandidate(RetrievalCandidate):
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def to_paper_candidate(self) -> PaperCandidate:
        candidate = super(ScoredCandidate, self).to_paper_candidate()
        candidate.score = self.score
        candidate.reasons = list(self.reasons)
        candidate.flags = list(self.flags)
        return candidate

    @classmethod
    def from_paper_candidate(cls, candidate: PaperCandidate) -> "ScoredCandidate":
        retrieval = RetrievalCandidate.from_paper_candidate(candidate)
        return cls(
            title=retrieval.title,
            abstract=retrieval.abstract,
            url=retrieval.url,
            source=retrieval.source,
            source_id=retrieval.source_id,
            authors=list(retrieval.authors),
            year=retrieval.year,
            venue=retrieval.venue,
            doi=retrieval.doi,
            citation_count=retrieval.citation_count,
            open_access_url=retrieval.open_access_url,
            document_kind=retrieval.document_kind,
            snippet=retrieval.snippet,
            fields_of_study=list(retrieval.fields_of_study),
            matched_queries=list(retrieval.matched_queries),
            source_names=list(retrieval.source_names),
            score=candidate.score,
            reasons=list(candidate.reasons),
            flags=list(candidate.flags),
        )


@dataclass(slots=True)
class EnrichedCandidate(ScoredCandidate):
    full_text: str = ""
    full_text_source: str = ""
    access_status: str = ""
    access_url: str = ""
    evidence: list[str] = field(default_factory=list)
    llm_score: float | None = None
    llm_reasons: list[str] = field(default_factory=list)

    def to_paper_candidate(self) -> PaperCandidate:
        candidate = super(EnrichedCandidate, self).to_paper_candidate()
        candidate.full_text = self.full_text
        candidate.full_text_source = self.full_text_source
        candidate.access_status = self.access_status
        candidate.access_url = self.access_url
        candidate.evidence = list(self.evidence)
        candidate.llm_score = self.llm_score
        candidate.llm_reasons = list(self.llm_reasons)
        return candidate

    @classmethod
    def from_paper_candidate(cls, candidate: PaperCandidate) -> "EnrichedCandidate":
        scored = ScoredCandidate.from_paper_candidate(candidate)
        return cls(
            title=scored.title,
            abstract=scored.abstract,
            url=scored.url,
            source=scored.source,
            source_id=scored.source_id,
            authors=list(scored.authors),
            year=scored.year,
            venue=scored.venue,
            doi=scored.doi,
            citation_count=scored.citation_count,
            open_access_url=scored.open_access_url,
            document_kind=scored.document_kind,
            snippet=scored.snippet,
            fields_of_study=list(scored.fields_of_study),
            matched_queries=list(scored.matched_queries),
            source_names=list(scored.source_names),
            score=scored.score,
            reasons=list(scored.reasons),
            flags=list(scored.flags),
            full_text=candidate.full_text,
            full_text_source=candidate.full_text_source,
            access_status=candidate.access_status,
            access_url=candidate.access_url,
            evidence=list(candidate.evidence),
            llm_score=candidate.llm_score,
            llm_reasons=list(candidate.llm_reasons),
        )


@dataclass(slots=True)
class RunArtifacts:
    run_id: str
    created_at: str
    run_dir: str
    brief: ResearchBrief
    queries: list[QueryRecord]
    candidates: list[PaperCandidate]
    program_text: str
    warnings: list[str] = field(default_factory=list)
    synthesis: str = ""

    @classmethod
    def create(
        cls,
        run_id: str,
        run_dir: str,
        brief: ResearchBrief,
        queries: list[QueryRecord],
        candidates: list[PaperCandidate],
        program_text: str,
        warnings: list[str] | None = None,
        synthesis: str = "",
    ) -> "RunArtifacts":
        return cls(
            run_id=run_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            run_dir=run_dir,
            brief=brief,
            queries=queries,
            candidates=candidates,
            program_text=program_text,
            warnings=warnings or [],
            synthesis=synthesis,
        )


def _parse_optional_int(value: object) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
