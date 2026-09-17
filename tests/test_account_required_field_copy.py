"""Required account fields should tell the customer what is missing."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT / "theme" / "snippets" / "login-redirect-boot.liquid"


class AccountRequiredFieldCopyTests(unittest.TestCase):
    def test_profile_forms_use_field_specific_required_messages(self) -> None:
        source = BOOT.read_text(encoding="utf-8")

        self.assertIn("var profileFormSelector = '#details_form, #customer-attr-form';", source)
        self.assertIn(
            "var profileRequiredSelector = '#details_form [required], #customer-attr-form [required]';",
            source,
        )
        self.assertIn("function labelFor(field)", source)
        self.assertIn(
            "'Please complete the \"' + labelFor(field) + '\" field.'",
            source,
        )

    def test_required_dropdown_placeholder_is_treated_as_missing(self) -> None:
        source = BOOT.read_text(encoding="utf-8")

        self.assertIn("field.tagName === 'SELECT'", source)
        self.assertIn("selectedOption && selectedOption.disabled", source)
        self.assertIn("field.validity.valueMissing", source)


if __name__ == "__main__":
    unittest.main()
