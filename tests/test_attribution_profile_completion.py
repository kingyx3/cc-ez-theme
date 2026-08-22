"""Regression tests for Click ID versus customer profile completion."""

from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIELD_SNIPPET = (
    REPOSITORY_ROOT / "theme" / "snippets" / "attribution-click-id-field.liquid"
)


def source() -> str:
    return FIELD_SNIPPET.read_text(encoding="utf-8")


class ClickIdDoesNotCompleteTheHumanProfileTests(unittest.TestCase):
    def test_signup_and_activation_require_the_human_fields(self) -> None:
        snippet = source()

        for field_name in (
            "customer[first_name]",
            "customer[last_name]",
            "customer[gender]",
            "customer[birthdate]",
            "customer[password]",
        ):
            self.assertIn(f"'{field_name}'", snippet)

        self.assertIn("form.id !== 'form-register'", snippet)
        self.assertIn("form.id !== 'form-activate'", snippet)
        self.assertIn("input.setAttribute('required', 'required')", snippet)

    def test_click_id_is_injected_by_the_submit_listener(self) -> None:
        snippet = source()

        listener = snippet.index("form.addEventListener('submit'")
        injected_from_listener = snippet.index("submitClickId(field);", listener)
        capture_phase = snippet.index("}, true);", injected_from_listener)

        self.assertLess(listener, injected_from_listener)
        self.assertLess(injected_from_listener, capture_phase)

    def test_click_id_stays_hidden_and_is_not_required(self) -> None:
        snippet = source()

        self.assertIn("display: none !important", snippet)
        self.assertIn("wrapper.setAttribute('hidden', 'hidden')", snippet)
        self.assertIn("field.removeAttribute('required')", snippet)


if __name__ == "__main__":
    unittest.main()
