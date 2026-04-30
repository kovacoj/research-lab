from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.final_ranking import group_final_ranking, is_broad_intent_match
from research_lab.models import EnrichedCandidate, ResearchBrief


class FinalRankingTests(unittest.TestCase):
    def test_group_final_ranking_builds_report_ready_groups(self) -> None:
        brief = ResearchBrief(topic="graph neural networks", context="notes", top_k=3)
        survey = EnrichedCandidate(
            title="Survey",
            abstract="A survey",
            url="https://example.com/survey",
            source="openalex",
            source_id="oa:survey",
            score=0.9,
            flags=["survey_intent"],
        )
        lead = EnrichedCandidate(
            title="Lead",
            abstract="A paper",
            url="https://example.com/lead",
            source="openalex",
            source_id="oa:lead",
            score=0.6,
        )
        exploratory = EnrichedCandidate(
            title="Exploratory",
            abstract="A weaker paper",
            url="https://example.com/exploratory",
            source="openalex",
            source_id="oa:exploratory",
            score=0.2,
        )

        ranking = group_final_ranking([exploratory, survey, lead], brief)

        self.assertEqual([candidate.title for candidate in ranking.ranked], ["Survey", "Lead", "Exploratory"])
        self.assertEqual([candidate.title for candidate in ranking.high_confidence], ["Survey", "Lead"])
        self.assertEqual([candidate.title for candidate in ranking.exploratory], ["Exploratory"])
        self.assertEqual([candidate.title for candidate in ranking.broad_intent], ["Survey"])

    def test_is_broad_intent_match_reads_flags(self) -> None:
        candidate = EnrichedCandidate(
            title="Benchmark",
            abstract="Benchmark paper",
            url="https://example.com/benchmark",
            source="openalex",
            source_id="oa:benchmark",
            flags=["benchmark_intent"],
        )

        self.assertTrue(is_broad_intent_match(candidate))


if __name__ == "__main__":
    unittest.main()
