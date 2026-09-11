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
    submit-event guard cannot deduplicate it from the theme side. It can change
    independently of this theme, which means even a synthetic-event design that
    submits once against a captured replica can submit twice against later
    platform behavior. The theme therefore stays out of the OTP cells entirely.
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

    def test_legacy_otp_mutation_modules_stay_removed(self) -> None:
        for directory in ASSET_DIRECTORIES:
            for name in ("otp-cell-autofill.js", "account-otp-autofill.js"):
                with self.subTest(directory=directory, module=name):
                    self.assertFalse((THEME_ROOT / directory / name).exists())

    def test_no_layout_or_snippet_loads_a_second_otp_mutation_script(self) -> None:
        banned = ("otp-cell-autofill", "account-otp-autofill")
        for liquid in THEME_ROOT.rglob("*.liquid"):
            source = liquid.read_text(encoding="utf-8")
            with self.subTest(template=liquid.name):
                for name in banned:
                    self.assertNotIn(name, source)

    def test_no_theme_script_claims_one_time_code_fields(self) -> None:
        for path, source in self.scripts.items():
            with self.subTest(script=path.name):
                self.assertNotIn("one-time-code", source)
                self.assertNotIn("OTPCredential", source)

    def test_otp_aware_scripts_never_dispatch_synthetic_input(self) -> None:
        for path, source in self.scripts.items():
            if "#otp-form" not in source and "otp-input" not in source:
                continue
            with self.subTest(script=path.name):
                self.assertNotIn("new Event('input'", source)
                self.assertNotIn('new Event("input"', source)

    def test_account_otp_copy_is_visibility_only(self) -> None:
        for directory in ASSET_DIRECTORIES:
            source = code_only(
                (THEME_ROOT / directory / "account-otp-copy.js").read_text(encoding="utf-8")
            )
            with self.subTest(directory=directory):
                self.assertIn("hideEmailSignup", source)
                self.assertIn("control.hidden = true", source)
                self.assertNotIn("#otp-form", source)
                self.assertNotIn("otp-input", source)
                self.assertNotIn("dispatchEvent", source)
                self.assertNotIn(".value", source)
                self.assertNotIn("addEventListener('input'", source)
                self.assertNotIn('addEventListener("input"', source)
                self.assertNotIn("fetch(", source)
                self.assertNotIn("XMLHttpRequest", source)
                self.assertNotIn(".submit(", source)
                self.assertNotIn(".click(", source)

    def test_account_otp_copy_assets_are_identical(self) -> None:
        storefront = (THEME_ROOT / "assets" / "account-otp-copy.js").read_bytes()
        editor = (THEME_ROOT / "editor_assets" / "account-otp-copy.js").read_bytes()
        self.assertEqual(storefront, editor)

    def test_temporary_beforeinput_diagnostic_is_read_only_and_mirrored(self) -> None:
        name = "otp-beforeinput-diagnostic.js"
        storefront_path = THEME_ROOT / "assets" / name
        editor_path = THEME_ROOT / "editor_assets" / name

        self.assertTrue(storefront_path.exists())
        self.assertEqual(storefront_path.read_bytes(), editor_path.read_bytes())

        source = code_only(storefront_path.read_text(encoding="utf-8"))
        self.assertIn("cc_otp_diag", source)
        self.assertIn("addEventListener('beforeinput'", source)
        self.assertIn("addEventListener('input'", source)
        self.assertNotIn("preventDefault(", source)
        self.assertNotIn("stopPropagation(", source)
        self.assertNotIn("stopImmediatePropagation(", source)
        self.assertNotIn("dispatchEvent(", source)
        self.assertNotIn("new Event(", source)
        self.assertNotIn("new InputEvent(", source)
        self.assertNotIn("fetch(", source)
        self.assertNotIn("XMLHttpRequest", source)
        self.assertNotIn(".submit(", source)
        self.assertNotIn(".click(", source)
        self.assertNotRegex(source, r"\.value\s*=")
        self.assertNotRegex(source, r"setAttribute\s*\(\s*['\"]value['\"]")
        self.assertIn("'otp-beforeinput-diagnostic.js' | asset_url", self.currencies)


class ActivateAccountButtonTests(unittest.TestCase):
    """The activate template renders no ".btn", so its own inline handler threw
    a TypeError on every submit and the loading state never applied."""

    def test_the_activate_form_renders_the_button_its_script_looks_for(self) -> None:
        template = (
            THEME_ROOT / "templates" / "customers" / "activate_account.liquid"
        ).read_text(encoding="utf-8")
        self.assertIn("#form-activate .btn", template)
        self.assertIn('type="submit" class="btn"', template)


class NoGeneralizedAuthFlowScriptsTests(unittest.TestCase):
    """Keep broad account-submit interception out of the theme.

    Speculative theme scripts in the account flows caused the outage. Read-only
    step detection may keep redirects and history loads out of account setup,
    but no theme script may compete with EasyStore's own verification request.
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
