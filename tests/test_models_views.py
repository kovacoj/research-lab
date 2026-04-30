from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.models import EnrichedCandidate, PaperCandidate, RetrievalCandidate, ScoredCandidate


class CandidateViewTests(unittest.TestCase):
    def test_candidate_views_hide_unset_lifecycle_fields(self) -> None:
        retrieval = RetrievalCandidate(
            title="Paper",
            abstract="Abstract",
            url="https://example.com",
            source="openalex",
            source_id="oa:1",
        )
        scored = ScoredCandidate(
            title="Paper",
            abstract="Abstract",
            url="https://example.com",
            source="openalex",
            source_id="oa:1",
            score=0.7,
            reasons=["has abstract"],
            flags=["benchmark_intent"],
        )

        with self.assertRaises(AttributeError):
            _ = retrieval.score
        with self.assertRaises(AttributeError):
            _ = scored.full_text

    def test_enriched_candidate_round_trips_through_paper_candidate(self) -> None:
        paper = PaperCandidate(
            title="Paper",
            abstract="Abstract",
            url="https://example.com",
            source="openalex",
            source_id="oa:1",
            score=0.7,
            reasons=["has abstract"],
            flags=["benchmark_intent"],
            full_text="Full text",
            evidence=["evidence"],
        )

        enriched = EnrichedCandidate.from_paper_candidate(paper)
        round_tripped = enriched.to_paper_candidate()

        self.assertEqual(round_tripped.full_text, "Full text")
        self.assertEqual(round_tripped.flags, ["benchmark_intent"])
        self.assertEqual(round_tripped.evidence, ["evidence"])


if __name__ == "__main__":
    unittest.main()
