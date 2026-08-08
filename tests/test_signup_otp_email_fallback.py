"""Checks the override that removes the email escape hatch from the OTP step.

Signing up here verifies a mobile number, and while the code is outstanding
EasyStore offers a "continue with email instead" link. That link belongs to the
platform's own flow at /account/auth, so no theme deploy can take it out of the
template; the theme hides it at runtime instead.

The safety constraints are the same ones the recovery-copy override lives under,
and for the same reason: theme scripts writing into the platform's verification
fields are what broke signup with "Customer already exists (phone)". This
override reads text and hides an element, and the assertions below hold it
there.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


THEME = Path(__file__).resolve().parents[1] / "theme"
ASSET_DIRECTORIES = ("assets", "editor_assets")
SCRIPT_NAME = "account-otp-copy.js"


def code_only(source: str) -> str:
    """Strips JS comments so assertions read the code, not the prose."""
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return "\n".join(
        line for line in without_blocks.splitlines()
        if not line.strip().startswith("//")
    )


class OtpEmailFallbackOverrideTests(unittest.TestCase):
    RUNTIME = THEME / "assets" / SCRIPT_NAME
    EDITOR = THEME / "editor_assets" / SCRIPT_NAME

    @classmethod
    def setUpClass(cls) -> None:
        cls.script = cls.RUNTIME.read_text(encoding="utf-8")
        cls.code = code_only(cls.script)

    def test_the_layout_loads_it(self) -> None:
        layout = (THEME / "layout" / "theme.liquid").read_text(encoding="utf-8")
        self.assertIn(f"'{SCRIPT_NAME}' | asset_url", layout)

    def test_runtime_and_editor_copies_stay_in_sync(self) -> None:
        self.assertEqual(
            self.RUNTIME.read_text(encoding="utf-8"),
            self.EDITOR.read_text(encoding="utf-8"),
        )

    def test_it_matches_the_wording_the_platform_shows(self) -> None:
        pattern = re.search(
            r"const EMAIL_FALLBACK = /(.*)/i;", self.code
        )
        self.assertIsNotNone(pattern, "the fallback wording is no longer matched")
        fallback = re.compile(pattern.group(1), re.IGNORECASE)
        for wording in (
            "Continue with email instead",
            "continue with email instead",
            "Sign up with your email address instead",
            "Log in with e-mail instead",
            "Use email instead",
        ):
            with self.subTest(wording=wording):
                self.assertTrue(fallback.search(wording))

    def test_it_leaves_ordinary_copy_about_email_alone(self) -> None:
        pattern = re.search(r"const EMAIL_FALLBACK = /(.*)/i;", self.code)
        fallback = re.compile(pattern.group(1), re.IGNORECASE)
        for wording in (
            "Enter your email address",
            "We sent a verification code to your mobile number.",
            "You can update your email in account details.",
            "Instead of email, we use your mobile number for order updates.",
        ):
            with self.subTest(wording=wording):
                self.assertIsNone(fallback.search(wording))

    def test_it_only_hides_while_a_code_is_outstanding(self) -> None:
        # A link offered before any code was sent - the choice between signing
        # up by phone or by email - is not this link, and stays.
        self.assertIn("if (!OTP_STEP.test(pageText())) return 0;", self.code)
        step = re.search(r"const OTP_STEP = /(.*)/i;", self.code)
        self.assertIsNotNone(step)
        otp_step = re.compile(step.group(1), re.IGNORECASE)
        for wording in (
            "Enter the verification code we just sent to +65 9123 4567",
            "Resend code",
            "Verify your mobile number",
            "Confirm your mobile OTP to proceed",
        ):
            with self.subTest(wording=wording):
                self.assertTrue(otp_step.search(wording))
        for wording in ("Create account", "Sign in to your account"):
            with self.subTest(wording=wording):
                self.assertIsNone(otp_step.search(wording))

    def test_it_hides_and_writes_nothing_else(self) -> None:
        # The whole safety argument for touching the platform's auth flow.
        self.assertIn("element.hidden = true", self.code)
        self.assertNotIn("dispatchEvent", self.code)
        self.assertNotIn(".value =", self.code)
        self.assertNotIn("innerHTML", self.code)
        self.assertNotIn("textContent =", self.code)
        self.assertNotIn("submit()", self.code)
        self.assertNotIn("one-time-code", self.code)
        self.assertNotIn("OTPCredential", self.code)

    def test_it_leaves_the_platform_markup_in_place(self) -> None:
        # The widget can still hold the node it rendered, so nothing is removed
        # and no control is left behind with its text blanked out.
        self.assertNotIn(".remove()", self.code)
        self.assertNotIn("removeChild", self.code)

    def test_it_leaves_the_rest_of_the_storefront_alone(self) -> None:
        # No observer anywhere without an account step on the page, and no
        # page-path heuristics - the trap that once turned the search box into
        # an OTP field.
        self.assertIn("if (!hasAccountStep()) return;", self.code)
        self.assertIn('form[action*="/account/register"]', self.code)
        self.assertNotIn("location.pathname", self.code)

    def test_it_only_reads_elements_that_hold_their_own_text(self) -> None:
        self.assertIn("element.children.length === 0", self.code)
        self.assertIn("if (!isLeaf(element)) return;", self.code)

    def test_it_hides_a_link_and_not_a_paragraph(self) -> None:
        # Hiding a wrapper would take the step's instructions with it.
        self.assertIn("text.length > LINK_LENGTH", self.code)
        self.assertIn("own(parent) === own(target)", self.code)


class NoNewOtpFieldHandlingTests(unittest.TestCase):
    """The override must not reintroduce what broke signup.

    tests/test_otp_cell_autofill.py guards every theme script; this repeats the
    check against the new one so a failure names the file that caused it.
    """

    def test_the_override_claims_no_verification_fields(self) -> None:
        for directory in ASSET_DIRECTORIES:
            with self.subTest(directory=directory):
                source = code_only(
                    (THEME / directory / SCRIPT_NAME).read_text(encoding="utf-8")
                )
                self.assertNotIn("otpCell", source)
                self.assertNotIn("distributeOtpCode", source)
                self.assertNotIn("querySelector('input", source)


if __name__ == "__main__":
    unittest.main()
