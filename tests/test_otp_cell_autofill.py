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


class OtpSameEventAutofillSafetyTests(unittest.TestCase):
    """Regression guard for Android autofill and duplicate verification.

    Real-device testing showed Android inserting all six SMS digits into the
    first EasyStore OTP cell as one trusted, non-cancelable input event, with no
    beforeinput. The safe theme handoff may synchronously split those six plain
    DOM values during capture of that same event. It must never manufacture a
    replacement event or compete with EasyStore's verification request.

    The earlier synthetic-event design could make EasyStore verify twice: the
    first request created the customer and a second request surfaced "Customer
    already exists (phone)". These tests keep that failure mode impossible.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.scripts = {
            path: code_only(path.read_text(encoding="utf-8"))
            for directory in ASSET_DIRECTORIES
            for path in sorted((THEME_ROOT / directory).glob("*.js"))
        }

    def test_legacy_otp_mutation_modules_stay_removed(self) -> None:
        for directory in ASSET_DIRECTORIES:
            for name in ("otp-cell-autofill.js", "account-otp-autofill.js"):
                with self.subTest(directory=directory, module=name):
                    self.assertFalse((THEME_ROOT / directory / name).exists())

    def test_temporary_preview_helper_is_removed(self) -> None:
        for directory in ASSET_DIRECTORIES:
            with self.subTest(directory=directory):
                self.assertFalse(
                    (THEME_ROOT / directory / "otp-same-event-preview.js").exists()
                )

    def test_no_layout_or_snippet_loads_a_legacy_otp_mutation_script(self) -> None:
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
                self.assertNotIn("dispatchEvent", source)
                self.assertNotIn("new Event('input'", source)
                self.assertNotIn('new Event("input"', source)
                self.assertNotIn("new InputEvent", source)

    def test_account_otp_copy_only_hides_copy_and_loads_the_narrow_helper(self) -> None:
        for directory in ASSET_DIRECTORIES:
            source = code_only(
                (THEME_ROOT / directory / "account-otp-copy.js").read_text(encoding="utf-8")
            )
            with self.subTest(directory=directory):
                self.assertIn("hideEmailSignup", source)
                self.assertIn("control.hidden = true", source)
                self.assertIn("otp-same-event-autofill.js", source)
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
                self.assertNotIn("otpdiag", source)

    def test_same_event_helper_has_fail_closed_guards_and_no_verification_side_effects(self) -> None:
        forbidden = (
            "dispatchEvent",
            "preventDefault",
            "stopPropagation",
            "stopImmediatePropagation",
            "fetch(",
            "XMLHttpRequest",
            ".submit(",
            ".click(",
            "sessionStorage",
            "otpdiag",
        )

        for directory in ASSET_DIRECTORIES:
            source = code_only(
                (THEME_ROOT / directory / "otp-same-event-autofill.js").read_text(
                    encoding="utf-8"
                )
            )
            with self.subTest(directory=directory):
                self.assertIn("event.isTrusted !== true", source)
                self.assertIn("/^\\d{6}$/", source)
                self.assertIn("cells[0] !== event.target", source)
                self.assertIn("cells.slice(1).every", source)
                self.assertIn("cell.value = code[index]", source)
                self.assertIn("window.addEventListener('input'", source)
                self.assertIn("capture: true", source)
                self.assertIn("passive: true", source)
                for token in forbidden:
                    self.assertNotIn(token, source)

    def test_otp_assets_are_mirrored_byte_for_byte(self) -> None:
        for name in ("account-otp-copy.js", "otp-same-event-autofill.js"):
            with self.subTest(asset=name):
                storefront = (THEME_ROOT / "assets" / name).read_bytes()
                editor = (THEME_ROOT / "editor_assets" / name).read_bytes()
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

    The OTP helper may change six DOM values during one trusted browser input,
    but no theme script may compete with EasyStore's own verification request or
    generalize that behavior into account-submit interception.
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
