from __future__ import annotations

from datetime import datetime, timezone
import math
import re

from research_lab.enrichment import extract_evidence_sentences
from research_lab.identity import candidates_match, normalize_title
from research_lab.lex import STOPWORDS, tokenize
from research_lab.models import PaperCandidate, ResearchBrief, RetrievalCandidate, ScoredCandidate

VISUAL_TERMS = {"vision", "visual", "image", "images", "video", "clip"}
ROBOTICS_TERMS = {"robot", "robotic", "robotics", "manipulation", "embodied"}
BIOMED_TERMS = {"protein", "molecular", "biomedical", "medical", "drug", "clinical"}
TEXT_TERMS = {"language", "languages", "llm", "llms", "text", "nlp"}
SURVEY_TERMS = {"survey", "review", "overview"}
BENCHMARK_TERMS = {"benchmark", "benchmarking", "comparison", "comparative", "evaluation"}
def _to_paper_candidate(candidate: RetrievalCandidate | PaperCandidate) -> PaperCandidate:
    if isinstance(candidate, PaperCandidate):
        return candidate
    return candidate.to_paper_candidate()


def dedupe_candidates(candidates: list[RetrievalCandidate | PaperCandidate]) -> list[PaperCandidate]:
    merged: list[PaperCandidate] = []
    by_doi: dict[str, PaperCandidate] = {}
    by_title: dict[str, PaperCandidate] = {}
    for raw_candidate in candidates:
        candidate = _to_paper_candidate(raw_candidate)
        if not candidate.title:
            continue
        doi_key = candidate.doi.lower().strip() if candidate.doi else ""
        title_key = normalize_title(candidate.title)
        existing = None
        if doi_key:
            existing = by_doi.get(doi_key)
        if existing is None:
            existing = by_title.get(title_key)
        if existing is None:
            for prior in merged:
                if candidates_match(prior, candidate):
                    existing = prior
                    break
        if existing is None:
            merged.append(candidate)
            if doi_key:
                by_doi[doi_key] = candidate
            by_title[title_key] = candidate
            continue
        existing.source_names = sorted(set(existing.source_names + candidate.source_names))
        existing.matched_queries = sorted(set(existing.matched_queries + candidate.matched_queries))
        existing.authors = existing.authors or candidate.authors
        if not existing.doi and candidate.doi:
            existing.doi = candidate.doi
            by_doi[doi_key] = existing
        if not existing.abstract and candidate.abstract:
            existing.abstract = candidate.abstract
        if not existing.url and candidate.url:
            existing.url = candidate.url
        if not existing.open_access_url and candidate.open_access_url:
            existing.open_access_url = candidate.open_access_url
        if not existing.full_text and candidate.full_text:
            existing.full_text = candidate.full_text
            existing.full_text_source = candidate.full_text_source
        if not existing.access_status and candidate.access_status:
            existing.access_status = candidate.access_status
            existing.access_url = candidate.access_url
        if not existing.evidence and candidate.evidence:
            existing.evidence = list(candidate.evidence)
        if candidate.citation_count > existing.citation_count:
            existing.citation_count = candidate.citation_count
        if not existing.venue and candidate.venue:
            existing.venue = candidate.venue
        if not existing.year and candidate.year:
            existing.year = candidate.year
        existing.fields_of_study = sorted(set(existing.fields_of_study + candidate.fields_of_study))
        by_title[title_key] = existing
    return merged


def _keyword_set(text: str) -> set[str]:
    return {
        token
        for token in tokenize(text)
        if token not in STOPWORDS and len(token) > 2 and not token.isdigit()
    }


def _bigram_set(text: str) -> set[str]:
    tokens = [token for token in tokenize(text) if token not in STOPWORDS and len(token) > 2]
    return {f"{left} {right}" for left, right in zip(tokens, tokens[1:])}


def _topic_facets(topic: str) -> list[str]:
    parts = re.split(r"\b(?:for|with|using|via|towards|in|on)\b|[:;,]", topic, flags=re.IGNORECASE)
    facets = [normalize_title(part) for part in parts if normalize_title(part)]
    return facets or [normalize_title(topic)]


def _facet_coverage(text: str, facet: str) -> float:
    facet_terms = _keyword_set(facet)
    if not facet_terms:
        return 0.0
    text_terms = _keyword_set(text)
    return len(facet_terms & text_terms) / len(facet_terms)


def _expanded_terms(terms: set[str]) -> set[str]:
    expanded = set(terms)
    for term in list(terms):
        if "-" in term:
            expanded.update(part for part in term.split("-") if len(part) > 2)
    return expanded


