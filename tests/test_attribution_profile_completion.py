"""Regression tests for retiring the old machine-only Click ID customer field."""

from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIELD_SNIPPET = (
    REPOSITORY_ROOT / "theme" / "snippets" / "attribution-click-id-field.liquid"
)


def source() -> str:
    return FIELD_SNIPPET.read_text(encoding="utf-8")


class RetiredClickIdDoesNotParticipateInProfileTests(unittest.TestCase):
    def test_it_never_injects_a_value_into_customer_submission(self) -> None:
        snippet = source()
        self.assertNotIn("field.value =", snippet)
        self.assertNotIn("submitClickId", snippet)
        self.assertNotIn("window.ccSourceClickId", snippet)
        self.assertNotIn("form.addEventListener('submit'", snippet)

    def test_legacy_field_is_disabled_hidden_and_has_no_name(self) -> None:
        snippet = source()
        self.assertIn("display: none !important", snippet)
        self.assertIn("wrapper.setAttribute('hidden', 'hidden')", snippet)
        self.assertIn("field.removeAttribute('required')", snippet)
        self.assertIn("field.setAttribute('disabled', 'disabled')", snippet)
        self.assertIn("field.removeAttribute('name')", snippet)

    def test_attribution_no_longer_changes_human_profile_requirements(self) -> None:
        snippet = source()
        for field_name in (
            "customer[first_name]",
            "customer[last_name]",
            "customer[gender]",
            "customer[birthdate]",
            "customer[password]",
        ):
            self.assertNotIn(field_name, snippet)
        self.assertNotIn("setAttribute('required', 'required')", snippet)


if __name__ == "__main__":
    unittest.main()
