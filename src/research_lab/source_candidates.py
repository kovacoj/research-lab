from __future__ import annotations

from research_lab.models import Candidate


def paper_candidate(
    *,
    title: str,
    abstract: str,
    url: str,
    source: str,
    source_id: str,
    authors: list[str] | None = None,
    year: int | None = None,
    venue: str = "",
    doi: str = "",
    citation_count: int = 0,
    open_access_url: str = "",
    snippet: str = "",
    fields_of_study: list[str] | None = None,
) -> Candidate:
    return Candidate(
        title=title,
        abstract=abstract,
        url=url,
        source=source,
        source_id=source_id,
        authors=authors or [],
        year=year,
        venue=venue,
        doi=doi,
        citation_count=citation_count,
        open_access_url=open_access_url,
        snippet=snippet or abstract,
        fields_of_study=fields_of_study or [],
        source_names=[source],
    )


def web_candidate(*, title: str, abstract: str, url: str, source: str, source_id: str, venue: str = "") -> Candidate:
    return Candidate(
        title=title,
        abstract=abstract,
        url=url,
        source=source,
        source_id=source_id,
        venue=venue,
        document_kind="web",
        snippet=abstract,
        source_names=[source],
    )
