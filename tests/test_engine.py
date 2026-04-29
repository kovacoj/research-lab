from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.engine import _expansion_seed_candidates, _search_all_sources
from research_lab.models import PaperCandidate, QueryRecord, ResearchBrief
from research_lab.sources import SourceError


class EngineTests(unittest.TestCase):
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
        )

        seeds = _expansion_seed_candidates([web, drift_paper, weak_paper, clean_paper], brief)

        self.assertEqual([candidate.title for candidate in seeds], [clean_paper.title])

    def test_search_all_sources_disables_semantic_scholar_after_rate_limit(self) -> None:
        brief = ResearchBrief(topic="graph neural networks", context="")
        query = QueryRecord(query="graph neural networks", origin="topic", iteration=0)
        warnings: list[str] = []
        source_state = {
            "semanticscholar_enabled": True,
            "semanticscholar_has_api_key": False,
            "semanticscholar_requests_remaining": 5,
        }

        with patch("research_lab.engine.search_arxiv", return_value=[]), patch(
            "research_lab.engine.search_openalex", return_value=[]
        ), patch("research_lab.engine.search_duckduckgo", return_value=[]), patch(
            "research_lab.engine.search_google_scholar", return_value=[]
        ), patch(
            "research_lab.engine.search_semantic_scholar",
            side_effect=SourceError("request failed for semantic scholar: HTTP Error 429:"),
        ) as semantic_mock:
            _search_all_sources(query, brief, object(), warnings, source_state)
            _search_all_sources(query, brief, object(), warnings, source_state)

        self.assertEqual(semantic_mock.call_count, 1)
        self.assertFalse(source_state["semanticscholar_enabled"])
        self.assertEqual(warnings, ["semantic scholar disabled after rate limit"])

    def test_search_all_sources_skips_semantic_scholar_for_low_value_expansion_without_key(self) -> None:
        brief = ResearchBrief(topic="graph neural networks", context="")
        query = QueryRecord(query='"Jane Doe" graph neural networks', origin="author_expansion", iteration=1)
        warnings: list[str] = []
        source_state = {
            "semanticscholar_enabled": True,
            "semanticscholar_has_api_key": False,
            "semanticscholar_requests_remaining": 5,
        }

        with patch("research_lab.engine.search_arxiv", return_value=[]), patch(
            "research_lab.engine.search_openalex", return_value=[]
        ), patch("research_lab.engine.search_duckduckgo", return_value=[]), patch(
            "research_lab.engine.search_google_scholar", return_value=[]
        ), patch("research_lab.engine.search_semantic_scholar") as semantic_mock:
            _search_all_sources(query, brief, object(), warnings, source_state)

        semantic_mock.assert_not_called()
        self.assertEqual(source_state["semanticscholar_requests_remaining"], 5)


if __name__ == "__main__":
    unittest.main()
