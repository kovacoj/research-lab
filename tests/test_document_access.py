from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.document_access import DocumentAccessResolver
from research_lab.models import PaperCandidate
from research_lab.sources import HttpResponse, SourceError


class _FakeClient:
    def __init__(self, responses: dict[str, HttpResponse | Exception]) -> None:
        self.responses = responses

    def fetch(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
        del headers
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class DocumentAccessResolverTests(unittest.TestCase):
    def test_fetch_falls_back_from_open_access_url_to_landing_page(self) -> None:
        candidate = PaperCandidate(
            title="Fallback Paper",
            abstract="",
            url="https://example.com/landing",
            source="openalex",
            source_id="oa:1",
            open_access_url="https://example.com/missing.pdf",
            document_kind="paper",
            source_names=["openalex"],
        )
        html = b"""
        <html><body>
          <h1>Fallback Paper</h1>
          <h2>Introduction</h2>
          <p>This paper includes readable full text content.</p>
          <h2>Methods</h2><p>Method text.</p>
          <h2>Results</h2><p>Result text.</p>
          <h2>References</h2><p>Refs.</p>
        </body></html>
        """
        client = _FakeClient(
            {
                "https://example.com/missing.pdf": SourceError("request failed for https://example.com/missing.pdf: HTTP Error 404:"),
                "https://example.com/landing": HttpResponse(
                    body=html,
                    content_type="text/html",
                    final_url="https://example.com/landing",
                ),
            }
        )

        result = DocumentAccessResolver(client).fetch(candidate)

        self.assertEqual(result.access_status, "open")
        self.assertEqual(result.source, "html")
        self.assertTrue(result.text)


if __name__ == "__main__":
    unittest.main()
