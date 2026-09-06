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


class OtpAutofillSafetyTests(unittest.TestCase):
    """Keep Android autofill to one platform-visible completion event.

    EasyStore owns the one-time-code widget and posts verification itself. The
    previous autofill helper spread all six digits before the browser's original
    first-cell input event reached EasyStore, then dispatched another input on
    the final cell. That depended on the platform submitting only from cell six.
    If EasyStore instead submits whenever all cells are complete, both events can
    post verification and the second request returns "Customer already exists
    (phone)".

    The current helper is narrower: it intercepts only an exact six-digit value
    in the captured six-cell plain-DOM widget, stops the original event at window
    capture while the DOM is still incomplete, then hands EasyStore one final-
    cell input event after the sixth digit is written. Unknown/framework-owned
    widgets, manual typing, partial values, and native paste stay platform-owned.
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

    def test_only_account_otp_copy_may_dispatch_synthetic_input(self) -> None:
        for path, source in self.scripts.items():
            if "#otp-form" not in source and "otp-input" not in source:
                continue
            if path.name == "account-otp-copy.js":
                continue
            with self.subTest(script=path.name):
                self.assertNotIn("new Event('input'", source)
                self.assertNotIn('new Event("input"', source)

    def test_account_otp_copy_has_one_narrow_completion_handoff(self) -> None:
        for directory in ASSET_DIRECTORIES:
            source = code_only(
                (THEME_ROOT / directory / "account-otp-copy.js").read_text(encoding="utf-8")
            )
            with self.subTest(directory=directory):
                self.assertIn("CELL_SELECTOR = '#otp-form .otp-input'", source)
                self.assertIn("CELL_COUNT = 6", source)
                self.assertIn("getAttribute('maxlength') !== '1'", source)
                self.assertIn("frameworkControlled(container)", source)
                self.assertIn("frameworkControlled(cell)", source)
                self.assertIn("event.stopImmediatePropagation()", source)
                self.assertIn(
                    "window.addEventListener('input', spreadFullOtpAutofill, true)",
                    source,
                )
                self.assertEqual(source.count("dispatchEvent(new Event('input'"), 1)
                self.assertNotIn("new Event('change'", source)
                self.assertNotIn('new Event("change"', source)
                self.assertNotIn("fetch(", source)
                self.assertNotIn("XMLHttpRequest", source)
                self.assertNotIn(".submit(", source)
                self.assertNotIn(".click(", source)

    def test_account_otp_copy_assets_are_identical(self) -> None:
        storefront = (THEME_ROOT / "assets" / "account-otp-copy.js").read_bytes()
        editor = (THEME_ROOT / "editor_assets" / "account-otp-copy.js").read_bytes()
        self.assertEqual(storefront, editor)


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

    The OTP autofill exception above is scoped to one captured widget and one
    completion event. It must not grow back into the generalized account form
    submit guards that previously competed with EasyStore's own auth flow.
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
