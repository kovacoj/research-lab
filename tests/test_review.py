from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.models import PaperCandidate, ResearchBrief
from research_lab.review import compare_runs, write_review_markdown
from research_lab.report import write_json
from research_lab.run_history import find_previous_run_ref, load_run_snapshot
from research_lab.store import init_db, record_run
from research_lab.models import RunArtifacts


class ReviewTests(unittest.TestCase):
    def test_compare_runs_reports_new_and_dropped_candidates(self) -> None:
        brief = ResearchBrief(topic="alignment for language models", context="notes")
        baseline = _snapshot(
            "run-a",
            brief,
            [
                _candidate("Paper One", 0.7, doi="10.1/one"),
                _candidate("Paper Two", 0.6),
            ],
        )
        current = _snapshot(
            "run-b",
            brief,
            [
                _candidate("Paper One", 0.9, doi="10.1/one"),
                _candidate("Paper Three", 0.8),
            ],
        )

        result = compare_runs(current, baseline, top_k=5)

        self.assertEqual(len(result.overlap), 1)
        self.assertEqual(result.new_candidates[0].title, "Paper Three")
        self.assertEqual(result.dropped_candidates[0].title, "Paper Two")
        self.assertEqual(result.improved_candidates[0][0].title, "Paper One")

    def test_find_previous_run_ref_uses_same_topic_from_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir)
            init_db(runs_dir / "index.sqlite3")
            brief = ResearchBrief(topic="alignment for language models", context="notes")
            older_dir = runs_dir / "20260101-000000-alignment"
            older_dir.mkdir()
            newer_dir = runs_dir / "20260102-000000-alignment"
            newer_dir.mkdir()
            other_dir = runs_dir / "20260103-000000-different"
            other_dir.mkdir()

            older = RunArtifacts.create("20260101-000000-alignment", str(older_dir), brief, [], [_candidate("Old", 0.4)], "program")
            newer = RunArtifacts.create("20260102-000000-alignment", str(newer_dir), brief, [], [_candidate("New", 0.5)], "program")
            different = RunArtifacts.create(
                "20260103-000000-different",
                str(other_dir),
                ResearchBrief(topic="different topic", context="notes"),
                [],
                [_candidate("Other", 0.3)],
                "program",
            )
            record_run(runs_dir / "index.sqlite3", older)
            record_run(runs_dir / "index.sqlite3", newer)
            record_run(runs_dir / "index.sqlite3", different)

            write_json(newer_dir / "brief.json", brief.to_dict())
            write_json(newer_dir / "candidates.json", [_candidate("New", 0.5).to_dict()])
            snapshot = load_run_snapshot(str(newer_dir), runs_dir)

            previous = find_previous_run_ref(snapshot, runs_dir)

            self.assertEqual(previous, "20260101-000000-alignment")

    def test_write_review_markdown_creates_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            brief = ResearchBrief(topic="alignment for language models", context="notes")
            baseline = _snapshot("run-a", brief, [_candidate("Paper One", 0.7)])
            current = _snapshot("run-b", brief, [_candidate("Paper One", 0.9)])
            result = compare_runs(current, baseline, top_k=5)

            output_path = Path(tmpdir) / "review.md"
            write_review_markdown(result, output_path, top_k=5)

            text = output_path.read_text(encoding="utf-8")
            self.assertIn("Run Review", text)
            self.assertIn("Improved Overlap", text)


def _candidate(title: str, score: float, doi: str = "") -> PaperCandidate:
    return PaperCandidate(
        title=title,
        abstract="abstract",
        url="https://example.com",
        source="openalex",
        source_id=title.lower().replace(" ", "-"),
        doi=doi,
        source_names=["openalex"],
        score=score,
    )


def _snapshot(run_id: str, brief: ResearchBrief, candidates: list[PaperCandidate]):
    return type("Snapshot", (), {"run_id": run_id, "run_dir": Path(run_id), "brief": brief, "candidates": candidates})()


if __name__ == "__main__":
    unittest.main()
