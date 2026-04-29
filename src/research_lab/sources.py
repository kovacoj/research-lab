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
import xml.etree.ElementTree as ET
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
class FullTextResult:
    text: str
    source: str
    access_status: str
    access_url: str


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


class GoogleScholarHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._depth = 0
        self._in_title = False
        self._in_meta = False
        self._in_snippet = False
        self._in_access_link = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        classes = set(attr_map.get("class", "").split())

        if tag == "div" and "gs_r" in classes and "gs_or" in classes:
            self._flush_current()
            self._current = {"title": "", "url": "", "meta": "", "snippet": "", "open_access_url": ""}
            self._depth = 1
            return

        if self._current is None:
            return

        self._depth += 1
        if tag == "h3" and "gs_rt" in classes:
            self._in_title = True
            if not self._current.get("url"):
                self._current["url"] = _decode_google_scholar_url(attr_map.get("href", ""))
        elif tag == "a" and self._in_title:
            self._current["url"] = _decode_google_scholar_url(attr_map.get("href", ""))
        elif tag == "div" and "gs_a" in classes:
            self._in_meta = True
        elif tag == "div" and "gs_rs" in classes:
            self._in_snippet = True
        elif tag == "div" and "gs_or_ggsm" in classes:
            self._in_access_link = True
        elif tag == "a" and self._in_access_link and not self._current.get("open_access_url"):
            self._current["open_access_url"] = _decode_google_scholar_url(attr_map.get("href", ""))

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return

        if tag == "h3" and self._in_title:
            self._in_title = False
        elif tag == "div" and self._in_meta:
            self._in_meta = False
        elif tag == "div" and self._in_snippet:
            self._in_snippet = False
        elif tag == "div" and self._in_access_link:
            self._in_access_link = False

        self._depth -= 1
        if self._depth <= 0:
            self._flush_current()

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        if self._in_title:
            self._current["title"] += data
        elif self._in_meta:
            self._current["meta"] += data
        elif self._in_snippet:
            self._current["snippet"] += data

    def close(self) -> None:
        super().close()
        self._flush_current()

    def _flush_current(self) -> None:
        if self._current is None:
            return
        title = _clean_text(self._current.get("title", ""))
        url = self._current.get("url", "") or self._current.get("open_access_url", "")
        if title and url:
            self.results.append(
                {
                    "title": title,
                    "url": url,
                    "meta": _clean_text(self._current.get("meta", "")),
                    "snippet": _clean_text(self._current.get("snippet", "")),
                    "open_access_url": self._current.get("open_access_url", ""),
                }
            )
        self._current = None
        self._depth = 0
        self._in_title = False
        self._in_meta = False
        self._in_snippet = False
        self._in_access_link = False


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


def _decode_google_scholar_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.path == "/scholar_url":
        query = urllib.parse.parse_qs(parsed.query)
        target = query.get("url", [""])[0]
        if target:
            return urllib.parse.unquote(target)
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://scholar.google.com{url}"
    return url


def _url_host(url: str) -> str:
    return urllib.parse.urlparse(url).netloc


def _extract_year(text: str) -> int | None:
    match = re.search(r"\b(19|20)\d{2}\b", text)
    if not match:
        return None
    return int(match.group(0))


def _parse_scholar_authors(metadata: str) -> list[str]:
    if not metadata:
        return []
    prefix = metadata.split(" - ", 1)[0]
    authors: list[str] = []
    for item in prefix.split(","):
        cleaned = item.strip()
        if cleaned and cleaned not in {"...", "…"}:
            authors.append(cleaned)
    return authors[:6]


def _parse_scholar_venue(metadata: str, year: int | None) -> str:
    parts = [part.strip() for part in metadata.split(" - ") if part.strip()]
    if len(parts) < 2:
        return ""
    venue = parts[1]
    if year is not None:
        venue = venue.replace(str(year), "").strip(" ,")
    return venue


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
    hits = sum(1 for marker in paywall_markers if marker in text)
    return hits >= 1


def _looks_like_full_text(text: str) -> bool:
    if len(text) >= 12000:
        return True
    section_hits = sum(
        1
        for marker in ["introduction", "method", "methods", "results", "discussion", "conclusion", "references"]
        if re.search(rf"\b{marker}\b", text)
    )
    return section_hits >= 3 or (section_hits >= 2 and len(text) >= 5000)


def _classify_html_access(candidate: PaperCandidate, response: HttpResponse) -> FullTextResult:
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


def search_arxiv(
    query: str,
    limit: int,
    since_year: int | None,
    client: HttpClient,
) -> list[PaperCandidate]:
    params = {
        "search_query": f"all:{query}",
        "start": "0",
        "max_results": str(limit),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    url = f"https://export.arxiv.org/api/query?{urllib.parse.urlencode(params)}"
    response = client.fetch(url)
    try:
        root = ET.fromstring(response.body)
    except ET.ParseError as exc:  # pragma: no cover - malformed upstream payloads are environment specific
        raise SourceError(f"invalid arxiv response for {query}: {exc}") from exc

    namespace = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    results: list[PaperCandidate] = []
    for entry in root.findall("atom:entry", namespace):
        title = _clean_text(entry.findtext("atom:title", default="", namespaces=namespace))
        abstract = _clean_text(entry.findtext("atom:summary", default="", namespaces=namespace))
        published = entry.findtext("atom:published", default="", namespaces=namespace)
        year = _extract_year(published)
        if since_year is not None and year is not None and year < since_year:
            continue
        paper_url = entry.findtext("atom:id", default="", namespaces=namespace)
        pdf_url = ""
        for link in entry.findall("atom:link", namespace):
            if (link.attrib.get("title") or "").lower() == "pdf":
                pdf_url = link.attrib.get("href", "")
                break
        results.append(
            PaperCandidate(
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


def search_google_scholar(
    query: str,
    limit: int,
    client: HttpClient,
) -> list[PaperCandidate]:
    if limit <= 0:
        return []
    params = {"hl": "en", "q": query, "num": str(min(limit, 20))}
    url = f"https://scholar.google.com/scholar?{urllib.parse.urlencode(params)}"
    response = client.fetch(url)
    html = response.body.decode("utf-8", errors="ignore")
    lowered = html.lower()
    if "/sorry/" in lowered or "not a robot" in lowered or "unusual traffic" in lowered:
        raise SourceError("google scholar blocked automated access")
    parser = GoogleScholarHtmlParser()
    parser.feed(html)
    parser.close()

    results: list[PaperCandidate] = []
    for item in parser.results[:limit]:
        year = _extract_year(item["meta"])
        results.append(
            PaperCandidate(
                title=item["title"],
                abstract=item["snippet"],
                url=item["url"],
                source="googlescholar",
                source_id=item["url"],
                authors=_parse_scholar_authors(item["meta"]),
                year=year,
                venue=_parse_scholar_venue(item["meta"], year),
                open_access_url=item.get("open_access_url", ""),
                snippet=item["snippet"],
                source_names=["googlescholar"],
            )
        )
    return results


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


def fetch_candidate_full_text(candidate: PaperCandidate, client: HttpClient) -> FullTextResult:
    last_result = FullTextResult(text="", source="", access_status="", access_url="")
    last_error: SourceError | None = None
    for url in [candidate.open_access_url, candidate.url]:
        if not url:
            continue
        try:
            response = client.fetch(url, headers={"Accept": "text/html,application/pdf;q=0.9,*/*;q=0.8"})
        except SourceError as exc:
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
