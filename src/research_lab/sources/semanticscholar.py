from __future__ import annotations

import os
import urllib.parse

from research_lab.models import Candidate
from research_lab.source_candidates import paper_candidate
from research_lab.sources.transport import HttpClient


def search_semantic_scholar(query: str, limit: int, since_year: int | None, client: HttpClient) -> list[Candidate]:
    fields = ",".join(["paperId", "title", "abstract", "url", "year", "authors", "venue", "citationCount", "externalIds", "openAccessPdf", "fieldsOfStudy"])
    params = {"query": query, "limit": str(limit), "fields": fields}
    if since_year is not None:
        params["year"] = f"{since_year}-"
    headers: dict[str, str] = {}
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    payload = client.get_json(f"https://api.semanticscholar.org/graph/v1/paper/search?{urllib.parse.urlencode(params)}", headers=headers)
    results: list[Candidate] = []
    for item in payload.get("data", []):
        external_ids = item.get("externalIds") or {}
        open_access_pdf = item.get("openAccessPdf") or {}
        abstract = item.get("abstract") or ""
        results.append(
            paper_candidate(
                title=item.get("title") or "",
                abstract=abstract,
                url=item.get("url") or "",
                source="semanticscholar",
                source_id=item.get("paperId") or "",
                authors=[author.get("name", "") for author in item.get("authors") or []],
                year=item.get("year"),
                venue=item.get("venue") or "",
                doi=external_ids.get("DOI") or "",
                citation_count=item.get("citationCount") or 0,
                open_access_url=open_access_pdf.get("url") or "",
                snippet=abstract,
                fields_of_study=item.get("fieldsOfStudy") or [],
            )
        )
    return results


def fetch_semantic_scholar_references(paper_id: str, limit: int, client: HttpClient) -> list[Candidate]:
    if not paper_id:
        return []
    fields = ",".join(["references.paperId", "references.title", "references.abstract", "references.url", "references.year", "references.authors", "references.venue", "references.citationCount", "references.externalIds", "references.openAccessPdf", "references.fieldsOfStudy"])
    headers: dict[str, str] = {}
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    encoded_id = urllib.parse.quote(paper_id, safe="")
    payload = client.get_json(
        f"https://api.semanticscholar.org/graph/v1/paper/{encoded_id}?fields={urllib.parse.quote(fields, safe=',')}",
        headers=headers,
    )
    results: list[Candidate] = []
    for item in (payload.get("references") or [])[:limit]:
        cited = item.get("citedPaper") or item
        external_ids = cited.get("externalIds") or {}
        open_access_pdf = cited.get("openAccessPdf") or {}
        abstract = cited.get("abstract") or ""
        results.append(
            paper_candidate(
                title=cited.get("title") or "",
                abstract=abstract,
                url=cited.get("url") or "",
                source="semanticscholar_reference",
                source_id=cited.get("paperId") or "",
                authors=[author.get("name", "") for author in cited.get("authors") or []],
                year=cited.get("year"),
                venue=cited.get("venue") or "",
                doi=external_ids.get("DOI") or "",
                citation_count=cited.get("citationCount") or 0,
                open_access_url=open_access_pdf.get("url") or "",
                snippet=abstract,
                fields_of_study=cited.get("fieldsOfStudy") or [],
            )
        )
    return results
