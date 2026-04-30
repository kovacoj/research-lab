from __future__ import annotations

from dataclasses import dataclass

from research_lab.llm import LlmClient, LlmError, rerank_candidates_with_llm, summarize_candidates_with_llm
from research_lab.models import EnrichedCandidate, ResearchBrief


@dataclass(slots=True)
class FinalRanking:
    ranked: list[EnrichedCandidate]
    high_confidence: list[EnrichedCandidate]
    exploratory: list[EnrichedCandidate]
    broad_intent: list[EnrichedCandidate]
    synthesis: str = ""


def finalize_ranking(
    candidates: list[EnrichedCandidate],
    brief: ResearchBrief,
    warnings: list[str],
) -> FinalRanking:
    ranked = list(candidates)
    synthesis = _apply_llm_layer(ranked, brief, warnings)
    _sort_candidates(ranked)
    ranking = group_final_ranking(ranked, brief)
    ranking.synthesis = synthesis
    return ranking


def group_final_ranking(candidates: list[EnrichedCandidate], brief: ResearchBrief) -> FinalRanking:
    ranked = list(candidates)
    _sort_candidates(ranked)
    top = ranked[: brief.top_k]
    return FinalRanking(
        ranked=ranked,
        high_confidence=[candidate for candidate in top if candidate.score >= 0.35],
        exploratory=[candidate for candidate in top if candidate.score < 0.35],
        broad_intent=[candidate for candidate in top if is_broad_intent_match(candidate)],
    )


def is_broad_intent_match(candidate: EnrichedCandidate) -> bool:
    return any(flag in {"survey_intent", "benchmark_intent", "foundational_intent"} for flag in candidate.flags)


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
            _sort_candidates(ranked)
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


def _sort_candidates(candidates: list[EnrichedCandidate]) -> None:
    candidates.sort(key=lambda item: (item.score, item.citation_count, item.year or 0), reverse=True)
