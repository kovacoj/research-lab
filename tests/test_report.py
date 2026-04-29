from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.models import PaperCandidate, ResearchBrief, RunArtifacts
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


if __name__ == "__main__":
    unittest.main()
