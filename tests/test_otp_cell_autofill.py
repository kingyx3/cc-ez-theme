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
    submit-event guard cannot deduplicate it from the theme side.

    The widget has since been read rather than guessed at, with
    scripts/otp-widget-capture.console.js and scripts/otp-handler-probe.console.js,
    and `submitOTP()` turns out to have exactly one trigger - an input event on
    the last of the six cells. account-otp-autofill.js spreads an autofilled code
    on that evidence and emits that one event, so these assertions no longer ban
    every write. What they still ban is the reverted design: the old module and
    its loader, the WebOTP path that had a second script writing into the same
    cells, and the per-cell event storm. The count that actually matters - one
    submit, never two - is asserted behaviourally in e2e/otp-autofill.spec.js
    against a replica of the real widget.
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

    def test_no_theme_script_restores_the_reverted_modules_internals(self) -> None:
        # The double submit came from dispatching input *and* change on every
        # cell. Its helpers stay banned by name so the design cannot come back
        # by copy-paste.
        for path, source in self.scripts.items():
            with self.subTest(script=path.name):
                self.assertNotIn("distributeOtpCode", source)
                self.assertNotIn("otpCell", source)


class OtpAutofillModuleTests(unittest.TestCase):
    """account-otp-autofill.js spreads an autofilled code across the six cells.

    The widget's own handler submits from exactly one place - an input event on
    the last cell - so the module's safety reduces to which events it emits.
    e2e/otp-autofill.spec.js proves the resulting count against a replica; these
    assertions keep the source honest about how it gets there.
    """

    MODULE = "account-otp-autofill.js"

    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = {
            directory: code_only(
                (THEME_ROOT / directory / cls.MODULE).read_text(encoding="utf-8")
            )
            for directory in ASSET_DIRECTORIES
        }

    def test_the_module_ships_to_both_asset_mirrors_identically(self) -> None:
        bodies = {
            directory: (THEME_ROOT / directory / self.MODULE).read_text(encoding="utf-8")
            for directory in ASSET_DIRECTORIES
        }
        for directory in ASSET_DIRECTORIES:
            with self.subTest(directory=directory):
                self.assertTrue((THEME_ROOT / directory / self.MODULE).exists())
        self.assertEqual(bodies["assets"], bodies["editor_assets"])

    def test_the_layout_loads_it(self) -> None:
        layout = (THEME_ROOT / "layout" / "theme.liquid").read_text(encoding="utf-8")
        self.assertIn(self.MODULE, layout)

    def test_it_dispatches_input_and_never_change(self) -> None:
        # A change event is what the reverted module added on top of input, and
        # widgets that submit on change are why that doubled the POST.
        for directory, source in self.sources.items():
            with self.subTest(directory=directory):
                self.assertIn("new Event('input'", source)
                self.assertNotIn("'change'", source)
                self.assertNotIn('"change"', source)

    def test_it_only_ever_dispatches_on_the_last_cell(self) -> None:
        # One dispatch site, and it is the cell the widget submits from.
        for directory, source in self.sources.items():
            with self.subTest(directory=directory):
                self.assertEqual(source.count("dispatchEvent"), 1)
                self.assertIn("cells[cells.length - 1]", source)

    def test_it_latches_so_one_code_is_handed_over_once(self) -> None:
        # Autofill can fire input more than once for a single suggestion.
        for directory, source in self.sources.items():
            with self.subTest(directory=directory):
                self.assertIn("handedOver", source)

    def test_it_only_completes_when_every_cell_is_filled(self) -> None:
        # Otherwise a short autofill would post an incomplete verification.
        for directory, source in self.sources.items():
            with self.subTest(directory=directory):
                self.assertIn("complete", source)
                self.assertIn("every", source)

    def test_it_is_scoped_to_the_platform_widget(self) -> None:
        # The captured markup: six .otp-input cells inside #otp-form.
        for directory, source in self.sources.items():
            with self.subTest(directory=directory):
                self.assertIn("#otp-form .otp-input", source)


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
