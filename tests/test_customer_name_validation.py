"""Customer first and last names must contain at least two characters."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"
BOOT = THEME / "snippets" / "login-redirect-boot.liquid"
VALIDATION = THEME / "assets" / "customer-name-validation.js"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class CustomerNameValidationTests(unittest.TestCase):
    def test_all_customer_name_inputs_get_the_two_character_minimum(self) -> None:
        validation = read(VALIDATION)

        self.assertIn("var MIN_NAME_LENGTH = 2;", validation)
        self.assertIn("var MIN_NAME_PATTERN = '[\\\\s\\\\S]{2,}';", validation)
        for name in (
            "customer[first_name]",
            "customer[last_name]",
            "details[first_name]",
            "details[last_name]",
        ):
            with self.subTest(name=name):
                self.assertIn(name, validation)

        self.assertIn("field.setAttribute('minlength', String(MIN_NAME_LENGTH));", validation)
        self.assertIn("field.setAttribute('required', 'required');", validation)
        self.assertIn("if (!field.hasAttribute('pattern'))", validation)
        self.assertIn("field.setAttribute('pattern', MIN_NAME_PATTERN);", validation)

    def test_profile_completion_gate_rejects_short_saved_names(self) -> None:
        boot = read(BOOT)

        self.assertIn("customer.first_name | size", boot)
        self.assertIn("customer.last_name | size", boot)
        self.assertIn("cc_first_name_length < 2", boot)
        self.assertIn("cc_last_name_length < 2", boot)

    def test_validation_asset_is_deferred_from_the_head_boot_snippet(self) -> None:
        boot = read(BOOT)

        self.assertIn(
            '<script src="{{ \'customer-name-validation.js\' | asset_url }}" defer></script>',
            boot,
        )


if __name__ == "__main__":
    unittest.main()
