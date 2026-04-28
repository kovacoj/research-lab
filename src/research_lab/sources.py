from __future__ import annotations

from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.error
import urllib.request
from dataclasses import dataclass

from research_lab.models import PaperCandidate


class SourceError(RuntimeError):
    pass


@dataclass(slots=True)
class HttpResponse:
    body: bytes
    content_type: str
    final_url: str


@dataclass(slots=True)
class HttpClient:
    timeout_seconds: int = 30
    retries: int = 2
    max_bytes: int = 6_000_000
    user_agent: str = "research-lab/0.1 (+https://example.invalid)"

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> dict:
        response = self.fetch(url, headers=headers)
        try:
            return json.loads(response.body.decode("utf-8"))
        except Exception as exc:  # pragma: no cover - malformed upstream payloads are environment specific
            raise SourceError(f"invalid json from {url}: {exc}") from exc

    def fetch(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
        request_headers = {"User-Agent": self.user_agent, **(headers or {})}
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(url, headers=request_headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    body = response.read(self.max_bytes)
                    return HttpResponse(
                        body=body,
                        content_type=response.headers.get("Content-Type", ""),
                        final_url=response.geturl(),
                    )
            except urllib.error.HTTPError as exc:  # pragma: no cover - environment specific
                last_error = exc
                if exc.code in {429, 500, 502, 503, 504} and attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                break
            except Exception as exc:  # pragma: no cover - environment specific
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                break
        raise SourceError(f"request failed for {url}: {last_error}")


class DuckDuckGoHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._in_title = False
        self._in_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        classes = attr_map.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._flush_current()
            self._current = {"title": "", "url": _decode_duckduckgo_url(attr_map.get("href", "")), "snippet": ""}
            self._in_title = True
        elif tag in {"a", "div"} and "result__snippet" in classes and self._current is not None:
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
        elif tag in {"a", "div"} and self._in_snippet:
            self._in_snippet = False

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        if self._in_title:
            self._current["title"] += data
        elif self._in_snippet:
            self._current["snippet"] += data

    def close(self) -> None:
        super().close()
        self._flush_current()

    def _flush_current(self) -> None:
        if self._current is None:
            return
        title = _clean_text(self._current.get("title", ""))
        url = self._current.get("url", "")
        if title and url:
            self.results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": _clean_text(self._current.get("snippet", "")),
                }
            )
        self._current = None


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


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _decode_duckduckgo_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.path.endswith("/l/") or parsed.path == "/l/":
        query = urllib.parse.parse_qs(parsed.query)
        if "uddg" in query and query["uddg"]:
            return urllib.parse.unquote(query["uddg"][0])
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://duckduckgo.com{url}"
    return url


def _url_host(url: str) -> str:
    return urllib.parse.urlparse(url).netloc


def search_openalex(
    query: str,
    per_page: int,
    since_year: int | None,
    client: HttpClient,
) -> list[PaperCandidate]:
    params = {
        "search": query,
        "per-page": str(per_page),
        "sort": "relevance_score:desc",
    }
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

    url = f"https://api.openalex.org/works?{urllib.parse.urlencode(params)}"
    payload = client.get_json(url)

    results: list[PaperCandidate] = []
    for item in payload.get("results", []):
        primary_location = item.get("primary_location") or {}
        oa_location = item.get("best_oa_location") or {}
        authorships = item.get("authorships") or []
        results.append(
            PaperCandidate(
                title=item.get("title") or "",
                abstract=_join_abstract(item.get("abstract_inverted_index")),
                url=(primary_location.get("landing_page_url") or item.get("id") or ""),
                source="openalex",
                source_id=item.get("id") or "",
                authors=[entry.get("author", {}).get("display_name", "") for entry in authorships if entry.get("author")],
                year=item.get("publication_year"),
                venue=(primary_location.get("source") or {}).get("display_name", ""),
                doi=_extract_doi(item.get("doi")),
                citation_count=item.get("cited_by_count") or 0,
                open_access_url=oa_location.get("pdf_url") or "",
                snippet=_join_abstract(item.get("abstract_inverted_index")),
                fields_of_study=[topic.get("display_name", "") for topic in item.get("topics") or []],
                source_names=["openalex"],
            )
        )
    return results


def search_semantic_scholar(
    query: str,
    limit: int,
    since_year: int | None,
    client: HttpClient,
) -> list[PaperCandidate]:
    fields = ",".join(
        [
            "paperId",
            "title",
            "abstract",
            "url",
            "year",
            "authors",
            "venue",
            "citationCount",
            "externalIds",
            "openAccessPdf",
            "fieldsOfStudy",
        ]
    )
    params = {
        "query": query,
        "limit": str(limit),
        "fields": fields,
    }
    if since_year is not None:
        params["year"] = f"{since_year}-"

    url = f"https://api.semanticscholar.org/graph/v1/paper/search?{urllib.parse.urlencode(params)}"
    headers: dict[str, str] = {}
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    payload = client.get_json(url, headers=headers)

    results: list[PaperCandidate] = []
    for item in payload.get("data", []):
        external_ids = item.get("externalIds") or {}
        open_access_pdf = item.get("openAccessPdf") or {}
        results.append(
            PaperCandidate(
                title=item.get("title") or "",
                abstract=item.get("abstract") or "",
                url=item.get("url") or "",
                source="semanticscholar",
                source_id=item.get("paperId") or "",
                authors=[author.get("name", "") for author in item.get("authors") or []],
                year=item.get("year"),
                venue=item.get("venue") or "",
                doi=external_ids.get("DOI") or "",
                citation_count=item.get("citationCount") or 0,
                open_access_url=open_access_pdf.get("url") or "",
                snippet=item.get("abstract") or "",
                fields_of_study=item.get("fieldsOfStudy") or [],
                source_names=["semanticscholar"],
            )
        )
    return results


