"""Checks the override that hides the platform's email signup link.

This store signs customers up by mobile number only. The link belongs to
EasyStore's own flow at /account/auth, so no theme deploy can take it out of
the template and the theme hides it at runtime instead.

The safety constraints are the recovery-copy override's, for the same reason:
theme scripts writing into the platform's verification fields are what broke
signup with "Customer already exists (phone)".
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


THEME = Path(__file__).resolve().parents[1] / "theme"
SCRIPT_NAME = "account-otp-copy.js"


def code_only(source: str) -> str:
    """Strips JS comments so assertions read the code, not the prose."""
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return "\n".join(
        line for line in without_blocks.splitlines()
        if not line.strip().startswith("//")
    )


class EmailSignupOverrideTests(unittest.TestCase):
    RUNTIME = THEME / "assets" / SCRIPT_NAME
    EDITOR = THEME / "editor_assets" / SCRIPT_NAME

    @classmethod
    def setUpClass(cls) -> None:
        cls.code = code_only(cls.RUNTIME.read_text(encoding="utf-8"))
        pattern = re.search(r"const EMAIL_SIGNUP = /(.*)/i;", cls.code)
        assert pattern, "the link wording is no longer matched"
        cls.wording = re.compile(pattern.group(1), re.IGNORECASE)
        step = re.search(r"const OTP_STEP = /(.*)/i;", cls.code)
        assert step, "the step waiting on a code is no longer recognised"
        cls.step_wording = re.compile(step.group(1), re.IGNORECASE)

    def test_the_layout_loads_it(self) -> None:
        layout = (THEME / "layout" / "theme.liquid").read_text(encoding="utf-8")
        self.assertIn(f"'{SCRIPT_NAME}' | asset_url", layout)

    def test_runtime_and_editor_copies_stay_in_sync(self) -> None:
        self.assertEqual(
            self.RUNTIME.read_text(encoding="utf-8"),
            self.EDITOR.read_text(encoding="utf-8"),
        )

    def test_it_matches_the_wording_the_platform_shows(self) -> None:
        for wording in (
            "Continue with email instead",
            "Sign up with your email address instead",
            "Log in with e-mail instead",
        ):
            with self.subTest(wording=wording):
                self.assertTrue(self.wording.search(wording))

    def test_it_leaves_ordinary_copy_about_email_alone(self) -> None:
        for wording in (
            "Enter your email address",
            "We sent a verification code to your mobile number.",
            "Instead of email, we use your mobile number for order updates.",
        ):
            with self.subTest(wording=wording):
                self.assertIsNone(self.wording.search(wording))

    def test_it_hides_links_only(self) -> None:
        # Hiding a wrapper would take the step's instructions with it.
        self.assertIn("querySelectorAll('a, button')", self.code)
        self.assertIn("text.length > LINK_LENGTH", self.code)

    def test_it_hides_and_writes_nothing_else(self) -> None:
        # The whole safety argument for touching the platform's auth flow.
        self.assertIn("control.hidden = true", self.code)
        for forbidden in (
            "dispatchEvent",
            ".value =",
            "innerHTML",
            "textContent =",
            "submit()",
            "one-time-code",
            "OTPCredential",
            ".remove()",
            "removeChild",
            "location.pathname",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.code)

    def test_it_observes_account_pages_only(self) -> None:
        # Still no observer on the rest of the storefront, and still no
        # page-path heuristic - the trap that once turned the search box into
        # an OTP field, and why "location.pathname" is forbidden above.
        self.assertIn("if (!hasAccountStep()) return;", self.code)
        self.assertIn('form[action*="/account"]', self.code)

    def test_it_observes_the_step_that_renders_no_form(self) -> None:
        # The OTP step has no form for the form lookup to find, so keying the
        # observer off one left that step with the load-time pass alone: the
        # link went unhidden if the platform re-rendered it.
        self.assertIn("OTP_STEP.test(pageText())", self.code)
        self.assertIn("EMAIL_SIGNUP.test(pageText())", self.code)
        for wording in (
            "Enter the verification code we just sent to your mobile number.",
            "We sent a code to +65 9123 4567",
            "Resend code",
        ):
            with self.subTest(wording=wording):
                self.assertTrue(self.step_wording.search(wording))

    def test_the_rest_of_the_storefront_is_not_mistaken_for_a_step(self) -> None:
        for wording in (
            "Free shipping on orders over $80.",
            "Enter a discount code at checkout.",
            "We sent your order confirmation by email.",
        ):
            with self.subTest(wording=wording):
                self.assertIsNone(self.step_wording.search(wording))


if __name__ == "__main__":
    unittest.main()
