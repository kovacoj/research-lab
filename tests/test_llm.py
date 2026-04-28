from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.llm import _parse_json_block, rerank_candidates_with_llm
from research_lab.models import PaperCandidate, ResearchBrief


class FakeLlmClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return self.payload


class LlmTests(unittest.TestCase):
    def test_parse_json_block_accepts_fenced_json(self) -> None:
        payload = """```json
        {"candidates": [{"id": "c1", "score": 0.8, "reasons": ["good fit"]}]}
        ```"""

        parsed = _parse_json_block(payload)

        self.assertEqual(parsed["candidates"][0]["id"], "c1")

    def test_rerank_candidates_with_llm_returns_scores(self) -> None:
        client = FakeLlmClient({"candidates": [{"id": "c1", "score": 0.9, "reasons": ["direct match"]}]})
        brief = ResearchBrief(topic="alignment for language models", context="I need supporting literature.")
        candidates = [
            PaperCandidate(
                title="Alignment for Language Models",
                abstract="A strong direct match.",
                url="https://example.com",
                source="openalex",
                source_id="oa:1",
                source_names=["openalex"],
            )
        ]

        reranked = rerank_candidates_with_llm(client, brief, candidates)

        self.assertEqual(reranked["c1"]["score"], 0.9)
        self.assertEqual(reranked["c1"]["reasons"], ["direct match"])


if __name__ == "__main__":
    unittest.main()
