from __future__ import annotations

from research_lab.models import Candidate
from research_lab.sources.extraction import FullTextResult, _classify_fetch_error, _classify_html_access, _extract_text_from_pdf_bytes
from research_lab.sources.transport import HttpClient, SourceError


class DocumentAccessResolver:
    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def fetch(self, candidate: Candidate) -> FullTextResult:
        last_result = FullTextResult(text="", source="", access_status="", access_url="")
        last_error: SourceError | None = None
        for url in self._candidate_urls(candidate):
            try:
                response = self.client.fetch(url, headers={"Accept": "text/html,application/pdf;q=0.9,*/*;q=0.8"})
            except SourceError as exc:
                last_result = _classify_fetch_error(url, exc)
                last_error = exc
                continue
            content_type = response.content_type.lower()
            if "pdf" in content_type or response.final_url.lower().endswith(".pdf") or url.lower().endswith(".pdf"):
                text = _extract_text_from_pdf_bytes(response.body)
                if text:
                    return FullTextResult(text=text, source="pdf", access_status="open", access_url=response.final_url)
                last_result = FullTextResult(text="", source="", access_status="unreadable", access_url=response.final_url)
                continue
            result = _classify_html_access(candidate, response)
            if result.text:
                return result
            last_result = result
        if last_result.access_status:
            return last_result
        if last_error is not None:
            raise last_error
        raise SourceError(f"no reachable content found for {candidate.title}")

    def _candidate_urls(self, candidate: Candidate) -> list[str]:
        return [url for url in [candidate.open_access_url, candidate.url] if url]
