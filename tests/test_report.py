from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.models import PaperCandidate, ResearchBrief, RunArtifacts
from research_lab.report_assembly import assemble_report
from research_lab.report import write_run_files


class ReportTests(unittest.TestCase):
    def test_write_run_files_includes_requested_articles_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            brief = ResearchBrief(topic="test-time adaptation", context="notes")
            candidate = PaperCandidate(
                title="Paywalled Adaptation Paper",
                abstract="A strong candidate with only abstract access.",
                url="https://example.com/paper",
                source="openalex",
                source_id="oa:paper",
                year=2024,
                venue="Journal of Testing",
                doi="10.1000/test",
                source_names=["openalex"],
                score=0.82,
                reasons=["topic overlap 3/3", "has abstract"],
                access_status="paywalled",
                access_url="https://example.com/paper",
            )
            artifacts = RunArtifacts.create("run-1", str(run_dir), brief, [], [candidate], "program")

            write_run_files(run_dir, artifacts)

            report = (run_dir / "report.md").read_text(encoding="utf-8")
            self.assertIn("## Requested Articles From User", report)
            self.assertIn("Paywalled Adaptation Paper", report)
            self.assertIn("why request", report)

    def test_write_run_files_requests_unreadable_high_score_paper(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            brief = ResearchBrief(topic="graph neural networks", context="notes")
            candidate = PaperCandidate(
                title="Unreadable But Relevant Paper",
                abstract="Strong metadata but no readable page.",
                url="https://example.com/paper",
                source="semanticscholar",
                source_id="s2:paper",
                year=2024,
                venue="Bioinformatics",
                source_names=["semanticscholar"],
                score=0.91,
                reasons=["topic overlap 4/4", "has abstract"],
                access_status="unreadable",
                access_url="https://example.com/paper",
            )
            artifacts = RunArtifacts.create("run-2", str(run_dir), brief, [], [candidate], "program")

            write_run_files(run_dir, artifacts)

            report = (run_dir / "report.md").read_text(encoding="utf-8")
            self.assertIn("Unreadable But Relevant Paper", report)
            self.assertIn("access=unreadable", report)

    def test_write_run_files_includes_broad_coverage_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            brief = ResearchBrief(topic="graph neural networks", context="I want strong surveys and foundational sources.")
            candidate = PaperCandidate(
                title="A compact review of graph neural networks",
                abstract="A survey article.",
                url="https://example.com/review",
                source="openalex",
                source_id="oa:review",
                year=2020,
                venue="Journal of Testing",
                source_names=["openalex"],
                score=0.88,
                reasons=["topic overlap 3/3", "matches survey intent", "matches foundational intent"],
                flags=["survey_intent", "foundational_intent"],
            )
            artifacts = RunArtifacts.create("run-3", str(run_dir), brief, [], [candidate], "program")

            write_run_files(run_dir, artifacts)

            report = (run_dir / "report.md").read_text(encoding="utf-8")
            self.assertIn("## Broad Coverage Matches", report)
            self.assertIn("A compact review of graph neural networks", report)

    def test_write_run_files_includes_useful_web_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            brief = ResearchBrief(topic="ai agents", context="include useful engineering explainers")
            candidate = PaperCandidate(
                title="Agentic Engineering Explained",
                abstract="A practical engineering explainer.",
                url="https://example.com/blog",
                source="duckduckgo",
                source_id="web:blog",
                venue="example.com",
                document_kind="web",
                source_names=["duckduckgo"],
                score=0.44,
                reasons=["topic overlap 2/3", "context overlap 1/4"],
            )
            artifacts = RunArtifacts.create("run-4", str(run_dir), brief, [], [candidate], "program")

            write_run_files(run_dir, artifacts)

            report = (run_dir / "report.md").read_text(encoding="utf-8")
            self.assertIn("## Useful Web Sources", report)
            self.assertIn("Agentic Engineering Explained", report)
            self.assertIn("### ", report)

    def test_assemble_report_groups_results(self) -> None:
        brief = ResearchBrief(topic="graph neural networks", context="I want strong surveys.", top_k=3)
        survey = PaperCandidate(
            title="A compact review of graph neural networks",
            abstract="A survey article.",
            url="https://example.com/review",
            source="openalex",
            source_id="oa:review",
            score=0.88,
            flags=["survey_intent"],
        )
        web = PaperCandidate(
            title="Agentic Engineering Explained",
            abstract="A practical engineering explainer.",
            url="https://example.com/blog",
            source="duckduckgo",
            source_id="web:blog",
            document_kind="web",
            score=0.44,
        )
        artifacts = RunArtifacts.create("run-5", "run-5", brief, [], [survey, web], "program")

        assembly = assemble_report(artifacts)

        self.assertEqual([candidate.title for candidate in assembly.broad_intent_matches], [survey.title])
        self.assertIn("engineering_explainer", assembly.useful_web_groups)


if __name__ == "__main__":
    unittest.main()
