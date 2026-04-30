from __future__ import annotations

from dataclasses import dataclass

from research_lab.enrichment import needs_user_article
from research_lab.final_ranking import FinalRanking, group_final_ranking
from research_lab.models import Candidate, RunArtifacts
from research_lab.web_result import assemble_web_results


@dataclass(slots=True)
class ReportAssembly:
    top: list[Candidate]
    high_confidence: list[Candidate]
    exploratory: list[Candidate]
    broad_intent_matches: list[Candidate]
    requested_articles: list[Candidate]
    useful_web_groups: dict[str, list[Candidate]]


def assemble_report(artifacts: RunArtifacts) -> ReportAssembly:
    ranking = group_final_ranking(
        artifacts.candidates,
        artifacts.brief,
    )
    top = ranking.ranked[: artifacts.brief.top_k]
    web_results = assemble_web_results(artifacts.candidates)
    return ReportAssembly(
        top=top,
        high_confidence=ranking.high_confidence,
        exploratory=ranking.exploratory,
        broad_intent_matches=ranking.broad_intent,
        requested_articles=[candidate for candidate in top if needs_user_article(candidate)],
        useful_web_groups=web_results.grouped_sources,
    )
