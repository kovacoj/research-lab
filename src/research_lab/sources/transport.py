from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


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
