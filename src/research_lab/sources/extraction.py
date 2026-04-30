from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from dataclasses import dataclass

from research_lab.models import RetrievalCandidate
from research_lab.sources.transport import HttpClient, HttpResponse, SourceError


@dataclass(slots=True)
class FullTextResult:
    text: str
    source: str
    access_status: str
    access_url: str


class HtmlTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._ignore_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignore_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignore_depth > 0:
            self._ignore_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            return
        cleaned = _clean_text(data)
        if cleaned:
            self._chunks.append(cleaned)

    def text(self) -> str:
        return _clean_text(" ".join(self._chunks))


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clean_extracted_text(text: str) -> str:
    cleaned = text.replace("\x0c", " ")
    cleaned = re.sub(r"(?:^|\s)[\d():,;]{8,}(?=\s|$)", " ", cleaned)
    cleaned = re.sub(r"\b(?:received|accepted|published online|check for updates)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    cleaned = re.sub(r"\b[\w.+-]+@[\w.-]+\.\w+\b", " ", cleaned)
    cleaned = _clean_text(cleaned)
    abstract_match = re.search(r"\babstract\b", cleaned, flags=re.IGNORECASE)
    introduction_match = re.search(r"\bintroduction\b", cleaned, flags=re.IGNORECASE)
    match = abstract_match or introduction_match
    if match is not None and 0 < match.start() < 2500:
        cleaned = cleaned[match.start() :]
    return _clean_text(cleaned)


def _extract_year(text: str) -> int | None:
    match = re.search(r"\b(19|20)\d{2}\b", text)
    if not match:
        return None
    return int(match.group(0))


def _looks_like_paywall(text: str) -> bool:
    paywall_markers = [
        "purchase this article",
        "buy this article",
        "rent this article",
        "access through your institution",
        "institutional access",
        "sign in via your institution",
        "institutional login",
        "subscribe to journal",
        "get access",
        "view access options",
        "check access",
    ]
    return sum(1 for marker in paywall_markers if marker in text) >= 1


def _looks_like_full_text(text: str) -> bool:
    if len(text) >= 12000:
        return True
    section_hits = sum(
        1
        for marker in ["introduction", "method", "methods", "results", "discussion", "conclusion", "references"]
        if re.search(rf"\b{marker}\b", text)
    )
    return section_hits >= 3 or (section_hits >= 2 and len(text) >= 5000)


def _classify_fetch_error(url: str, exc: SourceError) -> FullTextResult:
    message = str(exc)
    if any(code in message for code in ["HTTP Error 401", "HTTP Error 403", "HTTP Error 451"]):
        return FullTextResult(text="", source="", access_status="paywalled", access_url=url)
    return FullTextResult(text="", source="", access_status="unreadable", access_url=url)


def _classify_html_access(candidate: RetrievalCandidate, response: HttpResponse) -> FullTextResult:
    text = _extract_text_from_html(response.body.decode("utf-8", errors="ignore"))
    lowered = text.lower()
    if not text:
        return FullTextResult(text="", source="", access_status="unreadable", access_url=response.final_url)
    if candidate.document_kind == "web":
        return FullTextResult(text=text, source="html", access_status="open", access_url=response.final_url)
    if _looks_like_paywall(lowered):
        return FullTextResult(text="", source="", access_status="paywalled", access_url=response.final_url)
    if _looks_like_full_text(lowered):
        return FullTextResult(text=text, source="html", access_status="open", access_url=response.final_url)
    if "abstract" in lowered or len(text) < 3500:
        return FullTextResult(text="", source="", access_status="abstract_only", access_url=response.final_url)
    return FullTextResult(text="", source="", access_status="unreadable", access_url=response.final_url)


def fetch_candidate_full_text(candidate: RetrievalCandidate, client: HttpClient) -> FullTextResult:
    last_result = FullTextResult(text="", source="", access_status="", access_url="")
    last_error: SourceError | None = None
    for url in [candidate.open_access_url, candidate.url]:
        if not url:
            continue
        try:
            response = client.fetch(url, headers={"Accept": "text/html,application/pdf;q=0.9,*/*;q=0.8"})
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


def _extract_text_from_html(html: str) -> str:
    parser = HtmlTextParser()
    parser.feed(html)
    parser.close()
    return _clean_extracted_text(parser.text())[:20000]


def _extract_text_from_pdf_bytes(payload: bytes) -> str:
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "document.pdf"
            txt_path = Path(tmpdir) / "document.txt"
            pdf_path.write_bytes(payload)
            try:
                subprocess.run([pdftotext, "-layout", "-nopgbrk", str(pdf_path), str(txt_path)], check=True, capture_output=True, timeout=30)
                return _clean_extracted_text(txt_path.read_text(encoding="utf-8", errors="ignore"))[:20000]
            except Exception:
                pass

    decoded = payload.decode("latin-1", errors="ignore")
    fragments = re.findall(r"\(([A-Za-z0-9 ,.;:()\-_/]{20,})\)", decoded)
    return _clean_extracted_text(" ".join(fragments))[:20000]
