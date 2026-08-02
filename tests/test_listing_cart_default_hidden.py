from __future__ import annotations

import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


class ListingCartDefaultHiddenTests(unittest.TestCase):
    def test_storefront_and_editor_presets_hide_listing_cart_buttons(self) -> None:
        settings_files = []

        for directory in ("config", "editor_config"):
            settings = json.loads(
                (THEME_ROOT / directory / "settings_data.json").read_text(
                    encoding="utf-8"
                )
            )
            settings_files.append(settings)

            current_preset = settings["presets"][settings["current"]]
            self.assertEqual(current_preset["show_add_to_cart_button"], 0)

        self.assertEqual(settings_files[0], settings_files[1])


if __name__ == "__main__":
    unittest.main()
