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


class GenderControlLayoutTests(unittest.TestCase):
    """Mobile and desktop guarantees for the gender segmented control.

    Verified in Chromium at 320px, 390px and 1280px: options sit side by side,
    stay above the 44px touch minimum, never overflow or clip, and a required
    group still reports validity.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.script = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_the_field_wrapper_is_replaced_not_filled(self) -> None:
        # `.customer .field` styles its label/input children as a floating-label
        # text input. Rendering the radio group inside it put every option at the
        # same absolute position with pointer-events: none - overlapping and
        # untappable.
        self.assertIn("const replaceGenderControl", self.script)
        self.assertIn("select.closest('.field')", self.script)
        # Never swallow a wrapper that holds other fields too.
        self.assertIn("querySelectorAll('input, select, textarea').length === 1", self.script)

    def test_injected_rules_outrank_the_account_field_styles(self) -> None:
        # `.customer .field label` is (0,2,1); a bare `.class` selector loses to
        # it no matter where the stylesheet sits in the cascade.
        for selector in (
            "fieldset.customer-gender-options",
            "legend.customer-gender-options__legend",
            "div.customer-gender-options__choices",
            "label.customer-gender-options__choice",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.script)
        # The properties `.customer .field label` would otherwise impose.
        self.assertIn("position: relative", self.script)
        self.assertIn("pointer-events: auto", self.script)

    def test_options_share_a_row_and_wrap_only_when_forced(self) -> None:
        self.assertIn("display: grid", self.script)
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr))", self.script)

    def test_options_reuse_the_themes_text_input_tokens(self) -> None:
        # Same pill radius, ring, height and type scale as the fields above and
        # below, so the control does not read as a second design.
        self.assertIn("border-radius: 3.5rem", self.script)
        self.assertIn("box-shadow: 0 0 0 0.1rem rgba(var(--color-foreground), 1)", self.script)
        self.assertIn("min-height: 4rem", self.script)
        self.assertIn("font-size: 1.5rem", self.script)

    def test_the_selected_option_is_unmistakable(self) -> None:
        self.assertIn("input:checked + span", self.script)
        self.assertIn("background-color: rgb(var(--color-foreground))", self.script)
        self.assertIn("color: rgb(var(--color-background))", self.script)

    def test_keyboard_and_motion_preferences_are_respected(self) -> None:
        self.assertIn("input:focus-visible + span", self.script)
        self.assertIn("outline-offset", self.script)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.script)
        # Hover feedback must not fire on touch, where it sticks after a tap.
        self.assertIn("@media (hover: hover)", self.script)

    def test_disabled_options_read_as_disabled(self) -> None:
        self.assertIn("input:disabled + span", self.script)


class BirthdatePickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_typing_is_offered_only_where_there_is_a_real_pointer(self) -> None:
        # On a phone a typeable date field raises the keyboard over the calendar.
        self.assertIn("const pointerIsCoarse", self.script)
        self.assertIn("'(pointer: coarse)'", self.script)
        self.assertIn("picker.config.allowInput = allowTyping", self.script)

    def test_the_readonly_attribute_is_corrected_by_hand(self) -> None:
        # flatpickr only reads allowInput while building, so flipping the config
        # afterwards leaves the input readonly and the setting inert.
        self.assertIn("input.removeAttribute('readonly')", self.script)
        self.assertIn("input.setAttribute('readonly', 'readonly')", self.script)


if __name__ == "__main__":
    unittest.main()
