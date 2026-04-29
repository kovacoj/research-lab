from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.models import PaperCandidate
from research_lab.sources import (
    HttpResponse,
    _decode_duckduckgo_url,
    _extract_text_from_html,
    fetch_candidate_full_text,
    search_arxiv,
    search_google_scholar,
)


class _FakeClient:
    def __init__(self, responses: dict[str, HttpResponse]) -> None:
        self.responses = responses

    def fetch(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
        del headers
        return self.responses[url]


class SourceHelpersTests(unittest.TestCase):
    def test_decode_duckduckgo_redirect_url(self) -> None:
        redirected = "/l/?uddg=https%3A%2F%2Fexample.com%2Fpaper"

        decoded = _decode_duckduckgo_url(redirected)

        self.assertEqual(decoded, "https://example.com/paper")

    def test_extract_text_from_html_ignores_script(self) -> None:
        html = """
        <html>
          <head><script>console.log('ignore me')</script></head>
          <body>
            <h1>Claim</h1>
            <p>This page strengthens the argument.</p>
          </body>
        </html>
        """

        text = _extract_text_from_html(html)

        self.assertIn("Claim", text)
        self.assertIn("strengthens the argument", text)
        self.assertNotIn("ignore me", text)

    def test_search_arxiv_parses_atom_feed(self) -> None:
        xml = b"""<?xml version='1.0' encoding='UTF-8'?>
        <feed xmlns='http://www.w3.org/2005/Atom' xmlns:arxiv='http://arxiv.org/schemas/atom'>
          <entry>
            <id>http://arxiv.org/abs/2401.12345v1</id>
            <updated>2024-01-20T00:00:00Z</updated>
            <published>2024-01-20T00:00:00Z</published>
            <title> Test-Time Adaptation for Language Models </title>
            <summary> We study adaptation at inference time. </summary>
            <author><name>Jane Doe</name></author>
            <author><name>John Roe</name></author>
            <link rel='alternate' type='text/html' href='http://arxiv.org/abs/2401.12345v1' />
            <link title='pdf' rel='related' type='application/pdf' href='http://arxiv.org/pdf/2401.12345v1' />
            <arxiv:doi>10.48550/arXiv.2401.12345</arxiv:doi>
          </entry>
        </feed>
        """
        client = _FakeClient(
            {
                "https://export.arxiv.org/api/query?search_query=all%3Atest-time+adaptation&start=0&max_results=2&sortBy=relevance&sortOrder=descending": HttpResponse(
                    body=xml,
                    content_type="application/atom+xml",
                    final_url="https://export.arxiv.org/api/query",
                )
            }
        )

        results = search_arxiv("test-time adaptation", 2, 2023, client)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "arxiv")
        self.assertEqual(results[0].year, 2024)
        self.assertEqual(results[0].authors, ["Jane Doe", "John Roe"])
        self.assertEqual(results[0].open_access_url, "http://arxiv.org/pdf/2401.12345v1")

    def test_search_google_scholar_parses_results(self) -> None:
        html = b"""
        <html><body>
          <div class='gs_r gs_or gs_scl'>
            <div class='gs_ggs gs_fl'>
              <div class='gs_or_ggsm'><a href='https://example.com/paper.pdf'>[PDF]</a></div>
            </div>
            <div class='gs_ri'>
              <h3 class='gs_rt'><a href='https://example.com/paper'>Test-Time Adaptation for Language Models</a></h3>
              <div class='gs_a'>Jane Doe, John Roe - Journal of Testing, 2024</div>
              <div class='gs_rs'>A strong paper about inference-time adaptation.</div>
            </div>
          </div>
        </body></html>
        """
        client = _FakeClient(
            {
                "https://scholar.google.com/scholar?hl=en&q=test-time+adaptation&num=3": HttpResponse(
                    body=html,
                    content_type="text/html",
                    final_url="https://scholar.google.com/scholar?hl=en&q=test-time+adaptation&num=3",
                )
            }
        )

        results = search_google_scholar("test-time adaptation", 3, client)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "googlescholar")
        self.assertEqual(results[0].authors, ["Jane Doe", "John Roe"])
        self.assertEqual(results[0].year, 2024)
        self.assertEqual(results[0].open_access_url, "https://example.com/paper.pdf")

    def test_fetch_candidate_full_text_marks_abstract_only_paper(self) -> None:
        candidate = PaperCandidate(
            title="A Paywalled Paper",
            abstract="",
            url="https://example.com/abstract",
            source="openalex",
            source_id="oa:1",
            document_kind="paper",
            source_names=["openalex"],
        )
        html = b"""
        <html><body>
          <h1>A Paywalled Paper</h1>
          <h2>Abstract</h2>
          <p>This page only shows the abstract and a short description.</p>
        </body></html>
        """
        client = _FakeClient(
            {
                "https://example.com/abstract": HttpResponse(
                    body=html,
                    content_type="text/html",
                    final_url="https://example.com/abstract",
                )
            }
        )

        result = fetch_candidate_full_text(candidate, client)

        self.assertEqual(result.access_status, "abstract_only")
        self.assertEqual(result.text, "")


if __name__ == "__main__":
    unittest.main()
