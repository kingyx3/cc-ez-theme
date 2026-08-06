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


class AccountSubmitGuardTests(unittest.TestCase):
    """The theme's own account forms are still guarded.

    These are theme-rendered templates with native form submits, so a submit
    lock does work here - unlike the platform's OTP widget.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.global_script = (THEME_ROOT / "assets" / "global.js").read_text(
            encoding="utf-8"
        )
        cls.editor_global_script = (
            THEME_ROOT / "editor_assets" / "global.js"
        ).read_text(encoding="utf-8")
        cls.templates = {
            name: (THEME_ROOT / "templates" / "customers" / f"{name}.liquid").read_text(
                encoding="utf-8"
            )
            for name in ("login", "register", "activate_account")
        }

    def test_storefront_and_editor_globals_match(self) -> None:
        self.assertEqual(self.global_script, self.editor_global_script)

    def test_account_forms_drop_duplicate_submits(self) -> None:
        self.assertIn("function guardSingleAccountSubmit", self.global_script)
        self.assertIn("submitInFlight", self.global_script)
        self.assertIn("event.stopImmediatePropagation()", self.global_script)
        self.assertIn("}, true);", self.global_script)

    def test_the_submit_button_is_never_disabled(self) -> None:
        # A disabled submit control is dropped from the payload and some
        # browsers cancel the in-flight submission along with it.
        self.assertNotIn("button.disabled = true", self.global_script)
        self.assertIn("btn--loading", self.global_script)

    def test_the_lock_is_released_when_the_page_stays_put(self) -> None:
        self.assertIn("window.setTimeout(release", self.global_script)
        self.assertIn("'pageshow', release", self.global_script)

    def test_customer_forms_use_the_shared_guard(self) -> None:
        for name, template in self.templates.items():
            with self.subTest(template=name):
                self.assertIn("guardSingleAccountSubmit", template)
                # global.js is deferred, so the call has to wait for it.
                self.assertIn("DOMContentLoaded", template)
                # The old inline handler dereferenced a missing element.
                self.assertNotIn(".btn').classList.add", template)

    def test_every_guarded_form_actually_has_a_loading_button(self) -> None:
        for name, template in self.templates.items():
            with self.subTest(template=name):
                self.assertIn('type="submit" class="btn"', template)


if __name__ == "__main__":
    unittest.main()
