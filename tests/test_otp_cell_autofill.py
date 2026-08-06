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
        self.assertIn("const isPlausibleOtpGroup", self.storefront_script)
        self.assertIn("const cellLikeCount", self.storefront_script)
        self.assertIn("const group = findGroupAroundAnchor(anchor, form)", self.storefront_script)

    def test_autofill_is_caught_before_and_after_browser_insertion(self) -> None:
        self.assertIn("cell.addEventListener('beforeinput'", self.storefront_script)
        self.assertIn("cell.addEventListener('input'", self.storefront_script)
        self.assertIn("documentObject.addEventListener('beforeinput'", self.storefront_script)
        self.assertIn("documentObject.addEventListener('input'", self.storefront_script)
        self.assertIn("setNativeInputValue", self.storefront_script)
        self.assertIn("distributeOtpCode(cells, digits", self.storefront_script)

    def test_email_fallback_is_removed_independently_of_exact_form_names(self) -> None:
        self.assertIn("const removeEmailFallback", self.storefront_script)
        self.assertIn("EMAIL_FALLBACK_PATTERN", self.storefront_script)
        self.assertIn("element.remove()", self.storefront_script)
        self.assertIn("if (pageLooksRelevant) removeEmailFallback(documentObject)", self.storefront_script)

    def test_dynamic_and_delayed_autofill_is_rechecked(self) -> None:
        self.assertIn("new windowObject.MutationObserver(run)", self.storefront_script)
        self.assertIn("windowObject.setInterval", self.storefront_script)
        self.assertIn("if (digits.length > 1) distributeOtpCode", self.storefront_script)

    def test_runtime_regression_for_real_six_cell_shape(self) -> None:
        completed = subprocess.run(
            ["node", str(RUNTIME_TEST)],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("OTP runtime regression passed", completed.stdout)


if __name__ == "__main__":
    unittest.main()