def _domain_mismatch_penalty(topic_terms: set[str], text_terms: set[str]) -> tuple[float, list[str]]:
    topic_terms = _expanded_terms(topic_terms)
    text_terms = _expanded_terms(text_terms)
    penalty = 0.0
    reasons: list[str] = []
    if topic_terms & TEXT_TERMS:
        if text_terms & VISUAL_TERMS and not topic_terms & VISUAL_TERMS:
            penalty += 0.32
            reasons.append("visual modality drift")
        if text_terms & ROBOTICS_TERMS and not topic_terms & ROBOTICS_TERMS:
            penalty += 0.32
            reasons.append("robotics modality drift")
        if text_terms & BIOMED_TERMS and not topic_terms & BIOMED_TERMS:
            penalty += 0.06
            reasons.append("biomed modality drift")
    if topic_terms & VISUAL_TERMS and text_terms & BIOMED_TERMS and not topic_terms & BIOMED_TERMS:
        penalty += 0.05
        reasons.append("biomed modality drift")
    return penalty, reasons


def _context_intent_bonus(candidate: PaperCandidate, brief: ResearchBrief, searchable_lower: str) -> tuple[float, list[str], list[str]]:
    context = brief.context.lower()
    title_norm = normalize_title(candidate.title)
    bonus = 0.0
    reasons: list[str] = []
    flags: list[str] = []
    broad_intent_requested = any(term in context for term in SURVEY_TERMS | BENCHMARK_TERMS) or "foundational" in context

    if any(term in context for term in SURVEY_TERMS) and any(term in title_norm for term in SURVEY_TERMS):
        bonus += 0.18
        reasons.append("matches survey intent")
        flags.append("survey_intent")

    if any(term in context for term in BENCHMARK_TERMS) and any(term in searchable_lower for term in BENCHMARK_TERMS):
        bonus += 0.18
        reasons.append("matches benchmark intent")
        flags.append("benchmark_intent")

    if "foundational" in context and candidate.citation_count >= 100:
        bonus += 0.16
        reasons.append("matches foundational intent")
        flags.append("foundational_intent")

    exact_topic = normalize_title(brief.topic)
    has_broad_intent_signal = any(term in searchable_lower for term in SURVEY_TERMS | BENCHMARK_TERMS)
    if broad_intent_requested and exact_topic and exact_topic in title_norm and not has_broad_intent_signal and candidate.citation_count < 50:
        bonus -= 0.24
        reasons.append("narrow method match against broad intent")

    return bonus, reasons, flags


def _add_flag(flags: list[str], flag: str) -> None:
    if flag not in flags:
        flags.append(flag)


