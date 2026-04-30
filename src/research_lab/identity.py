from __future__ import annotations

import re

from research_lab.models import PaperCandidate


def normalize_title(title: str) -> str:
    lowered = title.lower()
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def candidates_match(left: PaperCandidate, right: PaperCandidate) -> bool:
    if left.doi and right.doi and left.doi.lower() == right.doi.lower():
        return True
    left_title = normalize_title(left.title)
    right_title = normalize_title(right.title)
    if left_title == right_title:
        return True
    return _titles_match_fuzzily(left_title, right_title)


def _titles_match_fuzzily(left_title: str, right_title: str) -> bool:
    if not left_title or not right_title:
        return False
    shorter, longer = sorted([left_title, right_title], key=len)
    if len(shorter.split()) >= 5 and longer.startswith(shorter):
        return True
    left_terms = set(left_title.split())
    right_terms = set(right_title.split())
    overlap = len(left_terms & right_terms)
    minimum = min(len(left_terms), len(right_terms))
    return minimum >= 5 and overlap / minimum >= 0.8
