from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "theme" / "assets" / "search-history.js"


class CustomerFormEnhancementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_verification_codes_support_mobile_otp_autofill(self) -> None:
        self.assertIn("autocomplete', 'one-time-code", self.script)
        self.assertIn("'OTPCredential' in window", self.script)
        self.assertIn("otp: { transport: ['sms'] }", self.script)
        self.assertIn("input.dispatchEvent(new Event('input'", self.script)

    def test_gender_dropdowns_become_clickable_radio_options(self) -> None:
        self.assertIn('select[name="customer[gender]"]', self.script)
        self.assertIn('select[name="details[gender]"]', self.script)
        self.assertIn("radio.type = 'radio'", self.script)
        self.assertIn("radio.name = select.name", self.script)
        self.assertIn("customer-gender-options__choice", self.script)

    def test_empty_birthdate_pickers_open_at_january_2000(self) -> None:
        self.assertIn("new Date(2000, 0, 1)", self.script)
        self.assertIn("instance.jumpToDate(DEFAULT_BIRTHDATE, false)", self.script)
        self.assertIn("input.setAttribute('autocomplete', 'bday')", self.script)
        self.assertIn("if (!dateStr && !instance.selectedDates.length)", self.script)

    def test_dynamic_verification_markup_is_also_enhanced(self) -> None:
        self.assertIn("new MutationObserver", self.script)
        self.assertIn("record.addedNodes.forEach", self.script)
        self.assertIn("enhanceVerificationForm", self.script)


if __name__ == "__main__":
    unittest.main()
