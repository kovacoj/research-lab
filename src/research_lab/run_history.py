from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from research_lab.models import PaperCandidate, ResearchBrief


@dataclass(slots=True)
class RunSnapshot:
    run_id: str
    run_dir: Path
    brief: ResearchBrief
    candidates: list[PaperCandidate]


def load_run_snapshot(run_ref: str, runs_dir: Path) -> RunSnapshot:
    run_path = Path(run_ref)
    if not run_path.exists():
        run_path = runs_dir / run_ref
    if not run_path.exists() or not run_path.is_dir():
        raise ValueError(f"run not found: {run_ref}")

    brief = ResearchBrief.from_dict(_read_json(run_path / "brief.json"))
    candidates = [PaperCandidate.from_dict(item) for item in _read_json(run_path / "candidates.json")]
    return RunSnapshot(run_id=run_path.name, run_dir=run_path, brief=brief, candidates=candidates)


def find_previous_run_ref(current: RunSnapshot, runs_dir: Path) -> str | None:
    db_path = runs_dir / "index.sqlite3"
    if db_path.exists():
        connection = sqlite3.connect(db_path)
        try:
            row = connection.execute(
                """
                SELECT run_id
                FROM runs
                WHERE topic = ? AND run_id != ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (current.brief.topic, current.run_id),
            ).fetchone()
            if row:
                return str(row[0])
        finally:
            connection.close()

    sibling_runs = sorted(path.name for path in runs_dir.iterdir() if path.is_dir() and path.name != current.run_id)
    return sibling_runs[-1] if sibling_runs else None


def _read_json(path: Path) -> object:
    if not path.exists():
        raise ValueError(f"missing artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
