from __future__ import annotations

from collections import Counter
from pathlib import Path

from research_lab.enrichment import enrich_candidates
from research_lab.final_ranking import finalize_ranking
from research_lab.identity import candidates_match
from research_lab.models import Candidate, QueryRecord, ResearchBrief, RunArtifacts
from research_lab.planner import build_expansion_queries, build_seed_queries
from research_lab.rank import dedupe_candidates, rank_candidates
from research_lab.report import write_run_files
from research_lab.retrieval import RetrievalPolicy
from research_lab.sources import HttpClient
from research_lab.store import init_db, record_run


class SearchSession:
    def __init__(self, brief: ResearchBrief, client: HttpClient | None = None) -> None:
        self.brief = brief
        self.client = client or HttpClient()
        self.retrieval = RetrievalPolicy(client=self.client, scholar_per_query=brief.scholar_per_query)
        self.queries: list[QueryRecord] = []
        self.pool: list[Candidate] = []
        self._seen_query_strings: set[str] = set()

    @property
    def warnings(self) -> list[str]:
        return self.retrieval.warnings

    def execute(self, run_id: str, run_dir: Path, db_path: Path, program_text: str) -> RunArtifacts:
        self._run_seed_queries()
        ranked = self._rank_pool()

        for iteration in range(1, self.brief.iterations + 1):
            ranked = self._run_expansion_iteration(ranked, iteration)

        final_ranking = self._finalize_ranking(ranked)
        artifacts = RunArtifacts.create(
            run_id=run_id,
            run_dir=str(run_dir),
            brief=self.brief,
            queries=self.queries,
            candidates=final_ranking.ranked,
            program_text=program_text,
            warnings=sorted(set(self.warnings)),
            synthesis=final_ranking.synthesis,
        )
        write_run_files(run_dir, artifacts)
        init_db(db_path)
        record_run(db_path, artifacts)
        return artifacts

    def _run_seed_queries(self) -> None:
        for query in build_seed_queries(self.brief):
            self._record_query(query)
            self.pool.extend(self.retrieval.search(query, self.brief))

    def _run_expansion_iteration(self, ranked: list[Candidate], iteration: int) -> list[Candidate]:
        seed_candidates = expansion_seed_candidates(ranked, self.brief)
        top_titles = [candidate.title for candidate in seed_candidates[:3]]
        top_authors = top_candidate_authors(seed_candidates)
        expanded_pool: list[Candidate] = []

        for query in build_expansion_queries(self.brief, top_titles, top_authors, iteration):
            if not self._record_query(query):
                continue
            expanded_pool.extend(self.retrieval.search(query, self.brief))

        for candidate in seed_candidates[:2]:
            expanded_pool.extend(self.retrieval.fetch_references(candidate, self.brief.per_query))

        if not expanded_pool:
            return ranked
        self.pool.extend(expanded_pool)
        return self._rank_pool()

    def _finalize_ranking(self, ranked: list[Candidate]):
        enriched, enrichment_warnings = enrich_candidates(ranked[: self.brief.full_text_top_n], self.brief, self.client)
        self.warnings.extend(enrichment_warnings)
        self.pool.extend(enriched)
        deduped_pool = dedupe_candidates(self.pool)
        reranked = rank_candidates(deduped_pool, self.brief)
        final_ranked = merge_scored_candidates(reranked, deduped_pool)
        return finalize_ranking(final_ranked, self.brief, self.warnings)

    def _rank_pool(self) -> list[Candidate]:
        return rank_candidates(dedupe_candidates(self.pool), self.brief)

    def _record_query(self, query: QueryRecord) -> bool:
        lowered = query.query.lower()
        if lowered in self._seen_query_strings:
            return False
        self._seen_query_strings.add(lowered)
        self.queries.append(query)
        return True


def top_candidate_authors(candidates: list[Candidate]) -> list[str]:
    counts = Counter(author for candidate in candidates for author in candidate.authors[:3] if author)
    return [author for author, _ in counts.most_common(3)]


def merge_scored_candidates(ranked: list[Candidate], pool: list[Candidate]) -> list[Candidate]:
    merged: list[Candidate] = []
    used_indices: set[int] = set()
    for scored_candidate in ranked:
        for index, candidate in enumerate(pool):
            if index in used_indices:
                continue
            if not candidates_match(scored_candidate, candidate):
                continue
            candidate.score = scored_candidate.score
            candidate.reasons = list(scored_candidate.reasons)
            candidate.flags = list(scored_candidate.flags)
            merged.append(candidate)
            used_indices.add(index)
            break
    return merged


def expansion_seed_candidates(ranked: list[Candidate], brief: ResearchBrief) -> list[Candidate]:
    required_hits = 0
    if brief.must_include:
        required_hits = 1 if len(brief.must_include) <= 2 else 2

    filtered = [
        candidate
        for candidate in ranked
        if candidate.document_kind == "paper"
        and candidate.score >= 0.45
        and must_include_hits(candidate, brief) >= required_hits
        and not any(flag in {"drift", "weak_title"} for flag in candidate.flags)
    ]
    if filtered:
        return filtered[:3]

    papers = [candidate for candidate in ranked if candidate.document_kind == "paper"]
    if papers:
        return papers[:3]
    return ranked[:3]


def must_include_hits(candidate: Candidate, brief: ResearchBrief) -> int:
    searchable_text = f"{candidate.title} {candidate.abstract} {candidate.snippet}".lower()
    return sum(1 for term in brief.must_include if term.lower() in searchable_text)
