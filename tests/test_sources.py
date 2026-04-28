from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_lab.sources import _decode_duckduckgo_url, _extract_text_from_html


class SourceHelpersTests(unittest.TestCase):
    def test_decode_duckduckgo_redirect_url(self) -> None:
        redirected = "/l/?uddg=https%3A%2F%2Fexample.com%2Fpaper"

        decoded = _decode_duckduckgo_url(redirected)

        self.assertEqual(decoded, "https://example.com/paper")

    def test_extract_text_from_html_ignores_script(self) -> None:
        html = """
        <html>
          <head><script>console.log('ignore me')</script></head>
          <body>
            <h1>Claim</h1>
            <p>This page strengthens the argument.</p>
          </body>
        </html>
        """

        text = _extract_text_from_html(html)

        self.assertIn("Claim", text)
        self.assertIn("strengthens the argument", text)
        self.assertNotIn("ignore me", text)


if __name__ == "__main__":
    unittest.main()
