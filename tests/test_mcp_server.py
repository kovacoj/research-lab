from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.briefs import load_brief_markdown
from research_lab.models import PaperCandidate, ResearchBrief, RunArtifacts
from research_lab_mcp.server import ResearchLabMcpServer


class _FakeUtcNow:
    def strftime(self, fmt: str) -> str:
        return "20260517-101500"


class _FakeDateTime:
    @staticmethod
    def utcnow() -> _FakeUtcNow:
        return _FakeUtcNow()


class McpServerTests(unittest.TestCase):
    def test_run_search_writes_under_workspace_research_runs_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            server = ResearchLabMcpServer(workspace)

            captured: dict[str, str] = {}

            def fake_execute_run(brief: ResearchBrief, program_text: str, run_id: str, run_dir: Path, db_path: Path):
                captured["topic"] = brief.topic
                captured["run_id"] = run_id
                captured["run_dir"] = str(run_dir)
                captured["db_path"] = str(db_path)
                (run_dir / "report.md").write_text("# Report\n", encoding="utf-8")
                (run_dir / "references.bib").write_text("@article{}\n", encoding="utf-8")
                return RunArtifacts.create(
                    run_id=run_id,
                    run_dir=str(run_dir),
                    brief=brief,
                    queries=[],
                    candidates=[_candidate("Paper One", 0.9)],
                    program_text=program_text,
                )

            with patch("research_lab_mcp.server.execute_run", side_effect=fake_execute_run), patch(
                "research_lab_mcp.server.datetime", _FakeDateTime
            ):
                result = server.run_search({"topic": "Demand-based pricing"})

            self.assertEqual(captured["topic"], "Demand-based pricing")
            self.assertTrue(captured["run_dir"].endswith("research/runs/20260517-101500-demand-based-pricing"))
            self.assertTrue(captured["db_path"].endswith("research/runs/index.sqlite3"))
            self.assertEqual(result["run_dir"], "research/runs/20260517-101500-demand-based-pricing")
            self.assertEqual(result["report_path"], "research/runs/20260517-101500-demand-based-pricing/report.md")

    def test_run_from_brief_rejects_workspace_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            server = ResearchLabMcpServer(workspace)

            with self.assertRaisesRegex(ValueError, "path must stay inside the workspace"):
                server.run_from_brief({"brief_path": "../outside.md"})

    def test_list_runs_returns_workspace_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            run_dir = workspace / "research" / "runs" / "20260517-101500-demand-based-pricing"
            run_dir.mkdir(parents=True)
            (run_dir / "brief.json").write_text(
                '{"topic": "Demand-based pricing", "context": "", "domains": [], "must_include": [], "must_exclude": [], "since_year": null, "iterations": 2, "per_query": 8, "web_per_query": 3, "scholar_per_query": 0, "full_text_top_n": 5, "llm_rerank_top_n": 8, "llm_summary_top_n": 5, "top_k": 20}\n',
                encoding="utf-8",
            )
            (run_dir / "report.md").write_text("# Report\n", encoding="utf-8")

            server = ResearchLabMcpServer(workspace)
            result = server.list_runs({})

            self.assertEqual(result["runs_dir"], "research/runs")
            self.assertEqual(result["runs"][0]["run_id"], "20260517-101500-demand-based-pricing")
            self.assertEqual(result["runs"][0]["report_path"], "research/runs/20260517-101500-demand-based-pricing/report.md")

    def test_create_brief_writes_parser_friendly_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            server = ResearchLabMcpServer(workspace)

            result = server.create_brief(
                {
                    "topic": "Demand-based pricing",
                    "context": "Use this for my thesis literature review.",
                    "domains": ["pricing", "B2B"],
                    "must_include": ["price elasticity"],
                    "output_path": "research/briefs/pricing.md",
                }
            )

            brief_path = workspace / "research" / "briefs" / "pricing.md"
            text = brief_path.read_text(encoding="utf-8")
            self.assertEqual(result["output_path"], "research/briefs/pricing.md")
            self.assertIn("# Topic", text)
            self.assertIn("## Must Include", text)
            parsed = load_brief_markdown(brief_path)
            self.assertEqual(parsed.topic, "Demand-based pricing")
            self.assertEqual(parsed.must_include, ["price elasticity"])

    def test_read_report_defaults_to_latest_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            older = workspace / "research" / "runs" / "20260517-101500-older"
            newer = workspace / "research" / "runs" / "20260517-101501-newer"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)
            (older / "report.md").write_text("older\n", encoding="utf-8")
            (newer / "report.md").write_text("newer\n", encoding="utf-8")

            server = ResearchLabMcpServer(workspace)
            result = server.read_report({})

            self.assertEqual(result["run_id"], "20260517-101501-newer")
            self.assertEqual(result["content"], "newer\n")

    def test_review_run_writes_review_for_requested_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            runs_dir = workspace / "research" / "runs"
            current_dir = runs_dir / "20260517-101501-current"
            baseline_dir = runs_dir / "20260517-101500-baseline"
            current_dir.mkdir(parents=True)
            baseline_dir.mkdir(parents=True)

            brief = ResearchBrief(topic="Demand-based pricing", context="notes")
            _write_run_files(current_dir, brief, [_candidate("Paper One", 0.9), _candidate("Paper Two", 0.8)])
            _write_run_files(baseline_dir, brief, [_candidate("Paper One", 0.7)])

            server = ResearchLabMcpServer(workspace)
            result = server.review_run({"run": "20260517-101501-current", "baseline": "20260517-101500-baseline"})

            review_path = current_dir / "review.md"
            self.assertEqual(result["output_path"], "research/runs/20260517-101501-current/review.md")
            self.assertTrue(review_path.exists())
            self.assertIn("Run Review", review_path.read_text(encoding="utf-8"))

    def test_review_run_rejects_output_path_outside_research_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            runs_dir = workspace / "research" / "runs"
            current_dir = runs_dir / "20260517-101501-current"
            baseline_dir = runs_dir / "20260517-101500-baseline"
            current_dir.mkdir(parents=True)
            baseline_dir.mkdir(parents=True)

            brief = ResearchBrief(topic="Demand-based pricing", context="notes")
            _write_run_files(current_dir, brief, [_candidate("Paper One", 0.9)])
            _write_run_files(baseline_dir, brief, [_candidate("Paper One", 0.7)])

            server = ResearchLabMcpServer(workspace)
            with self.assertRaisesRegex(ValueError, "workspace"):
                server.review_run(
                    {
                        "run": "20260517-101501-current",
                        "baseline": "20260517-101500-baseline",
                        "output_path": "../review.md",
                    }
                )


def _candidate(title: str, score: float) -> PaperCandidate:
    return PaperCandidate(
        title=title,
        abstract="abstract",
        url="https://example.com",
        source="openalex",
        source_id=title.lower().replace(" ", "-"),
        source_names=["openalex"],
        score=score,
    )


def _write_run_files(run_dir: Path, brief: ResearchBrief, candidates: list[PaperCandidate]) -> None:
    (run_dir / "brief.json").write_text(json_text(brief.to_dict()), encoding="utf-8")
    (run_dir / "candidates.json").write_text(json_text([candidate.to_dict() for candidate in candidates]), encoding="utf-8")


def json_text(payload: object) -> str:
    import json

    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"


if __name__ == "__main__":
    unittest.main()
