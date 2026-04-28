from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from research_lab.models import PaperCandidate, ResearchBrief


class LlmError(RuntimeError):
    pass


@dataclass(slots=True)
class LlmClient:
    model: str
    base_url: str
    api_key: str = ""
    timeout_seconds: int = 60

    @classmethod
    def from_env(cls) -> "LlmClient | None":
        model = os.getenv("RESEARCH_LAB_LLM_MODEL", "").strip()
        if not model:
            return None
        base_url = os.getenv("RESEARCH_LAB_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        api_key = os.getenv("RESEARCH_LAB_LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")).strip()
        return cls(model=model, base_url=base_url, api_key=api_key)

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        url = f"{self.base_url}/chat/completions"
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        payload = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "research-lab/0.1",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - network specific
            detail = exc.read().decode("utf-8", errors="ignore")
            raise LlmError(f"llm request failed ({exc.code}): {detail[:240]}") from exc
        except Exception as exc:  # pragma: no cover - network specific
            raise LlmError(f"llm request failed: {exc}") from exc

        try:
            content = raw["choices"][0]["message"]["content"]
        except Exception as exc:  # pragma: no cover - provider specific
            raise LlmError("llm response missing message content") from exc
        return _parse_json_block(content)


def rerank_candidates_with_llm(
    client: LlmClient,
    brief: ResearchBrief,
    candidates: list[PaperCandidate],
) -> dict[str, dict]:
    if not candidates:
        return {}

    system_prompt = (
        "You rerank research search results. Prefer direct topical fit, usefulness for strengthening an argument, "
        "and evidence in the supplied text. Penalize nearby but wrong modalities or domains. "
        "Return strict JSON only."
    )
    user_prompt = _build_rerank_prompt(brief, candidates)
    payload = client.chat_json(system_prompt, user_prompt)

    reranked: dict[str, dict] = {}
    for item in payload.get("candidates", []):
        candidate_id = str(item.get("id", "")).strip()
        if not candidate_id:
            continue
        try:
            score = float(item.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        reasons = [str(reason).strip() for reason in item.get("reasons", []) if str(reason).strip()]
        reranked[candidate_id] = {
            "score": score,
            "reasons": reasons[:3],
        }
    return reranked


def summarize_candidates_with_llm(
    client: LlmClient,
    brief: ResearchBrief,
    candidates: list[PaperCandidate],
) -> str:
    if not candidates:
        return ""

    system_prompt = (
        "You help a researcher strengthen arguments from retrieved literature. "
        "Return strict JSON with concise bullet-ready text only."
    )
    user_prompt = _build_summary_prompt(brief, candidates)
    payload = client.chat_json(system_prompt, user_prompt)

    support_points = [str(item).strip() for item in payload.get("support_points", []) if str(item).strip()]
    counterpoints = [str(item).strip() for item in payload.get("counterpoints", []) if str(item).strip()]
    next_queries = [str(item).strip() for item in payload.get("next_queries", []) if str(item).strip()]

    lines: list[str] = []
    if support_points:
        lines.append("### Strongest Support")
        lines.extend(f"- {item}" for item in support_points[:4])
    if counterpoints:
        lines.append("")
        lines.append("### Caveats")
        lines.extend(f"- {item}" for item in counterpoints[:3])
    if next_queries:
        lines.append("")
        lines.append("### Suggested Next Queries")
        lines.extend(f"- {item}" for item in next_queries[:4])
    return "\n".join(lines)


def _build_rerank_prompt(brief: ResearchBrief, candidates: list[PaperCandidate]) -> str:
    lines = [
        f"Topic: {brief.topic}",
        f"Context: {brief.context or '(none)'}",
        f"Must include: {', '.join(brief.must_include) or '(none)'}",
        f"Must exclude: {', '.join(brief.must_exclude) or '(none)'}",
        "",
        "Return JSON with schema:",
        '{"candidates": [{"id": "c1", "score": 0.0_to_1.0, "reasons": ["..."]}]}',
        "",
        "Candidates:",
    ]
    for index, candidate in enumerate(candidates, start=1):
        lines.extend(_render_candidate_for_prompt(index, candidate))
    return "\n".join(lines)


def _build_summary_prompt(brief: ResearchBrief, candidates: list[PaperCandidate]) -> str:
    lines = [
        f"Topic: {brief.topic}",
        f"Context: {brief.context or '(none)'}",
        "",
        "Return JSON with schema:",
        '{"support_points": ["..."], "counterpoints": ["..."], "next_queries": ["..."]}',
        "",
        "Top candidates:",
    ]
    for index, candidate in enumerate(candidates, start=1):
        lines.extend(_render_candidate_for_prompt(index, candidate))
    return "\n".join(lines)


def _render_candidate_for_prompt(index: int, candidate: PaperCandidate) -> list[str]:
    lines = [
        f"ID: c{index}",
        f"Title: {candidate.title}",
        f"Kind: {candidate.document_kind}",
        f"Year: {candidate.year or 'n/a'}",
        f"Venue: {candidate.venue or 'n/a'}",
        f"Heuristic score: {candidate.score:.4f}",
    ]
    if candidate.abstract:
        lines.append(f"Abstract: {_trim(candidate.abstract, 900)}")
    elif candidate.snippet:
        lines.append(f"Snippet: {_trim(candidate.snippet, 900)}")
    if candidate.evidence:
        lines.append(f"Evidence: {' | '.join(_trim(item, 220) for item in candidate.evidence[:2])}")
    lines.append("")
    return lines


def _trim(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def _parse_json_block(text: str) -> dict:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL)
    if fence_match:
        return json.loads(fence_match.group(1))

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(stripped[start : end + 1])
    raise LlmError("llm response did not contain valid json")
