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

    def test_extract_evidence_sentences_trims_pdf_preamble(self) -> None:
        brief = ResearchBrief(topic="graph neural networks for molecular property prediction", context="")
        text = (
            "Article Chemistry-intuitive explanation of graph neural networks for molecular property prediction with substructure masking "
            "Received 2022 Jane Doe, John Roe, Foo Bar. Graph neural networks for molecular property prediction are widely used in chemistry."
        )

        evidence = extract_evidence_sentences(text, brief)

        self.assertGreaterEqual(len(evidence), 1)
        self.assertTrue(evidence[0].lower().startswith("graph neural networks"))
        self.assertNotIn("jane doe", evidence[0].lower())

    def test_rank_prefers_structured_paper_over_light_metadata_web_page(self) -> None:
        brief = ResearchBrief(topic="mixed precision training", context="I need foundational and practical training sources.")
        paper = PaperCandidate(
            title="Mixed Precision Training",
            abstract="A foundational paper about half precision training and loss scaling.",
            url="https://example.com/paper",
            source="openalex",
            source_id="oa:paper",
            authors=["A Researcher"],
            year=2017,
            venue="Neural Conference",
            doi="10.1000/mixed",
            document_kind="paper",
            source_names=["openalex"],
        )
        web = PaperCandidate(
            title="What is Mixed Precision Training?",
            abstract="A simple explainer for mixed precision training.",
            url="https://example.com/web",
            source="duckduckgo",
            source_id="web:mixed",
            document_kind="web",
            source_names=["duckduckgo"],
        )

        ranked = rank_candidates([web, paper], brief)

        self.assertEqual(ranked[0].title, paper.title)

    def test_rank_penalizes_weak_must_include_coverage(self) -> None:
        brief = ResearchBrief(
            topic="mixed precision arithmetic for deep learning training",
            context="I need practical training sources.",
            must_include=["mixed precision", "float16", "bfloat16", "loss scaling"],
        )
        broad = PaperCandidate(
            title="A Hitchhiker's Guide On Distributed Training of Deep Neural Networks",
            abstract="This survey briefly mentions mixed precision training among many distributed techniques.",
            url="https://example.com/broad",
            source="openalex",
            source_id="oa:broad",
            document_kind="paper",
            source_names=["openalex"],
        )
        precise = PaperCandidate(
            title="Mixed Precision Training",
            abstract="We study float16, bfloat16, and loss scaling for deep learning training.",
            url="https://example.com/precise",
            source="openalex",
            source_id="oa:precise",
            document_kind="paper",
            source_names=["openalex"],
        )

        ranked = rank_candidates([broad, precise], brief)

        self.assertEqual(ranked[0].title, precise.title)

    def test_rank_prefers_review_when_context_requests_foundational_survey_sources(self) -> None:
        brief = ResearchBrief(
            topic="graph neural networks for molecular property prediction",
            context="I want foundational and practical papers, plus strong surveys and benchmark-oriented sources.",
        )
        method_paper = PaperCandidate(
            title="Cross-dependent graph neural networks for molecular property prediction",
            abstract="A direct method paper for the task.",
            url="https://example.com/method",
            source="openalex",
            source_id="oa:method",
            year=2024,
            citation_count=8,
            document_kind="paper",
            source_names=["openalex"],
        )
        review_paper = PaperCandidate(
            title="A compact review of molecular property prediction with graph neural networks",
            abstract="This review benchmarks models and surveys the field.",
            url="https://example.com/review",
            source="openalex",
            source_id="oa:review",
            year=2020,
            citation_count=400,
            document_kind="paper",
            source_names=["openalex"],
        )

        ranked = rank_candidates([method_paper, review_paper], brief)

        self.assertEqual(ranked[0].title, review_paper.title)

    def test_rank_prefers_foundational_comparison_when_context_is_mixed_intent(self) -> None:
        brief = ResearchBrief(
            topic="graph neural networks for molecular property prediction",
            context="I want foundational and practical papers, plus strong surveys and benchmark-oriented sources.",
        )
        exact_method = PaperCandidate(
            title="Cross-dependent graph neural networks for molecular property prediction",
            abstract="A direct method paper for the task.",
            url="https://example.com/method",
            source="openalex",
            source_id="oa:method-2",
            year=2024,
            citation_count=8,
            document_kind="paper",
            source_names=["openalex"],
        )
        foundational_comparison = PaperCandidate(
            title="Could graph neural networks learn better molecular representation for drug discovery? A comparison study of descriptor-based and graph-based models",
            abstract="This comparison study benchmarks graph-based and descriptor-based models across datasets.",
            url="https://example.com/comparison",
            source="openalex",
            source_id="oa:comparison",
            year=2021,
            citation_count=350,
            document_kind="paper",
            source_names=["openalex"],
        )

        ranked = rank_candidates([exact_method, foundational_comparison], brief)

        self.assertEqual(ranked[0].title, foundational_comparison.title)


if __name__ == "__main__":
    unittest.main()
