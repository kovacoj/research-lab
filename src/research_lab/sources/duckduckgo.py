from __future__ import annotations

from html.parser import HTMLParser
import urllib.parse

from research_lab.models import Candidate
from research_lab.sources.extraction import _clean_text
from research_lab.sources.transport import HttpClient


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
            self.results.append({"title": title, "url": url, "snippet": _clean_text(self._current.get("snippet", ""))})
        self._current = None


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


def search_duckduckgo(query: str, limit: int, client: HttpClient) -> list[Candidate]:
    if limit <= 0:
        return []
    response = client.fetch(f"https://html.duckduckgo.com/html/?{urllib.parse.urlencode({'q': query})}")
    parser = DuckDuckGoHtmlParser()
    parser.feed(response.body.decode("utf-8", errors="ignore"))
    parser.close()
    return [
        Candidate(
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
        for item in parser.results[:limit]
    ]
