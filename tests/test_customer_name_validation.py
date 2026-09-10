"""Customer first and last names must contain at least two characters."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT / "theme" / "snippets" / "login-redirect-boot.liquid"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class CustomerNameValidationTests(unittest.TestCase):
    def test_all_customer_name_inputs_get_the_two_character_minimum(self) -> None:
        boot = read(BOOT)

        for name in (
            "customer[first_name]",
            "customer[last_name]",
            "details[first_name]",
            "details[last_name]",
        ):
            with self.subTest(name=name):
                self.assertIn(name, boot)

        self.assertIn("field.setAttribute('required', 'required');", boot)
        self.assertIn("field.setAttribute('minlength', '2');", boot)
        self.assertIn("field.setAttribute('pattern', '.{2,}');", boot)

    def test_profile_completion_gate_rejects_short_saved_names(self) -> None:
        boot = read(BOOT)

        self.assertIn("customer.first_name | size", boot)
        self.assertIn("customer.last_name | size", boot)
        self.assertIn("cc_first_name_length < 2", boot)
        self.assertIn("cc_last_name_length < 2", boot)


if __name__ == "__main__":
    unittest.main()
