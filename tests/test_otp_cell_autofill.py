from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"
RUNTIME_TEST = REPOSITORY_ROOT / "tests" / "otp_cell_autofill_runtime_test.js"


class OtpCellAutofillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.storefront_script = (
            THEME_ROOT / "assets" / "otp-cell-autofill.js"
        ).read_text(encoding="utf-8")
        cls.editor_script = (
            THEME_ROOT / "editor_assets" / "otp-cell-autofill.js"
        ).read_text(encoding="utf-8")
        cls.currencies = (
            THEME_ROOT / "snippets" / "currencies.liquid"
        ).read_text(encoding="utf-8")

    def test_otp_fix_is_loaded_globally(self) -> None:
        self.assertIn("otp-cell-autofill.js", self.currencies)
        self.assertIn('defer="defer"', self.currencies)

    def test_storefront_and_editor_scripts_match(self) -> None:
        self.assertEqual(self.storefront_script, self.editor_script)

    def test_generic_sibling_cells_are_grouped_from_one_otp_anchor(self) -> None:
        self.assertIn("const findGroupAroundAnchor", self.storefront_script)
        self.assertIn("const plausibleGroup", self.storefront_script)
        self.assertIn("const group = findGroupAroundAnchor(anchor, form)", self.storefront_script)

    def test_browser_autofill_targets_a_dedicated_six_digit_receiver(self) -> None:
        self.assertIn("const createOtpProxy", self.storefront_script)
        self.assertIn("data-otp-autofill-proxy", self.storefront_script)
        self.assertIn("setAttr(proxy, 'autocomplete', 'one-time-code')", self.storefront_script)
        self.assertIn("setAttr(proxy, 'maxlength', String(cells.length))", self.storefront_script)
        self.assertIn("setAttr(cell, 'autocomplete', 'off')", self.storefront_script)
        self.assertIn("setAttr(cell, 'maxlength', '1')", self.storefront_script)
        self.assertIn("syncCellsFromCode(proxy.__otpCells", self.storefront_script)

    def test_email_fallback_is_removed_independently_of_exact_form_names(self) -> None:
        self.assertIn("const removeEmailFallback", self.storefront_script)
        self.assertIn("EMAIL_FALLBACK_PATTERN", self.storefront_script)
        self.assertIn("element.remove()", self.storefront_script)
        self.assertIn("removeEmailFallback(documentObject)", self.storefront_script)

    def test_dynamic_and_eventless_autofill_is_rechecked(self) -> None:
        self.assertIn("new windowObject.MutationObserver(run)", self.storefront_script)
        self.assertIn("windowObject.setInterval", self.storefront_script)
        self.assertIn("proxy.dataset.lastOtpValue", self.storefront_script)
        self.assertIn("if (current !== previous)", self.storefront_script)

    def test_runtime_regression_for_platform_clipped_six_cell_shape(self) -> None:
        completed = subprocess.run(
            ["node", str(RUNTIME_TEST)],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("OTP proxy runtime regression passed", completed.stdout)


if __name__ == "__main__":
    unittest.main()