def search_duckduckgo(
    query: str,
    limit: int,
    client: HttpClient,
) -> list[PaperCandidate]:
    if limit <= 0:
        return []
    url = f"https://html.duckduckgo.com/html/?{urllib.parse.urlencode({'q': query})}"
    response = client.fetch(url)
    html = response.body.decode("utf-8", errors="ignore")
    parser = DuckDuckGoHtmlParser()
    parser.feed(html)
    parser.close()

    results: list[PaperCandidate] = []
    for item in parser.results[:limit]:
        results.append(
            PaperCandidate(
                title=item["title"],
                abstract=item["snippet"],
                url=item["url"],
                source="duckduckgo",
                source_id=item["url"],
                venue=_url_host(item["url"]),
                document_kind="web",
                snippet=item["snippet"],
                source_names=["duckduckgo"],
            )
        )
    return results


def fetch_semantic_scholar_references(
    paper_id: str,
    limit: int,
    client: HttpClient,
) -> list[PaperCandidate]:
    if not paper_id:
        return []

    fields = ",".join(
        [
            "references.paperId",
            "references.title",
            "references.abstract",
            "references.url",
            "references.year",
            "references.authors",
            "references.venue",
            "references.citationCount",
            "references.externalIds",
            "references.openAccessPdf",
            "references.fieldsOfStudy",
        ]
    )
    encoded_id = urllib.parse.quote(paper_id, safe="")
    url = f"https://api.semanticscholar.org/graph/v1/paper/{encoded_id}?fields={urllib.parse.quote(fields, safe=',')}"
    headers: dict[str, str] = {}
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    payload = client.get_json(url, headers=headers)

    results: list[PaperCandidate] = []
    for item in (payload.get("references") or [])[:limit]:
        cited = item.get("citedPaper") or item
        external_ids = cited.get("externalIds") or {}
        open_access_pdf = cited.get("openAccessPdf") or {}
        results.append(
            PaperCandidate(
                title=cited.get("title") or "",
                abstract=cited.get("abstract") or "",
                url=cited.get("url") or "",
                source="semanticscholar_reference",
                source_id=cited.get("paperId") or "",
                authors=[author.get("name", "") for author in cited.get("authors") or []],
                year=cited.get("year"),
                venue=cited.get("venue") or "",
                doi=external_ids.get("DOI") or "",
                citation_count=cited.get("citationCount") or 0,
                open_access_url=open_access_pdf.get("url") or "",
                snippet=cited.get("abstract") or "",
                fields_of_study=cited.get("fieldsOfStudy") or [],
                source_names=["semanticscholar_reference"],
            )
        )
    return results


def fetch_candidate_full_text(candidate: PaperCandidate, client: HttpClient) -> tuple[str, str]:
    for url in [candidate.open_access_url, candidate.url]:
        if not url:
            continue
        response = client.fetch(url, headers={"Accept": "text/html,application/pdf;q=0.9,*/*;q=0.8"})
        content_type = response.content_type.lower()
        if "pdf" in content_type or response.final_url.lower().endswith(".pdf") or url.lower().endswith(".pdf"):
            text = _extract_text_from_pdf_bytes(response.body)
            if text:
                return text, "pdf"
        html = response.body.decode("utf-8", errors="ignore")
        text = _extract_text_from_html(html)
        if text:
            return text, "html"
    raise SourceError(f"no readable content found for {candidate.title}")


def _extract_text_from_html(html: str) -> str:
    parser = HtmlTextParser()
    parser.feed(html)
    parser.close()
    text = parser.text()
    return text[:20000]


def _extract_text_from_pdf_bytes(payload: bytes) -> str:
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "document.pdf"
            txt_path = Path(tmpdir) / "document.txt"
            pdf_path.write_bytes(payload)
            try:
                subprocess.run(
                    [pdftotext, "-layout", "-nopgbrk", str(pdf_path), str(txt_path)],
                    check=True,
                    capture_output=True,
                    timeout=30,
                )
                return _clean_text(txt_path.read_text(encoding="utf-8", errors="ignore"))[:20000]
            except Exception:
                pass

    decoded = payload.decode("latin-1", errors="ignore")
    fragments = re.findall(r"\(([A-Za-z0-9 ,.;:()\-_/]{20,})\)", decoded)
    return _clean_text(" ".join(fragments))[:20000]
