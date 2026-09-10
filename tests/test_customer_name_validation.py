"""Customer first and last names must contain at least two letters."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT / "theme" / "snippets" / "login-redirect-boot.liquid"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class CustomerNameValidationTests(unittest.TestCase):
    def test_all_customer_name_inputs_require_two_actual_letters(self) -> None:
        boot = read(BOOT)

        for name in (
            "customer[first_name]",
            "customer[last_name]",
            "details[first_name]",
            "details[last_name]",
        ):
            with self.subTest(name=name):
                self.assertIn(name, boot)

        self.assertIn("field.required = true;", boot)
        self.assertIn("field.minLength = 2;", boot)
        self.assertIn("new RegExp('\\\\p{L}', 'gu')", boot)
        self.assertIn("field.setCustomValidity(count >= 2", boot)
        self.assertIn("Please enter at least 2 letters for your ", boot)
        self.assertNotIn("field.setAttribute('pattern', '.{2,}');", boot)

    def test_dynamic_and_autofilled_fields_are_rechecked_before_submit(self) -> None:
        boot = read(BOOT)

        for event_name in ("focusin", "input", "change", "invalid"):
            with self.subTest(event_name=event_name):
                self.assertIn(event_name, boot)

        self.assertIn("validateForm(button.form);", boot)
        self.assertIn("event.key === 'Enter'", boot)
        self.assertIn("validateForm(event.target.form);", boot)

    def test_profile_completion_gate_strips_outer_whitespace_from_saved_names(self) -> None:
        boot = read(BOOT)

        self.assertIn("customer.first_name | strip | size", boot)
        self.assertIn("customer.last_name | strip | size", boot)
        self.assertIn("cc_first_name_length < 2", boot)
        self.assertIn("cc_last_name_length < 2", boot)


if __name__ == "__main__":
    unittest.main()
