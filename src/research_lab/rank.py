from __future__ import annotations

from datetime import datetime, timezone
import math
import re

from research_lab.models import PaperCandidate, ResearchBrief
from research_lab.planner import STOPWORDS, tokenize

VISUAL_TERMS = {"vision", "visual", "image", "images", "video", "clip"}
ROBOTICS_TERMS = {"robot", "robotic", "robotics", "manipulation", "embodied"}
BIOMED_TERMS = {"protein", "molecular", "biomedical", "medical", "drug", "clinical"}
TEXT_TERMS = {"language", "languages", "llm", "llms", "text", "nlp"}


def normalize_title(title: str) -> str:
    lowered = title.lower()
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _titles_match_fuzzily(left: str, right: str) -> bool:
    left_norm = normalize_title(left)
    right_norm = normalize_title(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    shorter, longer = sorted([left_norm, right_norm], key=len)
    if len(shorter.split()) >= 5 and longer.startswith(shorter):
        return True
    left_terms = set(left_norm.split())
    right_terms = set(right_norm.split())
    overlap = len(left_terms & right_terms)
    minimum = min(len(left_terms), len(right_terms))
    return minimum >= 5 and overlap / minimum >= 0.8


def dedupe_candidates(candidates: list[PaperCandidate]) -> list[PaperCandidate]:
    merged: list[PaperCandidate] = []
    by_doi: dict[str, PaperCandidate] = {}
    by_title: dict[str, PaperCandidate] = {}
    for candidate in candidates:
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
                if _titles_match_fuzzily(prior.title, candidate.title):
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
            penalty += 0.18
            reasons.append("visual modality drift")
        if text_terms & ROBOTICS_TERMS and not topic_terms & ROBOTICS_TERMS:
            penalty += 0.18
            reasons.append("robotics modality drift")
        if text_terms & BIOMED_TERMS and not topic_terms & BIOMED_TERMS:
            penalty += 0.06
            reasons.append("biomed modality drift")
    if topic_terms & VISUAL_TERMS and text_terms & BIOMED_TERMS and not topic_terms & BIOMED_TERMS:
        penalty += 0.05
        reasons.append("biomed modality drift")
    return penalty, reasons


def extract_evidence_sentences(text: str, brief: ResearchBrief, limit: int = 3) -> list[str]:
    topic_terms = _keyword_set(brief.topic)
    context_terms = _keyword_set(brief.context)
    must_include = {term.lower() for term in brief.must_include}
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    scored: list[tuple[float, str]] = []
    for sentence in sentences:
        cleaned = sentence.strip()
        if len(cleaned) < 40:
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


def score_candidate(candidate: PaperCandidate, brief: ResearchBrief) -> float:
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

    candidate.score = round(score, 4)
    candidate.reasons = reasons
    return candidate.score


def rank_candidates(candidates: list[PaperCandidate], brief: ResearchBrief) -> list[PaperCandidate]:
    for candidate in candidates:
        score_candidate(candidate, brief)
    return sorted(candidates, key=lambda item: (item.score, item.citation_count, item.year or 0), reverse=True)
