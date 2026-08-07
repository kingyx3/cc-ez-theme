from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CSS = ROOT / "theme" / "assets" / "base.css"
EDITOR_CSS = ROOT / "theme" / "editor_assets" / "base.css"


class CheckoutEmailPlaceholderTest(unittest.TestCase):
    def test_no_float_label_placeholders_are_visible(self):
        expected = (
            ".field__input.no-float-label::placeholder {\n"
            "  opacity: 1;\n"
            "}"
        )
        for path in (RUNTIME_CSS, EDITOR_CSS):
            with self.subTest(path=path):
                self.assertIn(expected, path.read_text(encoding="utf-8"))

    def test_a_field_with_no_label_shows_its_placeholder(self):
        # The checkout is rendered by the platform, not by this theme, so its
        # inputs arrive without the floating label the hidden placeholder
        # assumes. Without this rule the email field there names itself nowhere.
        expected = (
            ".field__input:not(:has(~ label))::placeholder {\n"
            "  opacity: 1;\n"
            "}"
        )
        for path in (RUNTIME_CSS, EDITOR_CSS):
            with self.subTest(path=path):
                self.assertIn(expected, path.read_text(encoding="utf-8"))

    def test_the_has_rule_stands_alone(self):
        # A browser without :has() drops the whole rule it appears in, so it
        # must not share a selector list with the no-float-label rule.
        for path in (RUNTIME_CSS, EDITOR_CSS):
            with self.subTest(path=path):
                self.assertNotIn(
                    ".field__input.no-float-label::placeholder,",
                    path.read_text(encoding="utf-8"),
                )

    def test_runtime_and_editor_css_stay_in_sync(self):
        self.assertEqual(
            RUNTIME_CSS.read_text(encoding="utf-8"),
            EDITOR_CSS.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
