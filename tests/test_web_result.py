from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.models import PaperCandidate
from research_lab.web_result import (
    CATEGORY_LABELS,
    WebResultAssembly,
    assemble_web_results,
    classify_web_source,
    collect_useful_web_sources,
    group_web_sources_by_category,
    is_useful_web_source,
)


class ClassifyWebSourceTests(unittest.TestCase):
    def test_returns_empty_for_paper(self) -> None:
        candidate = PaperCandidate(
            title="A Paper",
            abstract="abstract",
            url="https://example.com/paper",
            source="openalex",
            source_id="oa:1",
            document_kind="paper",
            source_names=["openalex"],
        )
        self.assertEqual(classify_web_source(candidate), "")

    def test_classifies_engineering_explainer_by_phrase(self) -> None:
        candidate = PaperCandidate(
            title="Getting Started with Mixed Precision Training",
            abstract="A practical tutorial.",
            url="https://example.com/blog",
            source="duckduckgo",
            source_id="web:1",
            document_kind="web",
            source_names=["duckduckgo"],
        )
        self.assertEqual(classify_web_source(candidate), "engineering_explainer")

    def test_classifies_engineering_explainer_by_host(self) -> None:
        candidate = PaperCandidate(
            title="Scaling Laws for Neural Language Models",
            abstract="OpenAI blog post.",
            url="https://openai.com/blog/scaling-laws",
            source="duckduckgo",
            source_id="web:2",
            document_kind="web",
            source_names=["duckduckgo"],
        )
        self.assertEqual(classify_web_source(candidate), "engineering_explainer")

    def test_classifies_survey_support(self) -> None:
        candidate = PaperCandidate(
            title="A Survey of Prompt Engineering Techniques",
            abstract="Overview of prompting methods.",
            url="https://example.com/survey",
            source="duckduckgo",
            source_id="web:3",
            document_kind="web",
            source_names=["duckduckgo"],
        )
        self.assertEqual(classify_web_source(candidate), "survey_support")

    def test_classifies_general_web(self) -> None:
        candidate = PaperCandidate(
            title="Some Random Blog Post",
            abstract="Not particularly structured.",
            url="https://example.com/random",
            source="duckduckgo",
            source_id="web:4",
            document_kind="web",
            source_names=["duckduckgo"],
        )
        self.assertEqual(classify_web_source(candidate), "general_web")

    def test_survey_support_takes_priority_over_engineering(self) -> None:
        candidate = PaperCandidate(
            title="A Survey of Engineering Practices for LLMs",
            abstract="A survey with practical guidance.",
            url="https://example.com/survey-engineering",
            source="duckduckgo",
            source_id="web:5",
            document_kind="web",
            source_names=["duckduckgo"],
        )
        self.assertEqual(classify_web_source(candidate), "survey_support")


class IsUsefulWebSourceTests(unittest.TestCase):
    def test_paper_is_never_useful_web(self) -> None:
        candidate = PaperCandidate(
            title="Paper",
            abstract="abstract",
            url="https://example.com",
            source="openalex",
            source_id="oa:1",
            document_kind="paper",
            score=0.8,
            source_names=["openalex"],
        )
        self.assertFalse(is_useful_web_source(candidate))

    def test_web_with_full_text_is_useful(self) -> None:
        candidate = PaperCandidate(
            title="Tutorial",
            abstract="abstract",
            url="https://example.com",
            source="duckduckgo",
            source_id="web:1",
            document_kind="web",
            score=0.05,
            full_text="lots of content",
            source_names=["duckduckgo"],
        )
        self.assertTrue(is_useful_web_source(candidate))

    def test_web_with_high_score_is_useful(self) -> None:
        candidate = PaperCandidate(
            title="Blog Post",
            abstract="abstract",
            url="https://example.com",
            source="duckduckgo",
            source_id="web:2",
            document_kind="web",
            score=0.25,
            source_names=["duckduckgo"],
        )
        self.assertTrue(is_useful_web_source(candidate))

    def test_engineering_explainer_with_lower_score_still_useful(self) -> None:
        candidate = PaperCandidate(
            title="Getting Started with Transformers",
            abstract="A tutorial.",
            url="https://huggingface.co/blog/transformers",
            source="duckduckgo",
            source_id="web:3",
            document_kind="web",
            score=0.12,
            source_names=["duckduckgo"],
        )
        self.assertTrue(is_useful_web_source(candidate))

    def test_general_web_with_very_low_score_not_useful(self) -> None:
        candidate = PaperCandidate(
            title="Random Page",
            abstract="abstract",
            url="https://example.com",
            source="duckduckgo",
            source_id="web:4",
            document_kind="web",
            score=0.04,
            source_names=["duckduckgo"],
        )
        self.assertFalse(is_useful_web_source(candidate))


