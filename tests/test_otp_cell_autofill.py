from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"
ASSET_DIRECTORIES = ("assets", "editor_assets")


def code_only(source: str) -> str:
    """Strip comments so assertions describe runtime behaviour, not prose."""
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return "\n".join(
        line for line in without_blocks.splitlines()
        if not line.strip().startswith("//")
    )


class OtpFieldsAreLeftAloneTests(unittest.TestCase):
    """EasyStore's OTP widget must be exclusively platform-owned.

    Theme-side writes and synthetic events have broken signup before. The live
    flow is again failing after OTP while parsing an HTML response as JSON, so the
    emergency posture is stricter: the shipped compatibility asset remains in the
    layout but executes no OTP behaviour at all.
    """

    MODULE = "account-otp-autofill.js"

    @classmethod
    def setUpClass(cls) -> None:
        cls.module_bodies = {
            directory: (THEME_ROOT / directory / cls.MODULE).read_text(encoding="utf-8")
            for directory in ASSET_DIRECTORIES
        }
        cls.module_code = {
            directory: code_only(body)
            for directory, body in cls.module_bodies.items()
        }

    def test_old_otp_module_stays_removed(self) -> None:
        for directory in ASSET_DIRECTORIES:
            with self.subTest(directory=directory):
                self.assertFalse((THEME_ROOT / directory / "otp-cell-autofill.js").exists())

    def test_kill_switch_ships_identically_to_both_asset_mirrors(self) -> None:
        self.assertEqual(self.module_bodies["assets"], self.module_bodies["editor_assets"])

    def test_layout_can_keep_loading_the_inert_asset(self) -> None:
        layout = (THEME_ROOT / "layout" / "theme.liquid").read_text(encoding="utf-8")
        self.assertIn(self.MODULE, layout)

    def test_kill_switch_has_no_otp_dom_or_event_behaviour(self) -> None:
        for directory, source in self.module_code.items():
            with self.subTest(directory=directory):
                self.assertNotIn("#otp-form", source)
                self.assertNotIn(".otp-input", source)
                self.assertNotIn("addEventListener", source)
                self.assertNotIn("dispatchEvent", source)
                self.assertNotIn(".value =", source)
                self.assertNotIn("OTPCredential", source)
                self.assertNotIn("one-time-code", source)

    def test_no_other_theme_script_claims_one_time_code_fields(self) -> None:
        for directory in ASSET_DIRECTORIES:
            for path in sorted((THEME_ROOT / directory).glob("*.js")):
                if path.name == self.MODULE:
                    continue
                source = code_only(path.read_text(encoding="utf-8"))
                with self.subTest(script=str(path.relative_to(THEME_ROOT))):
                    self.assertNotIn("one-time-code", source)
                    self.assertNotIn("OTPCredential", source)
                    self.assertNotIn("distributeOtpCode", source)
                    self.assertNotIn("otpCell", source)


class ActivateAccountButtonTests(unittest.TestCase):
    """The activate template renders the button its inline handler looks for."""

    def test_the_activate_form_renders_the_button_its_script_looks_for(self) -> None:
        template = (
            THEME_ROOT / "templates" / "customers" / "activate_account.liquid"
        ).read_text(encoding="utf-8")
        self.assertIn("#form-activate .btn", template)
        self.assertIn('type="submit" class="btn"', template)


class NoNewAuthFlowScriptsTests(unittest.TestCase):
    """Do not add theme-side submit interception to EasyStore account flows."""

    def test_global_js_adds_no_account_submit_handling(self) -> None:
        for directory in ASSET_DIRECTORIES:
            with self.subTest(directory=directory):
                source = code_only(
                    (THEME_ROOT / directory / "global.js").read_text(encoding="utf-8")
                )
                self.assertNotIn("guardSingleAccountSubmit", source)

    def test_customer_templates_keep_their_original_submit_handlers(self) -> None:
        for name in ("login", "register", "activate_account"):
            with self.subTest(template=name):
                template = (
                    THEME_ROOT / "templates" / "customers" / f"{name}.liquid"
                ).read_text(encoding="utf-8")
                self.assertNotIn("guardSingleAccountSubmit", template)
                self.assertIn(".btn').classList.add('btn--loading','loading')", template)


if __name__ == "__main__":
    unittest.main()
