from __future__ import annotations

from dataclasses import dataclass

from research_lab.enrichment import needs_user_article
from research_lab.final_ranking import FinalRanking, group_final_ranking
from research_lab.models import EnrichedCandidate, PaperCandidate, RunArtifacts
from research_lab.web_result import assemble_web_results


@dataclass(slots=True)
class ReportAssembly:
    top: list[PaperCandidate]
    high_confidence: list[PaperCandidate]
    exploratory: list[PaperCandidate]
    broad_intent_matches: list[PaperCandidate]
    requested_articles: list[PaperCandidate]
    useful_web_groups: dict[str, list[PaperCandidate]]


def assemble_report(artifacts: RunArtifacts) -> ReportAssembly:
    ranking = group_final_ranking(
        [EnrichedCandidate.from_paper_candidate(candidate) for candidate in artifacts.candidates],
        artifacts.brief,
    )
    top = _to_paper_candidates(ranking.ranked[: artifacts.brief.top_k])
    web_results = assemble_web_results(artifacts.candidates)
    return ReportAssembly(
        top=top,
        high_confidence=_to_paper_candidates(ranking.high_confidence),
        exploratory=_to_paper_candidates(ranking.exploratory),
        broad_intent_matches=_to_paper_candidates(ranking.broad_intent),
        requested_articles=[candidate for candidate in top if needs_user_article(candidate)],
        useful_web_groups=web_results.grouped_sources,
    )


def _to_paper_candidates(candidates: list[EnrichedCandidate]) -> list[PaperCandidate]:
    return [candidate.to_paper_candidate() for candidate in candidates]
