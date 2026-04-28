from argparse import Namespace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.cli import run_command
from research_lab.models import ResearchBrief


class _FakeUtcNow:
    def strftime(self, fmt: str) -> str:
        return "20260428-120000"


class _FakeDateTime:
    @staticmethod
    def utcnow() -> _FakeUtcNow:
        return _FakeUtcNow()


class CliTests(unittest.TestCase):
    def test_run_command_uses_brief_topic_for_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            brief_path = root / "brief.md"
            brief_path.write_text("# Topic\nMixed precision arithmetic\n", encoding="utf-8")
            program_path = root / "program.md"
            program_path.write_text("# Program\n", encoding="utf-8")
            runs_dir = root / "runs"

            args = Namespace(
                topic=None,
                brief_file=str(brief_path),
                brief_json=None,
                context_file=None,
                context="",
                domain=[],
                must_include=[],
                must_exclude=[],
                since_year=None,
                iterations=0,
                per_query=1,
                web_per_query=0,
                full_text_top_n=0,
                llm_rerank_top_n=0,
                llm_summary_top_n=0,
                top_k=1,
                program_file=str(program_path),
                runs_dir=str(runs_dir),
            )

            captured: dict[str, str] = {}

            def fake_execute_run(brief: ResearchBrief, program_text: str, run_id: str, run_dir: Path, db_path: Path):
                captured["run_id"] = run_id
                captured["run_dir"] = str(run_dir)
                return type("Artifacts", (), {"run_dir": str(run_dir), "candidates": []})()

            with patch("research_lab.cli.execute_run", side_effect=fake_execute_run), patch(
                "research_lab.cli.datetime", _FakeDateTime
            ):
                run_command(args)

            self.assertEqual(captured["run_id"], "20260428-120000-mixed-precision-arithmetic")
            self.assertTrue(captured["run_dir"].endswith("20260428-120000-mixed-precision-arithmetic"))


if __name__ == "__main__":
    unittest.main()
