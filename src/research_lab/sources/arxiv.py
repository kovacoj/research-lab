from __future__ import annotations

import urllib.parse
import xml.etree.ElementTree as ET

from research_lab.models import Candidate
from research_lab.sources.extraction import _clean_text, _extract_year
from research_lab.sources.transport import HttpClient, SourceError


def search_arxiv(query: str, limit: int, since_year: int | None, client: HttpClient) -> list[Candidate]:
    params = {
        "search_query": f"all:{query}",
        "start": "0",
        "max_results": str(limit),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    response = client.fetch(f"https://export.arxiv.org/api/query?{urllib.parse.urlencode(params)}")
    try:
        root = ET.fromstring(response.body)
    except ET.ParseError as exc:  # pragma: no cover - malformed upstream payloads are environment specific
        raise SourceError(f"invalid arxiv response for {query}: {exc}") from exc

    namespace = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    results: list[Candidate] = []
    for entry in root.findall("atom:entry", namespace):
        title = _clean_text(entry.findtext("atom:title", default="", namespaces=namespace))
        abstract = _clean_text(entry.findtext("atom:summary", default="", namespaces=namespace))
        year = _extract_year(entry.findtext("atom:published", default="", namespaces=namespace))
        if since_year is not None and year is not None and year < since_year:
            continue
        paper_url = entry.findtext("atom:id", default="", namespaces=namespace)
        pdf_url = ""
        for link in entry.findall("atom:link", namespace):
            if (link.attrib.get("title") or "").lower() == "pdf":
                pdf_url = link.attrib.get("href", "")
                break
        results.append(
            Candidate(
                title=title,
                abstract=abstract,
                url=paper_url,
                source="arxiv",
                source_id=paper_url,
                authors=[_clean_text(author.findtext("atom:name", default="", namespaces=namespace)) for author in entry.findall("atom:author", namespace)],
                year=year,
                venue="arXiv",
                doi=_clean_text(entry.findtext("arxiv:doi", default="", namespaces=namespace)),
                open_access_url=pdf_url,
                snippet=abstract,
                source_names=["arxiv"],
            )
        )
        if len(results) >= limit:
            break
    return results
