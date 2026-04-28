from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.models import PaperCandidate, ResearchBrief
from research_lab.rank import dedupe_candidates, extract_evidence_sentences, rank_candidates


class RankTests(unittest.TestCase):
    def test_dedupe_prefers_richer_candidate(self) -> None:
        first = PaperCandidate(
            title="A Useful Paper",
            abstract="",
            url="https://example.com/1",
            source="openalex",
            source_id="oa:1",
            doi="10.1000/example",
            source_names=["openalex"],
        )
        second = PaperCandidate(
            title="A Useful Paper",
            abstract="Has abstract",
            url="https://example.com/2",
            source="semanticscholar",
            source_id="s2:1",
            doi="10.1000/example",
            citation_count=42,
            source_names=["semanticscholar"],
        )

        merged = dedupe_candidates([first, second])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].abstract, "Has abstract")
        self.assertEqual(merged[0].citation_count, 42)
        self.assertEqual(merged[0].source_names, ["openalex", "semanticscholar"])

    def test_rank_prefers_topic_overlap(self) -> None:
        brief = ResearchBrief(topic="test time adaptation for language models", context="I have looked at prompt tuning.")
        relevant = PaperCandidate(
            title="Test-Time Adaptation for Large Language Models",
            abstract="We study adaptation of language models at inference time.",
            url="https://example.com/relevant",
            source="openalex",
            source_id="oa:relevant",
            source_names=["openalex"],
        )
        off_topic = PaperCandidate(
            title="Protein Folding With Diffusion Models",
            abstract="A biology paper.",
            url="https://example.com/off-topic",
            source="openalex",
            source_id="oa:off-topic",
            source_names=["openalex"],
        )

        ranked = rank_candidates([off_topic, relevant], brief)

        self.assertEqual(ranked[0].title, relevant.title)

    def test_dedupe_merges_title_match_when_only_one_source_has_doi(self) -> None:
        with_doi = PaperCandidate(
            title="MedAdapter: Efficient Test-Time Adaptation of Large Language Models Towards Medical Reasoning",
            abstract="",
            url="https://example.com/a",
            source="openalex",
            source_id="oa:medadapter",
            doi="10.18653/v1/2024.emnlp-main.1244",
            source_names=["openalex"],
        )
        without_doi = PaperCandidate(
            title="MedAdapter: Efficient Test-Time Adaptation of Large Language Models towards Medical Reasoning",
            abstract="abstract",
            url="https://example.com/b",
            source="semanticscholar",
            source_id="s2:medadapter",
            source_names=["semanticscholar"],
        )

        merged = dedupe_candidates([with_doi, without_doi])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].doi, "10.18653/v1/2024.emnlp-main.1244")
        self.assertEqual(merged[0].abstract, "abstract")

    def test_dedupe_merges_truncated_web_title(self) -> None:
        paper = PaperCandidate(
            title="MedAdapter: Efficient Test-Time Adaptation of Large Language Models Towards Medical Reasoning",
            abstract="full abstract",
            url="https://example.com/paper",
            source="openalex",
            source_id="oa:paper",
            source_names=["openalex"],
        )
        web = PaperCandidate(
            title="MedAdapter: Efficient Test-Time Adaptation of Large Language Models ...",
            abstract="snippet",
            url="https://example.com/web",
            source="duckduckgo",
            source_id="web:paper",
            document_kind="web",
            source_names=["duckduckgo"],
        )

        merged = dedupe_candidates([paper, web])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source_names, ["duckduckgo", "openalex"])

    def test_rank_penalizes_broad_modality_drift(self) -> None:
        brief = ResearchBrief(topic="test-time adaptation for language models", context="I need papers about LLM adaptation.")
        precise = PaperCandidate(
            title="Test-Time Adaptation for Large Language Models",
            abstract="We study large language models under test-time adaptation.",
            url="https://example.com/precise",
            source="openalex",
            source_id="oa:precise",
            source_names=["openalex"],
        )
        broad = PaperCandidate(
            title="Embodied Multimodal Large Language Model for Robotic Manipulation",
            abstract="This robot paper uses a large language model and discusses adaptation.",
            url="https://example.com/broad",
            source="openalex",
            source_id="oa:broad",
            source_names=["openalex"],
        )

        ranked = rank_candidates([broad, precise], brief)

        self.assertEqual(ranked[0].title, precise.title)

    def test_extract_evidence_sentences_prefers_relevant_claims(self) -> None:
        brief = ResearchBrief(topic="prompt tuning for language models", context="I need evidence about inference-time adaptation.")
        text = (
            "Large language models can be adapted at inference time with lightweight prompt tuning. "
            "This often improves downstream robustness without updating all model weights. "
            "Unrelated sentence about weather patterns."
        )

        evidence = extract_evidence_sentences(text, brief)

        self.assertGreaterEqual(len(evidence), 1)
        self.assertIn("prompt tuning", evidence[0].lower())


if __name__ == "__main__":
    unittest.main()
