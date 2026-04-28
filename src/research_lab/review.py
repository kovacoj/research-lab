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


@dataclass(slots=True)
class ReviewResult:
    current: RunSnapshot
    baseline: RunSnapshot
    overlap: list[tuple[PaperCandidate, PaperCandidate]]
    new_candidates: list[PaperCandidate]
    dropped_candidates: list[PaperCandidate]
    improved_candidates: list[tuple[PaperCandidate, PaperCandidate, float]]
    declined_candidates: list[tuple[PaperCandidate, PaperCandidate, float]]


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


def compare_runs(current: RunSnapshot, baseline: RunSnapshot, top_k: int) -> ReviewResult:
    current_top = current.candidates[:top_k]
    baseline_top = baseline.candidates[:top_k]

    overlap: list[tuple[PaperCandidate, PaperCandidate]] = []
    new_candidates: list[PaperCandidate] = []
    dropped_candidates: list[PaperCandidate] = []
    baseline_used: set[int] = set()

    for current_candidate in current_top:
        match_index = _find_matching_candidate_index(current_candidate, baseline_top, baseline_used)
        if match_index is None:
            new_candidates.append(current_candidate)
            continue
        baseline_used.add(match_index)
        overlap.append((current_candidate, baseline_top[match_index]))

    for index, baseline_candidate in enumerate(baseline_top):
        if index not in baseline_used:
            dropped_candidates.append(baseline_candidate)

    improved_candidates: list[tuple[PaperCandidate, PaperCandidate, float]] = []
    declined_candidates: list[tuple[PaperCandidate, PaperCandidate, float]] = []
    for current_candidate, baseline_candidate in overlap:
        delta = round(current_candidate.score - baseline_candidate.score, 4)
        if delta > 0:
            improved_candidates.append((current_candidate, baseline_candidate, delta))
        elif delta < 0:
            declined_candidates.append((current_candidate, baseline_candidate, delta))

    improved_candidates.sort(key=lambda item: item[2], reverse=True)
    declined_candidates.sort(key=lambda item: item[2])

    return ReviewResult(
        current=current,
        baseline=baseline,
        overlap=overlap,
        new_candidates=new_candidates,
        dropped_candidates=dropped_candidates,
        improved_candidates=improved_candidates,
        declined_candidates=declined_candidates,
    )


def write_review_markdown(result: ReviewResult, output_path: Path, top_k: int) -> None:
    lines = [
        f"# Run Review: {result.current.run_id}",
        "",
        f"Compared against `{result.baseline.run_id}`.",
        "",
        "## Summary",
        f"- topic: {result.current.brief.topic}",
        f"- top-k compared: {top_k}",
        f"- overlap: {len(result.overlap)}",
        f"- new in current: {len(result.new_candidates)}",
        f"- dropped from baseline: {len(result.dropped_candidates)}",
        f"- score improvements: {len(result.improved_candidates)}",
        f"- score declines: {len(result.declined_candidates)}",
        "",
        "## New Candidates",
    ]
    if result.new_candidates:
        lines.extend(_render_candidate_line(candidate) for candidate in result.new_candidates[:10])
    else:
        lines.append("- none")

    lines.extend(["", "## Dropped Candidates"])
    if result.dropped_candidates:
        lines.extend(_render_candidate_line(candidate) for candidate in result.dropped_candidates[:10])
    else:
        lines.append("- none")

    lines.extend(["", "## Improved Overlap"])
    if result.improved_candidates:
        for current_candidate, _, delta in result.improved_candidates[:10]:
            lines.append(f"- {current_candidate.title} (`+{delta:.4f}` to {current_candidate.score:.4f})")
    else:
        lines.append("- none")

    lines.extend(["", "## Declined Overlap"])
    if result.declined_candidates:
        for current_candidate, _, delta in result.declined_candidates[:10]:
            lines.append(f"- {current_candidate.title} (`{delta:.4f}` to {current_candidate.score:.4f})")
    else:
        lines.append("- none")

    lines.extend(["", "## Shared Candidates"])
    if result.overlap:
        for current_candidate, baseline_candidate in result.overlap[:10]:
            lines.append(
                f"- {current_candidate.title} (current `{current_candidate.score:.4f}` vs baseline `{baseline_candidate.score:.4f}`)"
            )
    else:
        lines.append("- none")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_json(path: Path) -> object:
    if not path.exists():
        raise ValueError(f"missing artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _find_matching_candidate_index(
    candidate: PaperCandidate,
    pool: list[PaperCandidate],
    used_indices: set[int],
) -> int | None:
    for index, existing in enumerate(pool):
        if index in used_indices:
            continue
        if _candidates_match(candidate, existing):
            return index
    return None


def _candidates_match(left: PaperCandidate, right: PaperCandidate) -> bool:
    if left.doi and right.doi and left.doi.lower() == right.doi.lower():
        return True
    left_title = _normalize_title(left.title)
    right_title = _normalize_title(right.title)
    if left_title == right_title:
        return True
    shorter, longer = sorted([left_title, right_title], key=len)
    if len(shorter.split()) >= 5 and longer.startswith(shorter):
        return True
    left_terms = set(left_title.split())
    right_terms = set(right_title.split())
    minimum = min(len(left_terms), len(right_terms))
    return minimum >= 5 and len(left_terms & right_terms) / minimum >= 0.8


def _normalize_title(title: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in title)
    return " ".join(cleaned.split())


def _render_candidate_line(candidate: PaperCandidate) -> str:
    year = candidate.year or "n/a"
    return f"- {candidate.title} (`{candidate.score:.4f}`, {year}, {candidate.document_kind})"
