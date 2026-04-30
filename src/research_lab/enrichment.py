from __future__ import annotations

import re

from dataclasses import dataclass

from research_lab.lex import STOPWORDS, tokenize
from research_lab.models import Candidate, ResearchBrief
from research_lab.sources.extraction import FullTextResult, fetch_candidate_full_text
from research_lab.sources.transport import HttpClient, SourceError


@dataclass(slots=True)
class EnrichmentResult:
    text: str
    source: str
    access_status: str
    access_url: str
    evidence: list[str]
    needs_user_article: bool


def needs_user_article(candidate: Candidate) -> bool:
    return (
        candidate.document_kind == "paper"
        and not candidate.full_text
        and candidate.access_status in {"paywalled", "abstract_only", "unreadable"}
        and candidate.score >= 0.45
    )


def _keyword_set(text: str) -> set[str]:
    return {
        token
        for token in tokenize(text)
        if token not in STOPWORDS and len(token) > 2 and not token.isdigit()
    }


def _trim_evidence_preamble(text: str, brief: ResearchBrief) -> str:
    from research_lab.identity import normalize_title

    lowered = text.lower()
    abstract_index = lowered.find("abstract")
    if 0 < abstract_index < 400:
        text = text[abstract_index:].strip()
        lowered = text.lower()

    topic_phrase = normalize_title(brief.topic)
    topic_index = lowered.find(topic_phrase)
    if topic_phrase and topic_index > 40:
        text = text[topic_index:].strip()

    topic_terms = _keyword_set(brief.topic)
    clauses = [clause.strip() for clause in re.split(r"(?<=[.:;])\s+", text) if clause.strip()]
    for clause in clauses:
        clause_terms = _keyword_set(clause)
        if len(topic_terms & clause_terms) >= 2 and re.search(
            r"\b(is|are|was|were|has|have|can|could|shows|show|improves|improve|uses|use|assists)\b",
            clause,
            flags=re.IGNORECASE,
        ):
            return _trim_to_claim_start(clause, brief)
        if clause.lower().startswith("abstract ") and len(topic_terms & clause_terms) >= 2:
            return _trim_to_claim_start(clause, brief)
    return _trim_to_claim_start(text, brief)


def _trim_to_claim_start(text: str, brief: ResearchBrief) -> str:
    from research_lab.identity import normalize_title

    topic_terms = [term for term in tokenize(brief.topic) if term not in STOPWORDS and len(term) > 2]
    phrases: list[str] = []
    for size in (3, 2):
        for index in range(len(topic_terms) - size + 1):
            phrases.append(" ".join(topic_terms[index : index + size]))
    seen_phrases: set[str] = set()
    for phrase in phrases:
        if phrase in seen_phrases:
            continue
        seen_phrases.add(phrase)
        matches = list(
            re.finditer(
                rf"\b{re.escape(phrase)}\b(?:(?![.!?]).){{0,80}}\b(is|are|was|were|has|have|can|could|shows|show|improves|improve|uses|use|assists)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        if matches:
            return text[matches[-1].start() :].strip()
    return text


def _has_claim_verb(text: str) -> bool:
    return re.search(
        r"\b(is|are|was|were|has|have|can|could|shows|show|improves|improve|uses|use|assists)\b",
        text,
        flags=re.IGNORECASE,
    ) is not None


def extract_evidence_sentences(text: str, brief: ResearchBrief, limit: int = 3) -> list[str]:
    from research_lab.identity import normalize_title

    topic_terms = _keyword_set(brief.topic)
    context_terms = _keyword_set(brief.context)
    must_include = {term.lower() for term in brief.must_include}
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    scored: list[tuple[float, str]] = []
    for sentence in sentences:
        cleaned = _trim_evidence_preamble(sentence.strip(), brief)
        if len(cleaned) < 40:
            continue
        if not _has_claim_verb(cleaned) and not cleaned.lower().startswith("abstract "):
            continue
        terms = _keyword_set(cleaned)
        if not terms:
            continue
        topic_overlap = len(topic_terms & terms)
        context_overlap = len(context_terms & terms)
        include_hits = sum(1 for term in must_include if term and term in cleaned.lower())
        if topic_overlap == 0 and context_overlap == 0 and include_hits == 0:
            continue
        phrase_bonus = 1 if normalize_title(brief.topic) and normalize_title(brief.topic) in normalize_title(cleaned) else 0
        score = topic_overlap * 2.0 + context_overlap + include_hits * 2.0 + phrase_bonus * 3.0
        scored.append((score, cleaned))
    scored.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    results: list[str] = []
    seen: set[str] = set()
    for _, sentence in scored:
        lowered = sentence.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        results.append(sentence)
        if len(results) >= limit:
            break
    return results


def enrich_candidate(
    candidate: Candidate,
    brief: ResearchBrief,
    client: HttpClient,
) -> EnrichmentResult:
    try:
        result = fetch_candidate_full_text(candidate, client)
    except SourceError:
        return EnrichmentResult(
            text="",
            source="",
            access_status="unreadable",
            access_url=candidate.url,
            evidence=[],
            needs_user_article=False,
        )

    evidence: list[str] = []
    if result.text:
        evidence = extract_evidence_sentences(result.text, brief)

    candidate.full_text = result.text
    candidate.full_text_source = result.source
    candidate.access_status = result.access_status
    candidate.access_url = result.access_url
    candidate.evidence = list(evidence)

    return EnrichmentResult(
        text=result.text,
        source=result.source,
        access_status=result.access_status,
        access_url=result.access_url,
        evidence=evidence,
        needs_user_article=needs_user_article(candidate),
    )


def enrich_candidates(
    candidates: list[Candidate],
    brief: ResearchBrief,
    client: HttpClient,
) -> tuple[list[Candidate], list[str]]:
    enriched: list[Candidate] = []
    warnings: list[str] = []
    for candidate in candidates:
        result = enrich_candidate(candidate, brief, client)
        enriched_candidate = Candidate(
            title=candidate.title,
            abstract=candidate.abstract,
            url=candidate.url,
            source=candidate.source,
            source_id=candidate.source_id,
            authors=list(candidate.authors),
            year=candidate.year,
            venue=candidate.venue,
            doi=candidate.doi,
            citation_count=candidate.citation_count,
            open_access_url=candidate.open_access_url,
            document_kind=candidate.document_kind,
            snippet=candidate.snippet,
            fields_of_study=list(candidate.fields_of_study),
            matched_queries=list(candidate.matched_queries),
            source_names=list(candidate.source_names),
            score=candidate.score,
            reasons=list(candidate.reasons),
            flags=list(candidate.flags),
            full_text=result.text,
            full_text_source=result.source,
            access_status=result.access_status,
            access_url=result.access_url,
            evidence=list(result.evidence),
        )
        if not result.text:
            if result.access_status == "unreadable":
                warnings.append(f"no readable content found for {enriched_candidate.title}")
            enriched.append(enriched_candidate)
            continue
        enriched.append(enriched_candidate)
    return enriched, warnings
