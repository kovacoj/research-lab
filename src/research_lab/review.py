from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from research_lab.identity import candidates_match
from research_lab.models import PaperCandidate, ResearchBrief
from research_lab.run_history import RunSnapshot


@dataclass(slots=True)
class ReviewResult:
    current: RunSnapshot
    baseline: RunSnapshot
    overlap: list[tuple[PaperCandidate, PaperCandidate]]
    new_candidates: list[PaperCandidate]
    dropped_candidates: list[PaperCandidate]
    improved_candidates: list[tuple[PaperCandidate, PaperCandidate, float]]
    declined_candidates: list[tuple[PaperCandidate, PaperCandidate, float]]
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
def _find_matching_candidate_index(
    candidate: PaperCandidate,
    pool: list[PaperCandidate],
    used_indices: set[int],
) -> int | None:
    for index, existing in enumerate(pool):
        if index in used_indices:
            continue
        if candidates_match(candidate, existing):
            return index
    return None


def _render_candidate_line(candidate: PaperCandidate) -> str:
    year = candidate.year or "n/a"
    return f"- {candidate.title} (`{candidate.score:.4f}`, {year}, {candidate.document_kind})"
