from __future__ import annotations

from research_lab.sources.arxiv import search_arxiv
from research_lab.sources.duckduckgo import DuckDuckGoHtmlParser, _decode_duckduckgo_url, search_duckduckgo
from research_lab.sources.extraction import (
    FullTextResult,
    HtmlTextParser,
    _clean_extracted_text,
    _extract_text_from_html,
    fetch_candidate_full_text,
)
from research_lab.sources.googlescholar import GoogleScholarHtmlParser, search_google_scholar
from research_lab.sources.openalex import search_openalex
from research_lab.sources.semanticscholar import fetch_semantic_scholar_references, search_semantic_scholar
from research_lab.sources.transport import HttpClient, HttpResponse, SourceError

__all__ = [
    "DuckDuckGoHtmlParser",
    "FullTextResult",
    "GoogleScholarHtmlParser",
    "HtmlTextParser",
    "HttpClient",
    "HttpResponse",
    "SourceError",
    "_clean_extracted_text",
    "_decode_duckduckgo_url",
    "_extract_text_from_html",
    "fetch_candidate_full_text",
    "fetch_semantic_scholar_references",
    "search_arxiv",
    "search_duckduckgo",
    "search_google_scholar",
    "search_openalex",
    "search_semantic_scholar",
]
