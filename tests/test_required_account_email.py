"""Regression coverage for the required account-details email field."""
from pathlib import Path
import re
import unittest


DETAILS = (
    Path(__file__).resolve().parents[1]
    / "theme"
    / "templates"
    / "customers"
    / "details.liquid"
)


class RequiredAccountEmailTests(unittest.TestCase):
    def test_account_details_email_is_required(self) -> None:
        source = DETAILS.read_text(encoding="utf-8")
        match = re.search(r'<input[^>]*id="DetailEmail"[^>]*>', source)
        self.assertIsNotNone(match, "account details email input is missing")
        self.assertRegex(match.group(0), r"\brequired\b")


if __name__ == "__main__":
    unittest.main()
