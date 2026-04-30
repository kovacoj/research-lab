from __future__ import annotations

from collections import Counter
from pathlib import Path

from research_lab.identity import candidates_match
from research_lab.llm import LlmClient, LlmError, rerank_candidates_with_llm, summarize_candidates_with_llm
from research_lab.models import EnrichedCandidate, PaperCandidate, QueryRecord, ResearchBrief, RetrievalCandidate, RunArtifacts, ScoredCandidate
from research_lab.planner import build_expansion_queries, build_seed_queries
from research_lab.rank import dedupe_candidates, extract_evidence_sentences, rank_candidates
from research_lab.report import write_run_files
from research_lab.retrieval import RetrievalPolicy
from research_lab.sources import HttpClient, SourceError, fetch_candidate_full_text
from research_lab.store import init_db, record_run


def execute_run(
    brief: ResearchBrief,
    program_text: str,
    run_id: str,
    run_dir: Path,
    db_path: Path,
) -> RunArtifacts:
    client = HttpClient()
    retrieval = RetrievalPolicy(client=client, scholar_per_query=brief.scholar_per_query)
    all_queries: list[QueryRecord] = []
    seen_query_strings: set[str] = set()
    pool: list[PaperCandidate | RetrievalCandidate] = []
    warnings: list[str] = retrieval.warnings

    seed_queries = build_seed_queries(brief)
    for query in seed_queries:
        _add_query(query, all_queries, seen_query_strings)
        pool.extend(retrieval.search(query, brief))

    ranked = rank_candidates(dedupe_candidates(pool), brief)

    for iteration in range(1, brief.iterations + 1):
        seed_candidates = _expansion_seed_candidates(ranked, brief)
        top_titles = [candidate.title for candidate in seed_candidates[:3]]
        top_authors = _top_authors(seed_candidates)
        expansion_queries = build_expansion_queries(brief, top_titles, top_authors, iteration)

        expanded_pool: list[PaperCandidate] = []
        for query in expansion_queries:
            if not _add_query(query, all_queries, seen_query_strings):
                continue
            expanded_pool.extend(retrieval.search(query, brief))

        for candidate in seed_candidates[:2]:
            expanded_pool.extend(retrieval.fetch_references(candidate, brief.per_query))

        if not expanded_pool:
            continue
        pool.extend(expanded_pool)
        ranked = rank_candidates(dedupe_candidates(pool), brief)

    enriched = _enrich_top_candidates(ranked[: brief.full_text_top_n], brief, client, warnings)
    pool.extend(candidate.to_paper_candidate() for candidate in enriched)
    deduped_pool = dedupe_candidates(pool)
    ranked = rank_candidates(deduped_pool, brief)
    final_ranked = [EnrichedCandidate.from_paper_candidate(candidate) for candidate in _merge_scored_candidates(ranked, deduped_pool)]
    synthesis = _apply_llm_layer(final_ranked, brief, warnings)

    artifacts = RunArtifacts.create(
        run_id=run_id,
        run_dir=str(run_dir),
        brief=brief,
        queries=all_queries,
        candidates=[candidate.to_paper_candidate() for candidate in final_ranked],
        program_text=program_text,
        warnings=sorted(set(warnings)),
        synthesis=synthesis,
    )
    write_run_files(run_dir, artifacts)
    init_db(db_path)
    record_run(db_path, artifacts)
    return artifacts


def _add_query(query: QueryRecord, all_queries: list[QueryRecord], seen: set[str]) -> bool:
    lowered = query.query.lower()
    if lowered in seen:
        return False
    seen.add(lowered)
    all_queries.append(query)
    return True


def _top_authors(candidates: list[ScoredCandidate]) -> list[str]:
    counts = Counter(author for candidate in candidates for author in candidate.authors[:3] if author)
    return [author for author, _ in counts.most_common(3)]


def _merge_scored_candidates(ranked: list[ScoredCandidate], pool: list[PaperCandidate]) -> list[PaperCandidate]:
    merged: list[PaperCandidate] = []
    used_indices: set[int] = set()
    for scored_candidate in ranked:
        for index, candidate in enumerate(pool):
            if index in used_indices:
                continue
            if not candidates_match(scored_candidate.to_paper_candidate(), candidate):
                continue
            candidate.score = scored_candidate.score
            candidate.reasons = list(scored_candidate.reasons)
            candidate.flags = list(scored_candidate.flags)
            merged.append(candidate)
            used_indices.add(index)
            break
    return merged


def _expansion_seed_candidates(ranked: list[ScoredCandidate], brief: ResearchBrief) -> list[ScoredCandidate]:
    required_hits = 0
    if brief.must_include:
        required_hits = 1 if len(brief.must_include) <= 2 else 2

    filtered = [
        candidate
        for candidate in ranked
        if candidate.document_kind == "paper"
        and candidate.score >= 0.45
        and _must_include_hits(candidate, brief) >= required_hits
        and not any(flag in {"drift", "weak_title"} for flag in candidate.flags)
    ]
    if filtered:
        return filtered[:3]

    papers = [candidate for candidate in ranked if candidate.document_kind == "paper"]
    if papers:
        return papers[:3]
    return ranked[:3]


def _must_include_hits(candidate: ScoredCandidate, brief: ResearchBrief) -> int:
    searchable_text = f"{candidate.title} {candidate.abstract} {candidate.snippet}".lower()
    return sum(1 for term in brief.must_include if term.lower() in searchable_text)


def _enrich_top_candidates(
    ranked: list[ScoredCandidate],
    brief: ResearchBrief,
    client: HttpClient,
    warnings: list[str],
) -> list[EnrichedCandidate]:
    enriched: list[EnrichedCandidate] = []
    for candidate in ranked:
        try:
            result = fetch_candidate_full_text(candidate, client)
        except SourceError as exc:
            warnings.append(str(exc))
            continue
        enriched_candidate = EnrichedCandidate.from_paper_candidate(candidate.to_paper_candidate())
        enriched_candidate.access_status = result.access_status
        enriched_candidate.access_url = result.access_url
        if not result.text:
            if result.access_status == "unreadable":
                warnings.append(f"no readable content found for {enriched_candidate.title}")
            enriched.append(enriched_candidate)
            continue
        enriched_candidate.full_text = result.text
        enriched_candidate.full_text_source = result.source
        enriched_candidate.evidence = extract_evidence_sentences(result.text, brief)
        enriched.append(enriched_candidate)
    return enriched


def _apply_llm_layer(ranked: list[EnrichedCandidate], brief: ResearchBrief, warnings: list[str]) -> str:
    client = LlmClient.from_env()
    if client is None:
        return ""

    rerank_targets = ranked[: brief.llm_rerank_top_n]
    if rerank_targets:
        try:
            reranked = rerank_candidates_with_llm(client, brief, rerank_targets)
            for index, candidate in enumerate(rerank_targets, start=1):
                candidate_id = f"c{index}"
                result = reranked.get(candidate_id)
                if result is None:
                    continue
                candidate.llm_score = result["score"]
                candidate.llm_reasons = result["reasons"]
                candidate.score = round(candidate.score + max(min(result["score"], 1.0), 0.0) * 0.25, 4)
            ranked.sort(key=lambda item: (item.score, item.citation_count, item.year or 0), reverse=True)
        except LlmError as exc:
            warnings.append(str(exc))

    summary_targets = ranked[: brief.llm_summary_top_n]
    if not summary_targets:
        return ""
    try:
        return summarize_candidates_with_llm(client, brief, summary_targets)
    except LlmError as exc:
        warnings.append(str(exc))
        return ""
