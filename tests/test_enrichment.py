from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.enrichment import (
    EnrichmentResult,
    enrich_candidate,
    extract_evidence_sentences,
    needs_user_article,
)
from research_lab.models import PaperCandidate, ResearchBrief
from research_lab.sources import HttpResponse, SourceError


class _FakeClient:
    def __init__(self, responses: dict[str, HttpResponse]) -> None:
        self.responses = responses

    def fetch(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
        del headers
        return self.responses[url]


class ExtractEvidenceSentencesTests(unittest.TestCase):
    def test_prefers_relevant_claims(self) -> None:
        brief = ResearchBrief(topic="prompt tuning for language models", context="I need evidence about inference-time adaptation.")
        text = (
            "Large language models can be adapted at inference time with lightweight prompt tuning. "
            "This often improves downstream robustness without updating all model weights. "
            "Unrelated sentence about weather patterns."
        )

        evidence = extract_evidence_sentences(text, brief)

        self.assertGreaterEqual(len(evidence), 1)
        self.assertIn("prompt tuning", evidence[0].lower())

    def test_trims_pdf_preamble(self) -> None:
        brief = ResearchBrief(topic="graph neural networks for molecular property prediction", context="")
        text = (
            "Article Chemistry-intuitive explanation of graph neural networks for molecular property prediction with substructure masking "
            "Received 2022 Jane Doe, John Roe, Foo Bar. Graph neural networks for molecular property prediction are widely used in chemistry."
        )

        evidence = extract_evidence_sentences(text, brief)

        self.assertGreaterEqual(len(evidence), 1)
        self.assertTrue(evidence[0].lower().startswith("graph neural networks"))
        self.assertNotIn("jane doe", evidence[0].lower())


class NeedsUserArticleTests(unittest.TestCase):
    def test_paywalled_high_score_paper_needs_article(self) -> None:
        candidate = PaperCandidate(
            title="Paywalled Paper",
            abstract="",
            url="https://example.com/paper",
            source="openalex",
            source_id="oa:1",
            document_kind="paper",
            source_names=["openalex"],
            score=0.82,
            access_status="paywalled",
            access_url="https://example.com/paper",
        )

        self.assertTrue(needs_user_article(candidate))

    def test_open_paper_does_not_need_article(self) -> None:
        candidate = PaperCandidate(
            title="Open Paper",
            abstract="",
            url="https://example.com/paper",
            source="openalex",
            source_id="oa:2",
            document_kind="paper",
            source_names=["openalex"],
            score=0.82,
            access_status="open",
            full_text="Full text here.",
            access_url="https://example.com/paper",
        )

        self.assertFalse(needs_user_article(candidate))

    def test_low_score_paywalled_does_not_need_article(self) -> None:
        candidate = PaperCandidate(
            title="Low Score Paper",
            abstract="",
            url="https://example.com/paper",
            source="openalex",
            source_id="oa:3",
            document_kind="paper",
            source_names=["openalex"],
            score=0.30,
            access_status="paywalled",
            access_url="https://example.com/paper",
        )

        self.assertFalse(needs_user_article(candidate))

    def test_abstract_only_high_score_needs_article(self) -> None:
        candidate = PaperCandidate(
            title="Abstract Only Paper",
            abstract="Has abstract",
            url="https://example.com/paper",
            source="openalex",
            source_id="oa:4",
            document_kind="paper",
            source_names=["openalex"],
            score=0.60,
            access_status="abstract_only",
            access_url="https://example.com/paper",
        )

        self.assertTrue(needs_user_article(candidate))


class EnrichCandidateTests(unittest.TestCase):
    def test_enrich_candidate_returns_abstract_only(self) -> None:
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
        brief = ResearchBrief(topic="test topic", context="test context")

        result = enrich_candidate(candidate, brief, client)

        self.assertIsInstance(result, EnrichmentResult)
        self.assertEqual(result.access_status, "abstract_only")
        self.assertEqual(result.text, "")
        self.assertEqual(result.evidence, [])

    def test_enrich_candidate_extracts_evidence_from_full_text(self) -> None:
        long_text = (
            "Prompt tuning for language models is an effective approach to adaptation at inference time. "
        ) * 80
        candidate = PaperCandidate(
            title="Prompt Tuning Paper",
            abstract="",
            url="https://example.com/open",
            source="arxiv",
            source_id="arxiv:1",
            document_kind="paper",
            source_names=["arxiv"],
        )
        html = b"""
        <html><body>
          <h1>Prompt Tuning Paper</h1>
          <h2>Introduction</h2>
          <p>Prompt tuning for language models is an effective approach to adaptation at inference time.</p>
          <h2>Methods</h2>
          <p>We describe the method. </p>
          <h2>Results</h2>
          <p>Results are shown. </p>
          <h2>Discussion</h2>
          <p>Discussion follows. </p>
          <h2>Conclusion</h2>
          <p>Concluding remarks. </p>
          <h2>References</h2>
          <p>[1] Reference. </p>
        </body></html>
        """
        client = _FakeClient(
            {
                "https://example.com/open": HttpResponse(
                    body=html,
                    content_type="text/html",
                    final_url="https://example.com/open",
                )
            }
        )
        brief = ResearchBrief(topic="prompt tuning for language models", context="inference time adaptation")

        result = enrich_candidate(candidate, brief, client)

        self.assertEqual(result.access_status, "open")
        self.assertTrue(result.text)
        self.assertGreaterEqual(len(result.evidence), 1)

    def test_enrich_candidate_handles_fetch_error_gracefully(self) -> None:
        candidate = PaperCandidate(
            title="Error Paper",
            abstract="",
            url="https://example.com/error",
            source="openalex",
            source_id="oa:err",
            document_kind="paper",
            source_names=["openalex"],
        )

        class _FailingClient:
            def fetch(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
                del headers
                raise SourceError(f"request failed for {url}: HTTP Error 403: Forbidden")

        brief = ResearchBrief(topic="test topic", context="test context")

        result = enrich_candidate(candidate, brief, _FailingClient())

        self.assertEqual(result.access_status, "paywalled")
        self.assertEqual(result.text, "")
        self.assertEqual(result.evidence, [])

    def test_enrich_candidate_sets_needs_user_article_flag(self) -> None:
        candidate = PaperCandidate(
            title="Paywalled High Score",
            abstract="",
            url="https://example.com/paywalled",
            source="openalex",
            source_id="oa:pw",
            document_kind="paper",
            source_names=["openalex"],
            score=0.82,
        )

        class _FailingClient:
            def fetch(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
                del headers
                raise SourceError(f"request failed for {url}: HTTP Error 403: Forbidden")

        brief = ResearchBrief(topic="test topic", context="test context")

        result = enrich_candidate(candidate, brief, _FailingClient())

        self.assertTrue(result.needs_user_article)


if __name__ == "__main__":
    unittest.main()
