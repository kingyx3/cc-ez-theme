from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


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

    def test_otp_fix_is_loaded_after_the_existing_global_assets(self) -> None:
        self.assertIn("otp-cell-autofill.js", self.currencies)
        self.assertIn('defer="defer"', self.currencies)

    def test_storefront_and_editor_scripts_match(self) -> None:
        self.assertEqual(self.storefront_script, self.editor_script)

    def test_autofilled_code_is_distributed_across_otp_cells(self) -> None:
        self.assertIn("const distributeOtpCode", self.storefront_script)
        self.assertIn("digits[index] || ''", self.storefront_script)
        self.assertIn("if (digits.length > 1)", self.storefront_script)
        self.assertIn("otpCodeDistributing", self.storefront_script)
        self.assertIn("cell.addEventListener('input'", self.storefront_script)

    def test_only_the_first_cell_requests_one_time_code_autofill(self) -> None:
        self.assertIn(
            "index === 0 ? 'one-time-code' : 'off'",
            self.storefront_script,
        )
        self.assertIn(
            "index === 0 ? String(cells.length) : '1'",
            self.storefront_script,
        )

    def test_email_fallback_is_hidden_during_mobile_otp(self) -> None:
        self.assertIn("continue\\s+with\\s+email\\s+instead", self.storefront_script)
        self.assertIn("element.hidden = true", self.storefront_script)
        self.assertIn("mobileOtpFallbackHidden", self.storefront_script)

    def test_dynamic_verification_markup_is_observed(self) -> None:
        self.assertIn("new MutationObserver", self.storefront_script)
        self.assertIn("enhanceWithin(document)", self.storefront_script)


if __name__ == "__main__":
    unittest.main()
