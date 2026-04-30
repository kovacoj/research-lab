from __future__ import annotations

import json
from pathlib import Path

from research_lab.enrichment import needs_user_article
from research_lab.models import PaperCandidate, RunArtifacts
from research_lab.web_result import CATEGORY_LABELS, collect_useful_web_sources, group_web_sources_by_category


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def bibtex_key(candidate: PaperCandidate) -> str:
    first_author = "unknown"
    if candidate.authors:
        first_author = candidate.authors[0].split()[-1].lower()
    year = str(candidate.year or "xxxx")
    title_word = "paper"
    for word in candidate.title.split():
        cleaned = "".join(ch for ch in word.lower() if ch.isalnum())
        if cleaned:
            title_word = cleaned
            break
    return f"{first_author}{year}{title_word}"


def candidate_to_bibtex(candidate: PaperCandidate) -> str:
    fields = [
        f"  title = {{{candidate.title}}}",
        f"  author = {{{' and '.join(candidate.authors)}}}",
        f"  year = {{{candidate.year or ''}}}",
    ]
    if candidate.venue:
        fields.append(f"  journal = {{{candidate.venue}}}")
    if candidate.doi:
        fields.append(f"  doi = {{{candidate.doi}}}")
    if candidate.url:
        fields.append(f"  url = {{{candidate.url}}}")
    return "@article{" + bibtex_key(candidate) + ",\n" + ",\n".join(fields) + "\n}\n"


def write_run_files(run_dir: Path, artifacts: RunArtifacts) -> None:
    write_json(run_dir / "brief.json", artifacts.brief.to_dict())
    write_json(run_dir / "queries.json", [query.to_dict() for query in artifacts.queries])
    write_json(run_dir / "candidates.json", [candidate.to_dict() for candidate in artifacts.candidates])

    bib = "\n".join(candidate_to_bibtex(candidate) for candidate in artifacts.candidates[: artifacts.brief.top_k])
    (run_dir / "references.bib").write_text(bib, encoding="utf-8")

    top = artifacts.candidates[: artifacts.brief.top_k]
    high_confidence = [candidate for candidate in top if candidate.score >= 0.35]
    exploratory = [candidate for candidate in top if candidate.score < 0.35]
    requested_articles = [candidate for candidate in top if needs_user_article(candidate)]
    broad_intent_matches = [candidate for candidate in top if _matches_broad_intent(candidate)]
    useful_web_sources = collect_useful_web_sources(artifacts.candidates)
    web_groups = group_web_sources_by_category(useful_web_sources)

    lines: list[str] = [
        f"# Research Run {artifacts.run_id}",
        "",
        "## Topic",
        artifacts.brief.topic,
        "",
        "## Context",
        artifacts.brief.context.strip() or "(none)",
        "",
        "## Queries Tried",
    ]
    lines.extend(f"- [{query.origin}] {query.query}" for query in artifacts.queries)
    if artifacts.warnings:
        lines.extend(["", "## Retrieval Warnings"])
        lines.extend(f"- {warning}" for warning in artifacts.warnings[:20])
    if artifacts.synthesis:
        lines.extend(["", "## LLM Synthesis", artifacts.synthesis])
    if broad_intent_matches:
        lines.extend(["", "## Broad Coverage Matches"])
        for candidate in broad_intent_matches[:4]:
            lines.extend(_render_candidate(candidate))
    if useful_web_sources:
        lines.extend(["", "## Useful Web Sources"])
        for category in ("survey_support", "engineering_explainer", "general_web"):
            group = web_groups.get(category, [])
            if not group:
                continue
            label = CATEGORY_LABELS.get(category, category)
            lines.extend(["", f"### {label}"])
            for candidate in group[:4]:
                lines.extend(_render_candidate(candidate))
    lines.extend(["", "## High Confidence Matches"])
    if high_confidence:
        for candidate in high_confidence:
            lines.extend(_render_candidate(candidate))
    else:
        lines.append("- No candidates crossed the high-confidence threshold.")

    lines.extend(["", "## Requested Articles From User"])
    if requested_articles:
        for candidate in requested_articles[:5]:
            lines.extend(_render_article_request(candidate))
    else:
        lines.append("- No paywalled or abstract-only papers need user retrieval in this run.")

    lines.extend(["", "## Lower Confidence Leads"])
    if exploratory:
        for candidate in exploratory[:10]:
            lines.extend(_render_candidate(candidate))
    else:
        lines.append("- No lower-confidence leads were retained.")

    lines.extend(
        [
            "",
            "## Gaps And Next Angles",
            "- Check whether the top papers cluster around one subproblem and miss adjacent domains.",
            "- Review the lower-confidence list for survey papers or benchmark papers worth targeted follow-up.",
            "- If the results look too broad, tighten `must_include` or `since_year` in the next run.",
            "",
            "## Program",
            "```markdown",
            artifacts.program_text.rstrip(),
            "```",
        ]
    )

    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _render_candidate(candidate: PaperCandidate) -> list[str]:
    lines = [f"- [{candidate.title}]({candidate.url or candidate.open_access_url or '#'})"]
    meta = []
    if candidate.year:
        meta.append(str(candidate.year))
    if candidate.venue:
        meta.append(candidate.venue)
    if candidate.authors:
        meta.append(", ".join(candidate.authors[:3]))
    meta.append(candidate.document_kind)
    if candidate.access_status and not candidate.full_text:
        meta.append(f"access={candidate.access_status}")
    meta.append(f"score={candidate.score:.4f}")
    lines.append(f"  - {' | '.join(meta)}")
    if candidate.reasons:
        lines.append(f"  - why: {', '.join(candidate.reasons[:4])}")
    if candidate.llm_reasons:
        lines.append(f"  - llm: {', '.join(candidate.llm_reasons[:3])}")
    if candidate.evidence:
        lines.append(f"  - evidence: {' | '.join(candidate.evidence[:2])}")
    summary_source = candidate.abstract or candidate.snippet or candidate.full_text
    if summary_source:
        summary = summary_source.replace("\n", " ").strip()
        if len(summary) > 280:
            summary = summary[:277] + "..."
        label = "abstract" if candidate.abstract else "summary"
        lines.append(f"  - {label}: {summary}")
    return lines


def _matches_broad_intent(candidate: PaperCandidate) -> bool:
    broad_intent_flags = {
        "survey_intent",
        "benchmark_intent",
        "foundational_intent",
    }
    return any(flag in broad_intent_flags for flag in candidate.flags)


def _render_article_request(candidate: PaperCandidate) -> list[str]:
    lines = [f"- [{candidate.title}]({candidate.access_url or candidate.url or candidate.open_access_url or '#'})"]
    meta = []
    if candidate.year:
        meta.append(str(candidate.year))
    if candidate.venue:
        meta.append(candidate.venue)
    if candidate.doi:
        meta.append(f"doi={candidate.doi}")
    if candidate.access_status:
        meta.append(f"access={candidate.access_status}")
    if meta:
        lines.append(f"  - {' | '.join(meta)}")
    lines.append("  - why request: the run could only reach a blocked, thin, or unreadable page, so your university access could unlock full-text evidence.")
    if candidate.reasons:
        lines.append(f"  - relevance: {', '.join(candidate.reasons[:4])}")
    return lines
