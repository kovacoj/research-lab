from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.engine import _expansion_seed_candidates
from research_lab.models import PaperCandidate, QueryRecord, ResearchBrief
from research_lab.retrieval import RetrievalPolicy
from research_lab.search_session import SearchSession
from research_lab.sources import HttpClient, HttpResponse, SourceError


class _FakeClient(HttpClient):
    def __init__(self, responses: dict[str, object]) -> None:
        super().__init__()
        self.responses = responses

    def fetch(self, url: str, headers: dict[str, str] | None = None) -> HttpResponse:
        del headers
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> dict:
        del headers
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class EngineTests(unittest.TestCase):
    def test_search_session_records_unique_queries(self) -> None:
        brief = ResearchBrief(topic="graph neural networks", context="")
        session = SearchSession(brief)
        query = QueryRecord(query="graph neural networks", origin="topic", iteration=0)

        first = session._record_query(query)
        second = session._record_query(query)

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(session.queries, [query])

    def test_expansion_seed_candidates_prefer_clean_papers(self) -> None:
        brief = ResearchBrief(topic="mixed precision training", context="", must_include=["mixed precision", "float16", "loss scaling"])
        web = PaperCandidate(
            title="What is Mixed Precision Training?",
            abstract="A web explainer.",
            url="https://example.com/web",
            source="duckduckgo",
            source_id="web:1",
            document_kind="web",
            source_names=["duckduckgo"],
            score=1.2,
            reasons=["topic overlap 3/4"],
        )
        drift_paper = PaperCandidate(
            title="Vision-Language Mixed Precision Training",
            abstract="An adjacent modality paper.",
            url="https://example.com/drift",
            source="openalex",
            source_id="oa:drift",
            document_kind="paper",
            source_names=["openalex"],
            score=1.1,
            reasons=["visual modality drift"],
            flags=["drift"],
        )
        clean_paper = PaperCandidate(
            title="Mixed Precision Training",
            abstract="A direct paper about float16 and loss scaling.",
            url="https://example.com/paper",
            source="openalex",
            source_id="oa:paper",
            document_kind="paper",
            source_names=["openalex"],
            score=0.9,
            reasons=["topic overlap 4/4"],
        )

        weak_paper = PaperCandidate(
            title="Distributed Training for Deep Neural Networks",
            abstract="Mentions mixed precision once.",
            url="https://example.com/weak",
            source="openalex",
            source_id="oa:weak",
            document_kind="paper",
            source_names=["openalex"],
            score=1.0,
            reasons=["topic overlap 4/4"],
            flags=["weak_title"],
        )

        seeds = _expansion_seed_candidates([web, drift_paper, weak_paper, clean_paper], brief)

        self.assertEqual([candidate.title for candidate in seeds], [clean_paper.title])

    def test_expansion_seed_candidates_uses_scored_fields_only(self) -> None:
        brief = ResearchBrief(topic="mixed precision training", context="", must_include=["mixed precision"])
        candidate = PaperCandidate(
            title="Mixed Precision Training",
            abstract="A direct paper about mixed precision.",
            url="https://example.com/paper",
            source="openalex",
            source_id="oa:paper-2",
            document_kind="paper",
            source_names=["openalex"],
            score=0.9,
            reasons=["topic overlap 3/3"],
        )

        scored = candidate
        scored.flags = []
        seeds = _expansion_seed_candidates([scored], brief)

        self.assertEqual([item.title for item in seeds], [candidate.title])

    def test_retrieval_policy_disables_semantic_scholar_after_rate_limit(self) -> None:
        brief = ResearchBrief(topic="graph neural networks", context="")
        query = QueryRecord(query="graph neural networks", origin="topic", iteration=0)
        client = _FakeClient(
            {
                "https://api.openalex.org/works?search=graph+neural+networks&per-page=8&sort=relevance_score%3Adesc": {"results": []},
                "https://api.semanticscholar.org/graph/v1/paper/search?query=graph+neural+networks&limit=8&fields=paperId%2Ctitle%2Cabstract%2Curl%2Cyear%2Cauthors%2Cvenue%2CcitationCount%2CexternalIds%2CopenAccessPdf%2CfieldsOfStudy": SourceError("request failed for semantic scholar: HTTP Error 429:"),
                "https://html.duckduckgo.com/html/?q=graph+neural+networks": HttpResponse(body=b"<html></html>", content_type="text/html", final_url="https://html.duckduckgo.com/html/?q=graph+neural+networks"),
            }
        )
        policy = RetrievalPolicy(client=client, scholar_per_query=0)
        policy._state["arxiv_enabled"] = False
        policy._state["semanticscholar_enabled"] = True
        policy._state["semanticscholar_requests_remaining"] = 5

        policy.search(query, brief)
        policy.search(query, brief)

        self.assertEqual(policy.warnings, ["semantic scholar disabled after rate limit"])
        self.assertFalse(policy._state["semanticscholar_enabled"])

    def test_retrieval_policy_skips_semantic_scholar_for_low_value_expansion_without_key(self) -> None:
        brief = ResearchBrief(topic="graph neural networks", context="")
        query = QueryRecord(query='"Jane Doe" graph neural networks', origin="author_expansion", iteration=1)
        client = _FakeClient(
            {
                "https://api.openalex.org/works?search=%22Jane+Doe%22+graph+neural+networks&per-page=8&sort=relevance_score%3Adesc": {"results": []},
                "https://html.duckduckgo.com/html/?q=%22Jane+Doe%22+graph+neural+networks": HttpResponse(body=b"<html></html>", content_type="text/html", final_url="https://html.duckduckgo.com/html/?q=%22Jane+Doe%22+graph+neural+networks"),
            }
        )
        policy = RetrievalPolicy(client=client, scholar_per_query=0)
        policy._state["semanticscholar_enabled"] = True
        policy._state["semanticscholar_requests_remaining"] = 5

        policy.search(query, brief)

        self.assertEqual(policy._state["semanticscholar_requests_remaining"], 5)

    def test_retrieval_policy_disables_arxiv_after_rate_limit(self) -> None:
        brief = ResearchBrief(topic="graph neural networks", context="")
        query = QueryRecord(query="graph neural networks", origin="topic", iteration=0)
        client = _FakeClient(
            {
                "https://export.arxiv.org/api/query?search_query=all%3Agraph+neural+networks&start=0&max_results=8&sortBy=relevance&sortOrder=descending": SourceError("request failed for arxiv: HTTP Error 429:"),
                "https://api.openalex.org/works?search=graph+neural+networks&per-page=8&sort=relevance_score%3Adesc": {"results": []},
                "https://html.duckduckgo.com/html/?q=graph+neural+networks": HttpResponse(body=b"<html></html>", content_type="text/html", final_url="https://html.duckduckgo.com/html/?q=graph+neural+networks"),
            }
        )
        policy = RetrievalPolicy(client=client, scholar_per_query=0)

        policy.search(query, brief)
        policy.search(query, brief)

        self.assertEqual(policy.warnings, ["arxiv disabled after rate limit"])
        self.assertFalse(policy._state["arxiv_enabled"])

    def test_retrieval_policy_disables_google_scholar_after_block(self) -> None:
        brief = ResearchBrief(topic="graph neural networks", context="", scholar_per_query=1)
        query = QueryRecord(query="graph neural networks", origin="topic", iteration=0)
        client = _FakeClient(
            {
                "https://api.openalex.org/works?search=graph+neural+networks&per-page=8&sort=relevance_score%3Adesc": {"results": []},
                "https://html.duckduckgo.com/html/?q=graph+neural+networks": HttpResponse(body=b"<html></html>", content_type="text/html", final_url="https://html.duckduckgo.com/html/?q=graph+neural+networks"),
                "https://scholar.google.com/scholar?hl=en&q=graph+neural+networks&num=1": SourceError("google scholar blocked automated access"),
            }
        )
        policy = RetrievalPolicy(client=client, scholar_per_query=0)
        policy._state["arxiv_enabled"] = False
        policy._state["googlescholar_enabled"] = True
        policy._state["googlescholar_requests_remaining"] = 3

        policy.search(query, brief)
        policy.search(query, brief)

        self.assertEqual(policy.warnings, ["google scholar disabled after block"])
        self.assertFalse(policy._state["googlescholar_enabled"])


if __name__ == "__main__":
    unittest.main()
