from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.engine import _expansion_seed_candidates
from research_lab.models import PaperCandidate, ResearchBrief


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


if __name__ == "__main__":
    unittest.main()
