from __future__ import annotations

from collections import Counter
import os
from pathlib import Path

from research_lab.llm import LlmClient, LlmError, rerank_candidates_with_llm, summarize_candidates_with_llm
from research_lab.models import PaperCandidate, QueryRecord, ResearchBrief, RunArtifacts
from research_lab.planner import build_expansion_queries, build_seed_queries
from research_lab.rank import dedupe_candidates, extract_evidence_sentences, rank_candidates
from research_lab.report import write_run_files
from research_lab.sources import (
    HttpClient,
    SourceError,
    fetch_candidate_full_text,
    fetch_semantic_scholar_references,
    search_arxiv,
    search_duckduckgo,
    search_google_scholar,
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
    semantic_scholar_api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    all_queries: list[QueryRecord] = []
    seen_query_strings: set[str] = set()
    pool: list[PaperCandidate] = []
    warnings: list[str] = []
    source_state = {
        "arxiv_enabled": True,
        "arxiv_requests_remaining": 6,
        "semanticscholar_enabled": bool(semantic_scholar_api_key),
        "semanticscholar_has_api_key": bool(semantic_scholar_api_key),
        "semanticscholar_requests_remaining": 999 if semantic_scholar_api_key else 0,
        "googlescholar_enabled": brief.scholar_per_query > 0,
        "googlescholar_requests_remaining": 3 if brief.scholar_per_query > 0 else 0,
    }

    seed_queries = build_seed_queries(brief)
    for query in seed_queries:
        _add_query(query, all_queries, seen_query_strings)
        pool.extend(_search_all_sources(query, brief, client, warnings, source_state))

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
            expanded_pool.extend(_search_all_sources(query, brief, client, warnings, source_state))

        for candidate in seed_candidates[:2]:
            if _should_use_semantic_scholar(None, source_state) and candidate.source_id and candidate.source.startswith("semanticscholar"):
                try:
                    source_state["semanticscholar_requests_remaining"] -= 1
                    references = fetch_semantic_scholar_references(candidate.source_id, brief.per_query, client)
                except SourceError as exc:
                    _handle_semantic_scholar_error(exc, warnings, source_state)
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
    synthesis = _apply_llm_layer(ranked, brief, warnings)

    artifacts = RunArtifacts.create(
        run_id=run_id,
        run_dir=str(run_dir),
        brief=brief,
        queries=all_queries,
        candidates=ranked,
        program_text=program_text,
        warnings=sorted(set(warnings)),
        synthesis=synthesis,
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
    source_state: dict[str, object],
) -> list[PaperCandidate]:
    collected: list[PaperCandidate] = []
    if _should_use_arxiv(query, source_state):
        try:
            source_state["arxiv_requests_remaining"] -= 1
            arxiv_results = search_arxiv(query.query, brief.per_query, brief.since_year, client)
            for candidate in arxiv_results:
                candidate.matched_queries.append(query.query)
            collected.extend(arxiv_results)
        except SourceError as exc:
            _handle_arxiv_error(exc, warnings, source_state)
    try:
        openalex_results = search_openalex(query.query, brief.per_query, brief.since_year, client)
        for candidate in openalex_results:
            candidate.matched_queries.append(query.query)
        collected.extend(openalex_results)
    except SourceError as exc:
        warnings.append(str(exc))
    if _should_use_semantic_scholar(query, source_state):
        try:
            source_state["semanticscholar_requests_remaining"] -= 1
            semantic_results = search_semantic_scholar(query.query, brief.per_query, brief.since_year, client)
            for candidate in semantic_results:
                candidate.matched_queries.append(query.query)
            collected.extend(semantic_results)
        except SourceError as exc:
            _handle_semantic_scholar_error(exc, warnings, source_state)
    try:
        web_results = search_duckduckgo(query.query, brief.web_per_query, client)
        for candidate in web_results:
            candidate.matched_queries.append(query.query)
        collected.extend(web_results)
    except SourceError as exc:
        warnings.append(str(exc))
    if _should_use_google_scholar(query, source_state):
        try:
            source_state["googlescholar_requests_remaining"] -= 1
            scholar_results = search_google_scholar(query.query, brief.scholar_per_query, client)
            for candidate in scholar_results:
                candidate.matched_queries.append(query.query)
            collected.extend(scholar_results)
        except SourceError as exc:
            _handle_google_scholar_error(exc, warnings, source_state)
    return collected


def _handle_arxiv_error(exc: SourceError, warnings: list[str], source_state: dict[str, object]) -> None:
    message = str(exc)
    if "HTTP Error 429" in message or "timed out" in message:
        if source_state["arxiv_enabled"]:
            warnings.append("arxiv disabled after rate limit")
        source_state["arxiv_enabled"] = False
        return
    warnings.append(message)


def _handle_semantic_scholar_error(exc: SourceError, warnings: list[str], source_state: dict[str, object]) -> None:
    if "HTTP Error 429" in str(exc):
        if source_state["semanticscholar_enabled"]:
            warnings.append("semantic scholar disabled after rate limit")
        source_state["semanticscholar_enabled"] = False
        return
    warnings.append(str(exc))


def _handle_google_scholar_error(exc: SourceError, warnings: list[str], source_state: dict[str, object]) -> None:
    if "google scholar blocked automated access" in str(exc):
        if source_state["googlescholar_enabled"]:
            warnings.append("google scholar disabled after block")
        source_state["googlescholar_enabled"] = False
        return
    warnings.append(str(exc))


def _should_use_arxiv(query: QueryRecord, source_state: dict[str, object]) -> bool:
    if not source_state["arxiv_enabled"]:
        return False
    if int(source_state["arxiv_requests_remaining"]) <= 0:
        return False
    return query.origin not in {"author_expansion", "title_expansion"}


def _should_use_semantic_scholar(query: QueryRecord | None, source_state: dict[str, object]) -> bool:
    if not source_state["semanticscholar_enabled"]:
        return False
    if int(source_state["semanticscholar_requests_remaining"]) <= 0:
        return False
    if bool(source_state["semanticscholar_has_api_key"]):
        return True
    if query is None:
        return True
    return query.origin not in {"author_expansion", "title_expansion"}


def _should_use_google_scholar(query: QueryRecord, source_state: dict[str, object]) -> bool:
    if not source_state["googlescholar_enabled"]:
        return False
    if int(source_state["googlescholar_requests_remaining"]) <= 0:
        return False
    return query.origin not in {"author_expansion", "title_expansion"}


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


def _expansion_seed_candidates(ranked: list[PaperCandidate], brief: ResearchBrief) -> list[PaperCandidate]:
    required_hits = 0
    if brief.must_include:
        required_hits = 1 if len(brief.must_include) <= 2 else 2

    filtered = [
        candidate
        for candidate in ranked
        if candidate.document_kind == "paper"
        and candidate.score >= 0.45
        and _must_include_hits(candidate, brief) >= required_hits
        and not any("drift" in reason or "weak title alignment" == reason for reason in candidate.reasons)
    ]
    if filtered:
        return filtered[:3]

    papers = [candidate for candidate in ranked if candidate.document_kind == "paper"]
    if papers:
        return papers[:3]
    return ranked[:3]


def _must_include_hits(candidate: PaperCandidate, brief: ResearchBrief) -> int:
    searchable_text = f"{candidate.title} {candidate.abstract} {candidate.snippet} {candidate.full_text}".lower()
    return sum(1 for term in brief.must_include if term.lower() in searchable_text)


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
            result = fetch_candidate_full_text(candidate, client)
        except SourceError as exc:
            warnings.append(str(exc))
            continue
        candidate.access_status = result.access_status
        candidate.access_url = result.access_url
        if not result.text:
            if result.access_status == "unreadable":
                warnings.append(f"no readable content found for {candidate.title}")
            continue
        candidate.full_text = result.text
        candidate.full_text_source = result.source
        candidate.evidence = extract_evidence_sentences(result.text, brief)


def _apply_llm_layer(ranked: list[PaperCandidate], brief: ResearchBrief, warnings: list[str]) -> str:
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
