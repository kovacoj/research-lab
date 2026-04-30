from __future__ import annotations

from html.parser import HTMLParser
import re
import urllib.parse

from research_lab.models import Candidate
from research_lab.sources.extraction import _clean_text, _extract_year
from research_lab.sources.transport import HttpClient, SourceError


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
            self.results.append({
                "title": title,
                "url": url,
                "meta": _clean_text(self._current.get("meta", "")),
                "snippet": _clean_text(self._current.get("snippet", "")),
                "open_access_url": self._current.get("open_access_url", ""),
            })
        self._current = None
        self._depth = 0
        self._in_title = self._in_meta = self._in_snippet = self._in_access_link = False


def _decode_google_scholar_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.path == "/scholar_url":
        target = urllib.parse.parse_qs(parsed.query).get("url", [""])[0]
        if target:
            return urllib.parse.unquote(target)
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://scholar.google.com{url}"
    return url


def _split_scholar_metadata(metadata: str) -> list[str]:
    parts = [part.strip(" ,") for part in re.split(r"\s*[\u2013\u2014-]\s+", metadata) if part.strip(" ,")]
    return parts or [metadata.strip()]


def _parse_scholar_authors(metadata: str) -> list[str]:
    prefix = _split_scholar_metadata(metadata)[0] if metadata else ""
    authors: list[str] = []
    for item in prefix.split(","):
        cleaned = item.strip().rstrip(". …")
        if cleaned and cleaned not in {"...", "…"} and not re.fullmatch(r"(19|20)\d{2}", cleaned):
            authors.append(cleaned)
    return authors[:6]


def _parse_scholar_venue(metadata: str, year: int | None) -> str:
    parts = _split_scholar_metadata(metadata)
    if len(parts) < 2:
        return ""
    venue = parts[1]
    return venue.replace(str(year), "").strip(" ,") if year is not None else venue


def _clean_scholar_title(title: str) -> str:
    return _clean_text(re.sub(r"^(?:\[(?:HTML|PDF|BOOK|CITATION)\])+\s*", "", title, flags=re.IGNORECASE))


def search_google_scholar(query: str, limit: int, client: HttpClient) -> list[Candidate]:
    if limit <= 0:
        return []
    response = client.fetch(f"https://scholar.google.com/scholar?{urllib.parse.urlencode({'hl': 'en', 'q': query, 'num': str(min(limit, 20))})}")
    html = response.body.decode("utf-8", errors="ignore")
    lowered = html.lower()
    if "/sorry/" in lowered or "not a robot" in lowered or "unusual traffic" in lowered:
        raise SourceError("google scholar blocked automated access")
    parser = GoogleScholarHtmlParser()
    parser.feed(html)
    parser.close()
    return [
        Candidate(
            title=_clean_scholar_title(item["title"]),
            abstract=item["snippet"],
            url=item["url"],
            source="googlescholar",
            source_id=item["url"],
            authors=_parse_scholar_authors(item["meta"]),
            year=_extract_year(item["meta"]),
            venue=_parse_scholar_venue(item["meta"], _extract_year(item["meta"])),
            open_access_url=item.get("open_access_url", ""),
            snippet=item["snippet"],
            source_names=["googlescholar"],
        )
        for item in parser.results[:limit]
    ]
