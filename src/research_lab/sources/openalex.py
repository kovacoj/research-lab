from __future__ import annotations

import os
import urllib.parse

from research_lab.models import Candidate
from research_lab.source_candidates import paper_candidate
from research_lab.sources.transport import HttpClient


def _join_abstract(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    ordered: list[tuple[int, str]] = []
    for word, positions in index.items():
        for position in positions:
            ordered.append((position, word))
    ordered.sort(key=lambda item: item[0])
    return " ".join(word for _, word in ordered)


def _extract_doi(raw_id: str | None) -> str:
    if not raw_id:
        return ""
    if raw_id.startswith("https://doi.org/"):
        return raw_id.removeprefix("https://doi.org/")
    return raw_id


def search_openalex(query: str, per_page: int, since_year: int | None, client: HttpClient) -> list[Candidate]:
    params = {"search": query, "per-page": str(per_page), "sort": "relevance_score:desc"}
    filter_parts: list[str] = []
    if since_year is not None:
        filter_parts.append(f"from_publication_date:{since_year}-01-01")
    if filter_parts:
        params["filter"] = ",".join(filter_parts)
    email = os.getenv("OPENALEX_EMAIL")
    if email:
        params["mailto"] = email
    api_key = os.getenv("OPENALEX_API_KEY")
    if api_key:
        params["api_key"] = api_key

    payload = client.get_json(f"https://api.openalex.org/works?{urllib.parse.urlencode(params)}")
    results: list[Candidate] = []
    for item in payload.get("results", []):
        primary_location = item.get("primary_location") or {}
        oa_location = item.get("best_oa_location") or {}
        authorships = item.get("authorships") or []
        abstract = _join_abstract(item.get("abstract_inverted_index"))
        results.append(
            paper_candidate(
                title=item.get("title") or "",
                abstract=abstract,
                url=(primary_location.get("landing_page_url") or item.get("id") or ""),
                source="openalex",
                source_id=item.get("id") or "",
                authors=[entry.get("author", {}).get("display_name", "") for entry in authorships if entry.get("author")],
                year=item.get("publication_year"),
                venue=(primary_location.get("source") or {}).get("display_name", ""),
                doi=_extract_doi(item.get("doi")),
                citation_count=item.get("cited_by_count") or 0,
                open_access_url=oa_location.get("pdf_url") or "",
                snippet=abstract,
                fields_of_study=[topic.get("display_name", "") for topic in item.get("topics") or []],
            )
        )
    return results
