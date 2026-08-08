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


class OtpWidgetProbeTests(unittest.TestCase):
    """The probe is how the split-autofill complaint gets unblocked.

    The verification widget is EasyStore's, so its markup cannot be read from
    this repository and a fix cannot be designed without it. The probe captures
    that markup and the widget's own request behaviour from a live page. It has
    to stay strictly passive: the outage above came from theme code writing into
    those cells, and a diagnostic that did the same would reproduce it.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.path = REPOSITORY_ROOT / "scripts" / "otp-widget-probe.console.js"
        cls.script = cls.path.read_text(encoding="utf-8")
        cls.code = code_only(cls.script)

    def test_the_probe_is_available(self) -> None:
        self.assertTrue(self.path.exists())

    def test_the_probe_never_ships_with_the_theme(self) -> None:
        # scripts/ is excluded from the ZIP (docs/PACKAGING_AND_DEPLOYMENT.md),
        # so the probe only ever runs when it is pasted into a console by hand.
        for directory in ASSET_DIRECTORIES:
            with self.subTest(directory=directory):
                self.assertFalse(
                    (THEME_ROOT / directory / "otp-widget-probe.console.js").exists()
                )
        for liquid in THEME_ROOT.rglob("*.liquid"):
            with self.subTest(template=liquid.name):
                self.assertNotIn(
                    "otp-widget-probe", liquid.read_text(encoding="utf-8")
                )

    def test_the_probe_writes_nothing_into_the_cells(self) -> None:
        # Exactly the operations that broke signup. A read-only diagnostic needs
        # none of them.
        self.assertNotIn("dispatchEvent", self.code)
        self.assertNotIn("preventDefault", self.code)
        self.assertNotIn("stopPropagation", self.code)
        self.assertNotIn("cell.value =", self.code)
        self.assertNotIn(".focus()", self.code)
        self.assertNotIn("OTPCredential", self.code)

    def test_the_probe_leaves_the_page_as_it_found_it(self) -> None:
        # fetch and XHR are wrapped so requests can be counted; the originals
        # are always called and always restorable.
        self.assertIn("return originalFetch.apply(this, arguments)", self.code)
        self.assertIn("return originalOpen.apply(this, arguments)", self.code)
        self.assertIn("return originalSend.apply(this, arguments)", self.code)
        self.assertIn("window.fetch = originalFetch", self.code)
        self.assertIn("XMLHttpRequest.prototype.open = originalOpen", self.code)
        self.assertIn("XMLHttpRequest.prototype.send = originalSend", self.code)

    def test_the_probe_reports_what_a_fix_actually_needs(self) -> None:
        # Attributes that decide whether autofill can be fixed without writing
        # values, plus the count of requests the widget makes by itself.
        for attribute in ("maxlength", "autocomplete", "inputmode", "pattern"):
            with self.subTest(attribute=attribute):
                self.assertIn(attribute, self.code)
        self.assertIn("POSTs while recording", self.code)
        self.assertIn("cell lengths", self.code)

    def test_the_probe_masks_secrets_but_not_structure(self) -> None:
        # A shared report must not carry a live code or the phone number it was
        # sent to. maxlength must survive masking - "maxlength=1" against
        # "maxlength=6" is the finding.
        self.assertIn("SENSITIVE_ATTRIBUTES", self.code)
        self.assertIn("SHOW_TEXT", self.code)
        for structural in ("maxlength", "size", "pattern"):
            with self.subTest(attribute=structural):
                self.assertNotIn(f"'{structural}'", self.code.split("SENSITIVE_ATTRIBUTES = [")[1].split("]")[0])


if __name__ == "__main__":
    unittest.main()
