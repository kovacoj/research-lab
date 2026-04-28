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
    full_text_top_n: int = 5
    top_k: int = 20

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class QueryRecord:
    query: str
    origin: str
    iteration: int

    def to_dict(self) -> dict:
        return asdict(self)


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
    fields_of_study: list[str] = field(default_factory=list)
    matched_queries: list[str] = field(default_factory=list)
    source_names: list[str] = field(default_factory=list)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


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
        )
