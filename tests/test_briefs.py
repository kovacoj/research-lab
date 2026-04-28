from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.briefs import parse_brief_markdown


class BriefParsingTests(unittest.TestCase):
    def test_parse_brief_markdown_sections(self) -> None:
        markdown = """
        # Topic
        Test-time adaptation for language models

        ## Context
        I have already looked at prompt tuning and inference-time adaptation.

        ## Domains
        - NLP
        - ML systems

        ## Must Include
        - language model
        - inference-time

        ## Must Exclude
        - vision-language

        ## Since Year
        2022

        ## Iterations
        3
        """

        brief = parse_brief_markdown(markdown)

        self.assertEqual(brief.topic, "Test-time adaptation for language models")
        self.assertIn("prompt tuning", brief.context)
        self.assertEqual(brief.domains, ["NLP", "ML systems"])
        self.assertEqual(brief.must_include, ["language model", "inference-time"])
        self.assertEqual(brief.must_exclude, ["vision-language"])
        self.assertEqual(brief.since_year, 2022)
        self.assertEqual(brief.iterations, 3)

    def test_parse_brief_markdown_requires_topic(self) -> None:
        with self.assertRaises(ValueError):
            parse_brief_markdown("## Context\nOnly notes")


if __name__ == "__main__":
    unittest.main()