class CollectUsefulWebSourcesTests(unittest.TestCase):
    def test_collects_and_sorts_by_score(self) -> None:
        low = PaperCandidate(
            title="Low",
            abstract="abstract",
            url="https://example.com/low",
            source="duckduckgo",
            source_id="web:low",
            document_kind="web",
            score=0.20,
            source_names=["duckduckgo"],
        )
        high = PaperCandidate(
            title="High",
            abstract="abstract",
            url="https://example.com/high",
            source="duckduckgo",
            source_id="web:high",
            document_kind="web",
            score=0.40,
            source_names=["duckduckgo"],
        )
        paper = PaperCandidate(
            title="Paper",
            abstract="abstract",
            url="https://example.com/paper",
            source="openalex",
            source_id="oa:paper",
            document_kind="paper",
            score=0.90,
            source_names=["openalex"],
        )
        result = collect_useful_web_sources([low, high, paper])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].title, "High")
        self.assertEqual(result[1].title, "Low")

    def test_respects_limit(self) -> None:
        candidates = [
            PaperCandidate(
                title=f"Web {i}",
                abstract="abstract",
                url="https://example.com",
                source="duckduckgo",
                source_id=f"web:{i}",
                document_kind="web",
                score=0.30,
                source_names=["duckduckgo"],
            )
            for i in range(10)
        ]
        result = collect_useful_web_sources(candidates, limit=3)
        self.assertEqual(len(result), 3)


class GroupWebSourcesByCategoryTests(unittest.TestCase):
    def test_groups_by_category(self) -> None:
        survey = PaperCandidate(
            title="A Survey of LLM Techniques",
            abstract="overview",
            url="https://example.com/survey",
            source="duckduckgo",
            source_id="web:survey",
            document_kind="web",
            score=0.30,
            source_names=["duckduckgo"],
        )
        explainer = PaperCandidate(
            title="Getting Started with LLMs",
            abstract="tutorial",
            url="https://huggingface.co/blog/llms",
            source="duckduckgo",
            source_id="web:explainer",
            document_kind="web",
            score=0.25,
            source_names=["duckduckgo"],
        )
        general = PaperCandidate(
            title="Some Random Page",
            abstract="random",
            url="https://example.com/random",
            source="duckduckgo",
            source_id="web:general",
            document_kind="web",
            score=0.20,
            source_names=["duckduckgo"],
        )
        paper = PaperCandidate(
            title="A Paper",
            abstract="abstract",
            url="https://example.com/paper",
            source="openalex",
            source_id="oa:1",
            document_kind="paper",
            score=0.80,
            source_names=["openalex"],
        )
        groups = group_web_sources_by_category([survey, explainer, general, paper])
        self.assertNotIn("", groups)
        self.assertIn("survey_support", groups)
        self.assertIn("engineering_explainer", groups)
        self.assertIn("general_web", groups)
        self.assertEqual(len(groups["survey_support"]), 1)
        self.assertEqual(len(groups["engineering_explainer"]), 1)
        self.assertEqual(len(groups["general_web"]), 1)

    def test_category_labels_cover_all_categories(self) -> None:
        for cat in ("survey_support", "engineering_explainer", "general_web"):
            self.assertIn(cat, CATEGORY_LABELS)


class AssembleWebResultsTests(unittest.TestCase):
    def test_assemble_web_results_returns_useful_and_grouped_views(self) -> None:
        survey = PaperCandidate(
            title="A Survey of LLM Techniques",
            abstract="overview",
            url="https://example.com/survey",
            source="duckduckgo",
            source_id="web:survey",
            document_kind="web",
            score=0.30,
            source_names=["duckduckgo"],
        )
        explainer = PaperCandidate(
            title="Getting Started with LLMs",
            abstract="tutorial",
            url="https://huggingface.co/blog/llms",
            source="duckduckgo",
            source_id="web:explainer",
            document_kind="web",
            score=0.25,
            source_names=["duckduckgo"],
        )

        assembly = assemble_web_results([survey, explainer])

        self.assertIsInstance(assembly, WebResultAssembly)
        self.assertEqual([candidate.title for candidate in assembly.useful_sources], [survey.title, explainer.title])
        self.assertIn("survey_support", assembly.grouped_sources)
        self.assertIn("engineering_explainer", assembly.grouped_sources)


if __name__ == "__main__":
    unittest.main()
