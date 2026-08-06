from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "theme" / "assets" / "search-history.js"


def code_only(source: str) -> str:
    """Strip comments so assertions describe behaviour, not prose.

    Only whole-line `//` comments and `/* */` blocks are removed, so a `//`
    inside a string literal (a URL, say) is never mistaken for a comment.
    """
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return "\n".join(
        line for line in without_blocks.splitlines()
        if not line.strip().startswith("//")
    )


class CustomerFormEnhancementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = SCRIPT_PATH.read_text(encoding="utf-8")
        cls.code = code_only(cls.script)

    def test_verification_codes_are_left_to_the_platform(self) -> None:
        # This module used to claim the verification cells at /account/auth and
        # open a WebOTP request against them. The platform widget posts its own
        # request, and the extra synthetic events made it post twice, breaking
        # signup with "Customer already exists (phone)".
        self.assertNotIn("one-time-code", self.code)
        self.assertNotIn("OTPCredential", self.code)
        self.assertNotIn("navigator.credentials", self.code)
        self.assertNotIn("enhanceVerificationForm", self.code)

    def test_no_form_on_a_verification_page_is_blindly_claimed(self) -> None:
        # The old page-path heuristic turned the header search box into an OTP
        # field on any URL containing "verify".
        self.assertNotIn("window.location.pathname", self.code)

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

    def test_dynamic_profile_markup_is_also_enhanced(self) -> None:
        self.assertIn("new MutationObserver", self.script)
        self.assertIn("record.addedNodes.forEach", self.script)
        self.assertIn("enhanceGenderSelect", self.script)
        self.assertIn("enhanceBirthdateInput", self.script)


if __name__ == "__main__":
    unittest.main()
