from __future__ import annotations

from pathlib import Path

from research_lab.models import ResearchBrief, RunArtifacts
from research_lab.search_session import SearchSession, expansion_seed_candidates


def execute_run(
    brief: ResearchBrief,
    program_text: str,
    run_id: str,
    run_dir: Path,
    db_path: Path,
) -> RunArtifacts:
    session = SearchSession(brief)
    return session.execute(run_id=run_id, run_dir=run_dir, db_path=db_path, program_text=program_text)


def _expansion_seed_candidates(ranked, brief: ResearchBrief):
    return expansion_seed_candidates(ranked, brief)
