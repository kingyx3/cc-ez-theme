from __future__ import annotations

import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"
EXPECTED_MESSAGE_TEXT = "SG61 Special: Crack a Hobbit Collector Booster for $61."


class SG61HeaderPromoTests(unittest.TestCase):
    def test_storefront_and_editor_use_updated_sg61_copy(self) -> None:
        for relative_path in (
            Path("config/settings_data.json"),
            Path("editor_config/settings_data.json"),
        ):
            with self.subTest(path=relative_path):
                settings = json.loads(
                    (THEME_ROOT / relative_path).read_text(encoding="utf-8")
                )
                message_text = settings["presets"]["editor"]["sections"][
                    "header"
                ]["settings"]["message_text"]
                self.assertEqual(message_text, EXPECTED_MESSAGE_TEXT)


if __name__ == "__main__":
    unittest.main()
