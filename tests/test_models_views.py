from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.models import Candidate, PaperCandidate, RetrievalCandidate, ScoredCandidate, EnrichedCandidate


class CandidateAliasTests(unittest.TestCase):
    def test_all_candidate_aliases_point_to_same_class(self) -> None:
        self.assertIs(PaperCandidate, Candidate)
        self.assertIs(RetrievalCandidate, Candidate)
        self.assertIs(ScoredCandidate, Candidate)
        self.assertIs(EnrichedCandidate, Candidate)

    def test_candidate_has_all_fields(self) -> None:
        candidate = Candidate(
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
        self.assertEqual(candidate.score, 0.7)
        self.assertEqual(candidate.full_text, "Full text")
        self.assertEqual(candidate.evidence, ["evidence"])
        self.assertEqual(candidate.flags, ["benchmark_intent"])

    def test_candidate_round_trips_through_dict(self) -> None:
        candidate = Candidate(
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
        payload = candidate.to_dict()
        restored = Candidate.from_dict(payload)
        self.assertEqual(restored.title, "Paper")
        self.assertEqual(restored.score, 0.7)
        self.assertEqual(restored.full_text, "Full text")
        self.assertEqual(restored.evidence, ["evidence"])


if __name__ == "__main__":
    unittest.main()
