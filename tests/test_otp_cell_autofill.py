from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"

# Every runtime script the theme loads on the storefront.
ASSET_DIRECTORIES = ("assets", "editor_assets")


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


class OtpFieldsAreLeftAloneTests(unittest.TestCase):
    """Regression guard for the "Customer already exists (phone)" outage.

    The one-time-code step at /account/auth is rendered by EasyStore, not by
    this theme, and the widget posts its verification itself. Theme scripts that
    wrote into those cells and dispatched synthetic input/change events made the
    widget fire that request more than once: the first call created the customer
    and the second came back "Customer already exists (phone)", so signup broke
    for every new phone number.

    The widget also submits over fetch rather than a native form submit, so a
    submit-event guard cannot deduplicate it from the theme side. Until the
    real markup is known, the theme stays out of these fields entirely - which
    is the behaviour that shipped before PR #65 and PR #66.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.scripts = {
            path: code_only(path.read_text(encoding="utf-8"))
            for directory in ASSET_DIRECTORIES
            for path in sorted((THEME_ROOT / directory).glob("*.js"))
        }
        cls.currencies = (
            THEME_ROOT / "snippets" / "currencies.liquid"
        ).read_text(encoding="utf-8")

    def test_the_otp_module_is_not_shipped(self) -> None:
        for directory in ASSET_DIRECTORIES:
            with self.subTest(directory=directory):
                self.assertFalse(
                    (THEME_ROOT / directory / "otp-cell-autofill.js").exists()
                )

    def test_no_layout_or_snippet_loads_an_otp_script(self) -> None:
        self.assertNotIn("otp-cell-autofill", self.currencies)
        for liquid in THEME_ROOT.rglob("*.liquid"):
            with self.subTest(template=liquid.name):
                self.assertNotIn(
                    "otp-cell-autofill", liquid.read_text(encoding="utf-8")
                )

    def test_no_theme_script_claims_one_time_code_fields(self) -> None:
        for path, source in self.scripts.items():
            with self.subTest(script=path.name):
                self.assertNotIn("one-time-code", source)
                self.assertNotIn("OTPCredential", source)

    def test_no_theme_script_writes_synthetic_events_into_otp_cells(self) -> None:
        # The double submit came from dispatching input/change on cells the
        # platform widget owns.
        for path, source in self.scripts.items():
            with self.subTest(script=path.name):
                self.assertNotIn("distributeOtpCode", source)
                self.assertNotIn("otpCell", source)


class ActivateAccountButtonTests(unittest.TestCase):
    """The activate template renders no ".btn", so its own inline handler threw
    a TypeError on every submit and the loading state never applied."""

    def test_the_activate_form_renders_the_button_its_script_looks_for(self) -> None:
        template = (
            THEME_ROOT / "templates" / "customers" / "activate_account.liquid"
        ).read_text(encoding="utf-8")
        self.assertIn("#form-activate .btn", template)
        self.assertIn('type="submit" class="btn"', template)


class NoNewAuthFlowScriptsTests(unittest.TestCase):
    """Auth-flow JavaScript is back to what shipped before PR #65 and PR #66.

    Speculative theme scripts in the account flows caused the outage; the only
    change kept there is the one-line button fix above.
    """

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
