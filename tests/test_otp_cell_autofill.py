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
        cls.legacy_enhancements = (
            THEME_ROOT / "assets" / "search-history.js"
        ).read_text(encoding="utf-8")

    def test_otp_owner_runs_before_the_deferred_legacy_helper(self) -> None:
        loader = '<script src="{{ \'otp-cell-autofill.js\' | asset_url }}"></script>'
        self.assertIn(loader, self.currencies)
        self.assertNotIn(
            "'otp-cell-autofill.js' | asset_url }}\" defer",
            self.currencies,
        )
        self.assertIn(
            "form.dataset.webOtpRequested === 'true'",
            self.legacy_enhancements,
        )
        self.assertIn(
            "form.dataset.webOtpRequested = 'true'",
            self.storefront_script,
        )
        self.assertIn(
            "form.dataset.otpEnhancementOwner = 'otp-cell-autofill'",
            self.storefront_script,
        )

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

    def test_duplicate_otp_submissions_are_blocked(self) -> None:
        self.assertIn("const SUBMISSION_LOCK_MS = 10000", self.storefront_script)
        self.assertIn("const guardOtpSubmission", self.storefront_script)
        self.assertIn("otpSubmissionGuardBound", self.storefront_script)
        self.assertIn("otpSubmissionInFlight", self.storefront_script)
        self.assertIn("event.preventDefault()", self.storefront_script)
        self.assertIn("event.stopImmediatePropagation()", self.storefront_script)
        self.assertLess(
            self.storefront_script.index("guardOtpSubmission(form)"),
            self.storefront_script.index("enhanceOtpCells(form, cells)"),
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
