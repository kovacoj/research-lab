from __future__ import annotations

from research_lab.models import PaperCandidate


EXPLAINER_HOSTS = {
    "medium.com",
    "towardsdatascience.com",
    "towardsdatascience",
    "analyticsvidhya.com",
    "analyticsvidhya",
    "thegradient.pub",
    "thegradient",
    "lilianweng.github.io",
    "distill.pub",
    "distill",
    "huggingface.co",
    "huggingface",
    "pytorch.org",
    "tensorflow.org",
    "openai.com",
    "openai",
    "deepmind.com",
    "deepmind",
    "ai.googleblog.com",
    "ai.googleblog",
    "blog.google",
    "microsoft.com",
    "microsoft",
    "research.google",
    "arxiv.org",
    "arxiv",
}

ENGINEERING_PHRASES = {
    "tutorial",
    "how to",
    "getting started",
    "walkthrough",
    "guide",
    "cookbook",
    "implement",
    "implementation",
    "engineering",
    "explainer",
    "explained",
    "practical",
    "hands-on",
    "hands on",
}

SURVEY_SUPPORT_PHRASES = {
    "survey",
    "review",
    "overview",
    "comparison",
    "benchmark",
    "landscape",
    "state of the art",
    "state-of-the-art",
    "literature",
}


def _host_from_url(url: str) -> str:
    if not url:
        return ""
    netloc = url.removeprefix("https://").removeprefix("http://").split("/")[0]
    parts = netloc.split(".")
    if len(parts) >= 2:
        return parts[-2]
    return netloc


def _host_matches(url: str, hosts: set[str]) -> bool:
    host = _host_from_url(url)
    netloc = url.removeprefix("https://").removeprefix("http://").split("/")[0]
    return host in hosts or netloc in hosts


def classify_web_source(candidate: PaperCandidate) -> str:
    if candidate.document_kind != "web":
        return ""
    title_lower = candidate.title.lower()
    snippet_lower = (candidate.snippet or candidate.abstract or "").lower()
    searchable = f"{title_lower} {snippet_lower}"
    if any(phrase in searchable for phrase in SURVEY_SUPPORT_PHRASES):
        return "survey_support"
    if any(phrase in searchable for phrase in ENGINEERING_PHRASES):
        return "engineering_explainer"
    if _host_matches(candidate.url or candidate.open_access_url, EXPLAINER_HOSTS):
        return "engineering_explainer"
    return "general_web"


def is_useful_web_source(candidate: PaperCandidate) -> bool:
    if candidate.document_kind != "web":
        return False
    if candidate.full_text:
        return True
    if candidate.score >= 0.18:
        return True
    category = classify_web_source(candidate)
    if category in {"survey_support", "engineering_explainer"}:
        return candidate.score >= 0.10
    return candidate.score >= 0.18


def collect_useful_web_sources(candidates: list[PaperCandidate], limit: int = 6) -> list[PaperCandidate]:
    useful = [c for c in candidates if is_useful_web_source(c)]
    useful.sort(key=lambda c: c.score, reverse=True)
    return useful[:limit]


def group_web_sources_by_category(candidates: list[PaperCandidate]) -> dict[str, list[PaperCandidate]]:
    groups: dict[str, list[PaperCandidate]] = {}
    for candidate in candidates:
        category = classify_web_source(candidate)
        if not category:
            continue
        groups.setdefault(category, []).append(candidate)
    for group in groups.values():
        group.sort(key=lambda c: c.score, reverse=True)
    return groups


CATEGORY_LABELS: dict[str, str] = {
    "survey_support": "Survey & Review Support",
    "engineering_explainer": "Engineering Explainers & Tutorials",
    "general_web": "General Web Sources",
}
