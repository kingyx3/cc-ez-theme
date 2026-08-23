from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"
LAYOUT = THEME / "layout" / "theme.liquid"
TRACKING = THEME / "snippets" / "hubspot-tracking.liquid"


class HubSpotTrackingTests(unittest.TestCase):
    def test_the_portal_tracking_code_is_loaded_once(self) -> None:
        source = TRACKING.read_text(encoding="utf-8")

        self.assertIn('id="hs-script-loader"', source)
        self.assertIn("https://js.hs-scripts.com/246919056.js", source)

        theme_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in THEME.rglob("*.liquid")
        )
        self.assertEqual(theme_source.count('id="hs-script-loader"'), 1)

    def test_tracking_is_included_at_body_end(self) -> None:
        layout = LAYOUT.read_text(encoding="utf-8")
        include = "{% include 'hubspot-tracking' %}"

        self.assertIn(include, layout)
        self.assertLess(layout.index(include), layout.index("</body>"))
        self.assertLess(layout.index(include), layout.index("{% app_snippet 'global/body_end' %}"))


if __name__ == "__main__":
    unittest.main()
