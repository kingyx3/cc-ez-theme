"""Regression coverage for the required account-details email field."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DETAILS = ROOT / "theme" / "templates" / "customers" / "details.liquid"
RUNTIME = ROOT / "theme" / "assets" / "account-recovery-copy.js"
EDITOR = ROOT / "theme" / "editor_assets" / "account-recovery-copy.js"


class RequiredAccountEmailTests(unittest.TestCase):
    def test_account_details_email_is_required(self) -> None:
        source = DETAILS.read_text(encoding="utf-8")
        match = re.search(r'<input[^>]*id="DetailEmail"[^>]*>', source)
        self.assertIsNotNone(match, "account details email input is missing")
        self.assertRegex(match.group(0), r"\brequired\b")

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

    def test_runtime_and_editor_helpers_stay_identical(self) -> None:
        self.assertEqual(
            RUNTIME.read_text(encoding="utf-8"),
            EDITOR.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
