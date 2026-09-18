"""Regression coverage for the required account-details email field."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DETAILS = ROOT / "theme" / "templates" / "customers" / "details.liquid"
LAYOUT = ROOT / "theme" / "layout" / "theme.liquid"
RUNTIME = ROOT / "theme" / "assets" / "account-details-validation.js"
EDITOR = ROOT / "theme" / "editor_assets" / "account-details-validation.js"


class RequiredAccountEmailTests(unittest.TestCase):
    def test_account_details_email_is_required(self) -> None:
        source = DETAILS.read_text(encoding="utf-8")
        match = re.search(r'<input[^>]*id="DetailEmail"[^>]*>', source)
        self.assertIsNotNone(match, "account details email input is missing")
        self.assertRegex(match.group(0), r"\brequired\b")

    def test_account_details_validation_helper_is_loaded(self) -> None:
        source = LAYOUT.read_text(encoding="utf-8")
        self.assertIn("'account-details-validation.js' | asset_url", source)

    def test_client_validation_catches_easystore_leading_punctuation_case(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const strictEmail = (value) =>", source)
        self.assertIn("/^[A-Za-z0-9](?:[A-Za-z0-9._%+\\-]*[A-Za-z0-9])?$/", source)
        self.assertIn("if (local.includes('..')) return false;", source)
        self.assertIn("Please enter a valid email address.", source)
        self.assertIn("-test@gmail.com", source)

    def test_server_validation_errors_restore_non_password_profile_values(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const DRAFT_KEY = 'cc:account-details-draft';", source)
        self.assertIn("const saveDraft = (form) =>", source)
        self.assertIn("const restoreDraft = (form) =>", source)
        self.assertIn("String(field.type || '').toLowerCase() !== 'password'", source)
        self.assertIn("invalid\\s+email\\s+address\\s+format", source)

    def test_server_errors_share_the_profile_validation_summary(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const ensureSummaryContainer = (form) =>", source)
        self.assertIn("data-profile-validation-summary", source)
        self.assertIn("data-profile-server-note", source)
        self.assertIn("data-profile-validation-note", source)
        self.assertIn("renderServerErrorsInSummary(form)", source)

    def test_correcting_email_clears_stale_server_format_error(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const clearResolvedEmailServerError = (form, field) =>", source)
        self.assertIn("invalid\\s+email\\s+address\\s+format", source)
        self.assertIn("clearResolvedEmailServerError(form, email);", source)

    def test_account_details_back_link_is_removed(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const removeBackLink = (form) =>", source)
        self.assertIn("a[href=\"/account\"]", source)
        self.assertIn("if (back) back.remove();", source)

    def test_cancel_and_submit_share_the_same_shape(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const alignActionButtons = (form) =>", source)
        self.assertIn("data-account-details-action", source)
        self.assertIn("min-width: 12rem !important;", source)
        self.assertIn("min-height: 4.4rem !important;", source)
        self.assertIn("border-radius: 1rem !important;", source)
        self.assertIn("border-radius: inherit !important;", source)

    def test_runtime_and_editor_helpers_stay_identical(self) -> None:
        self.assertEqual(
            RUNTIME.read_text(encoding="utf-8"),
            EDITOR.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