def score_candidate(candidate_view: RetrievalCandidate | PaperCandidate, brief: ResearchBrief) -> ScoredCandidate:
    candidate = _to_paper_candidate(candidate_view)
    topic_terms = _keyword_set(brief.topic)
    context_terms = _keyword_set(brief.context)
    title_terms = _keyword_set(candidate.title)
    abstract_terms = _keyword_set(candidate.abstract or candidate.snippet)
    full_text_terms = _keyword_set(candidate.full_text)
    text_terms = title_terms | abstract_terms | full_text_terms
    topic_bigrams = _bigram_set(brief.topic)
    text_bigrams = _bigram_set(f"{candidate.title} {candidate.abstract} {candidate.full_text}")
    topic_facets = _topic_facets(brief.topic)
    searchable_text = f"{candidate.title} {candidate.abstract} {candidate.snippet} {candidate.full_text}"
    searchable_norm = normalize_title(searchable_text)
    searchable_lower = searchable_text.lower()
    title_norm = normalize_title(candidate.title)

    score = 0.0
    reasons: list[str] = []
    flags: list[str] = []

    title_overlap = len(topic_terms & title_terms)
    body_overlap = len(topic_terms & (abstract_terms | full_text_terms))
    if topic_terms:
        title_ratio = title_overlap / len(topic_terms)
        body_ratio = body_overlap / len(topic_terms)
        score += title_ratio * 0.38
        score += body_ratio * 0.24
        topic_overlap = len(topic_terms & text_terms)
        if topic_overlap:
            reasons.append(f"topic overlap {topic_overlap}/{len(topic_terms)}")
        if title_overlap == len(topic_terms):
            reasons.append("covers all topic keywords")
        elif title_overlap == 0 and body_overlap > 0:
            score -= 0.12
            reasons.append("weak title alignment")
            _add_flag(flags, "weak_title")

    if topic_bigrams:
        bigram_overlap = len(topic_bigrams & text_bigrams)
        bigram_ratio = bigram_overlap / len(topic_bigrams)
        score += bigram_ratio * 0.12
        if bigram_overlap:
            reasons.append(f"phrase overlap {bigram_overlap}/{len(topic_bigrams)}")

    exact_topic = normalize_title(brief.topic)
    if exact_topic and exact_topic in title_norm:
        score += 0.18
        reasons.append("exact topic phrase in title")
    elif exact_topic and exact_topic in searchable_norm:
        score += 0.1
        reasons.append("exact topic phrase in text")

    if topic_facets:
        facet_coverages = [_facet_coverage(searchable_text, facet) for facet in topic_facets]
        covered_facets = sum(1 for coverage in facet_coverages if coverage >= 0.6)
        score += covered_facets / len(topic_facets) * 0.18
        if covered_facets and len(topic_facets) > 1:
            reasons.append(f"facet coverage {covered_facets}/{len(topic_facets)}")
        if len(topic_facets) > 1 and covered_facets < len(topic_facets):
            score -= (len(topic_facets) - covered_facets) * 0.04

    context_overlap = len(context_terms & text_terms)
    if context_terms:
        context_ratio = context_overlap / len(context_terms)
        score += min(context_ratio, 0.4) * 0.2
        if context_overlap:
            reasons.append(f"context overlap {context_overlap}/{len(context_terms)}")

    if candidate.abstract:
        score += 0.05
        reasons.append("has abstract")
    elif candidate.snippet:
        score += 0.02
        reasons.append("has snippet")

    if candidate.citation_count:
        citation_bonus = min(math.log10(candidate.citation_count + 1) / 15.0, 0.08)
        score += citation_bonus
        reasons.append(f"{candidate.citation_count} citations")

    if candidate.doi:
        score += 0.04
        reasons.append("has doi")
    if candidate.authors:
        score += 0.02
    if candidate.venue:
        score += 0.02

    if candidate.year:
        current_year = datetime.now(timezone.utc).year
        age = max(0, current_year - candidate.year)
        if age <= 3:
            score += 0.06
            reasons.append("recent")
        elif age <= 7:
            score += 0.03

    if len(candidate.source_names) > 1:
        score += 0.05
        reasons.append("seen in multiple sources")

    if candidate.document_kind == "paper":
        score += 0.08
    elif candidate.document_kind == "web" and candidate.full_text:
        score += 0.01
        reasons.append("web page read successfully")

    if candidate.document_kind == "web" and not candidate.doi and not candidate.authors and not candidate.year:
        score -= 0.08
        reasons.append("light metadata")

    if candidate.full_text:
        score += 0.03
        reasons.append("full text fetched")
    if candidate.evidence:
        score += min(len(candidate.evidence), 3) * 0.03
        reasons.append(f"{len(candidate.evidence)} evidence snippets")

    if title_norm and title_norm in normalize_title(brief.context):
        score -= 0.08
        reasons.append("already mentioned in context")

    if brief.must_include:
        include_hits = sum(1 for term in brief.must_include if term.lower() in searchable_lower)
        include_ratio = include_hits / len(brief.must_include)
        score += include_ratio * 0.24
        if include_hits:
            reasons.append(f"must-include coverage {include_hits}/{len(brief.must_include)}")
        if len(brief.must_include) >= 3 and include_hits <= 1:
            score -= 0.08
            reasons.append("weak must-include coverage")
        elif include_hits == 0:
            score -= 0.04
            reasons.append("misses must-include terms")

    for term in brief.must_exclude:
        if term.lower() in searchable_lower:
            score -= 0.2
            reasons.append(f"matches excluded term '{term}'")

    mismatch_penalty, mismatch_reasons = _domain_mismatch_penalty(topic_terms, text_terms)
    score -= mismatch_penalty
    reasons.extend(mismatch_reasons)
    if any("drift" in reason for reason in mismatch_reasons):
        _add_flag(flags, "drift")

    intent_bonus, intent_reasons, intent_flags = _context_intent_bonus(candidate, brief, searchable_lower)
    score += intent_bonus
    reasons.extend(intent_reasons)
    for flag in intent_flags:
        _add_flag(flags, flag)

    candidate.score = round(score, 4)
    candidate.reasons = reasons
    candidate.flags = flags
    return ScoredCandidate.from_paper_candidate(candidate)


def rank_candidates(candidates: list[RetrievalCandidate | PaperCandidate], brief: ResearchBrief) -> list[ScoredCandidate]:
    scored = [score_candidate(candidate, brief) for candidate in candidates]
    return sorted(scored, key=lambda item: (item.score, item.citation_count, item.year or 0), reverse=True)
