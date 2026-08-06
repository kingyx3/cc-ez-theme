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

    def test_runtime_and_editor_css_stay_in_sync(self):
        self.assertEqual(
            RUNTIME_CSS.read_text(encoding="utf-8"),
            EDITOR_CSS.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
