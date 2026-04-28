from __future__ import annotations

from collections import Counter
from pathlib import Path

from research_lab.models import PaperCandidate, QueryRecord, ResearchBrief, RunArtifacts
from research_lab.planner import build_expansion_queries, build_seed_queries
from research_lab.rank import dedupe_candidates, extract_evidence_sentences, rank_candidates
from research_lab.report import write_run_files
from research_lab.sources import (
    HttpClient,
    SourceError,
    fetch_candidate_full_text,
    fetch_semantic_scholar_references,
    search_duckduckgo,
    search_openalex,
    search_semantic_scholar,
)
from research_lab.store import init_db, record_run


def execute_run(
    brief: ResearchBrief,
    program_text: str,
    run_id: str,
    run_dir: Path,
    db_path: Path,
) -> RunArtifacts:
    client = HttpClient()
    all_queries: list[QueryRecord] = []
    seen_query_strings: set[str] = set()
    pool: list[PaperCandidate] = []
    warnings: list[str] = []

    seed_queries = build_seed_queries(brief)
    for query in seed_queries:
        _add_query(query, all_queries, seen_query_strings)
        pool.extend(_search_all_sources(query, brief, client, warnings))

    ranked = rank_candidates(dedupe_candidates(pool), brief)

    for iteration in range(1, brief.iterations + 1):
        top_titles = [candidate.title for candidate in ranked[:3]]
        top_authors = _top_authors(ranked[:5])
        expansion_queries = build_expansion_queries(brief, top_titles, top_authors, iteration)

        expanded_pool: list[PaperCandidate] = []
        for query in expansion_queries:
            if not _add_query(query, all_queries, seen_query_strings):
                continue
            expanded_pool.extend(_search_all_sources(query, brief, client, warnings))

        for candidate in ranked[:3]:
            if candidate.source_id and candidate.source.startswith("semanticscholar"):
                try:
                    references = fetch_semantic_scholar_references(candidate.source_id, brief.per_query, client)
                except SourceError as exc:
                    warnings.append(str(exc))
                    references = []
                for reference in references:
                    reference.matched_queries.append(f"references:{candidate.title}")
                    expanded_pool.append(reference)

        if not expanded_pool:
            continue
        pool.extend(expanded_pool)
        ranked = rank_candidates(dedupe_candidates(pool), brief)

    _enrich_top_candidates(ranked, brief, client, warnings)
    ranked = rank_candidates(dedupe_candidates(pool), brief)

    artifacts = RunArtifacts.create(
        run_id=run_id,
        run_dir=str(run_dir),
        brief=brief,
        queries=all_queries,
        candidates=ranked,
        program_text=program_text,
        warnings=sorted(set(warnings)),
    )
    write_run_files(run_dir, artifacts)
    init_db(db_path)
    record_run(db_path, artifacts)
    return artifacts


def _search_all_sources(
    query: QueryRecord,
    brief: ResearchBrief,
    client: HttpClient,
    warnings: list[str],
) -> list[PaperCandidate]:
    collected: list[PaperCandidate] = []
    try:
        openalex_results = search_openalex(query.query, brief.per_query, brief.since_year, client)
        for candidate in openalex_results:
            candidate.matched_queries.append(query.query)
        collected.extend(openalex_results)
    except SourceError as exc:
        warnings.append(str(exc))
    try:
        semantic_results = search_semantic_scholar(query.query, brief.per_query, brief.since_year, client)
        for candidate in semantic_results:
            candidate.matched_queries.append(query.query)
        collected.extend(semantic_results)
    except SourceError as exc:
        warnings.append(str(exc))
    try:
        web_results = search_duckduckgo(query.query, brief.web_per_query, client)
        for candidate in web_results:
            candidate.matched_queries.append(query.query)
        collected.extend(web_results)
    except SourceError as exc:
        warnings.append(str(exc))
    return collected


def _add_query(query: QueryRecord, all_queries: list[QueryRecord], seen: set[str]) -> bool:
    lowered = query.query.lower()
    if lowered in seen:
        return False
    seen.add(lowered)
    all_queries.append(query)
    return True


def _top_authors(candidates: list[PaperCandidate]) -> list[str]:
    counts = Counter(author for candidate in candidates for author in candidate.authors[:3] if author)
    return [author for author, _ in counts.most_common(3)]


def _enrich_top_candidates(
    ranked: list[PaperCandidate],
    brief: ResearchBrief,
    client: HttpClient,
    warnings: list[str],
) -> None:
    for candidate in ranked[: brief.full_text_top_n]:
        if candidate.full_text:
            continue
        try:
            full_text, full_text_source = fetch_candidate_full_text(candidate, client)
        except SourceError as exc:
            warnings.append(str(exc))
            continue
        candidate.full_text = full_text
        candidate.full_text_source = full_text_source
        candidate.evidence = extract_evidence_sentences(full_text, brief)
