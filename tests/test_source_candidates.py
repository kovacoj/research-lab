from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.source_candidates import paper_candidate, web_candidate


class SourceCandidateTests(unittest.TestCase):
    def test_paper_candidate_uses_source_name_and_snippet_defaults(self) -> None:
        candidate = paper_candidate(
            title="A Paper",
            abstract="Abstract text",
            url="https://example.com/paper",
            source="openalex",
            source_id="oa:1",
        )

        self.assertEqual(candidate.document_kind, "paper")
        self.assertEqual(candidate.snippet, "Abstract text")
        self.assertEqual(candidate.source_names, ["openalex"])

    def test_web_candidate_marks_document_kind(self) -> None:
        candidate = web_candidate(
            title="A Web Result",
            abstract="Snippet text",
            url="https://example.com/web",
            source="duckduckgo",
            source_id="web:1",
            venue="example.com",
        )

        self.assertEqual(candidate.document_kind, "web")
        self.assertEqual(candidate.snippet, "Snippet text")
        self.assertEqual(candidate.source_names, ["duckduckgo"])


if __name__ == "__main__":
    unittest.main()
