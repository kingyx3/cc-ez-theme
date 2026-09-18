"""Required account fields should tell the customer exactly what needs attention."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT / "theme" / "snippets" / "login-redirect-boot.liquid"


class AccountRequiredFieldCopyTests(unittest.TestCase):
    def test_profile_forms_use_field_specific_required_messages(self) -> None:
        source = BOOT.read_text(encoding="utf-8")

        self.assertIn("var profileFormSelector = '#details_form, #customer-attr-form';", source)
        self.assertIn("function labelFor(field)", source)
        self.assertIn(
            "'Please complete the \"' + labelFor(field) + '\" field.'",
            source,
        )

    def test_required_dropdown_placeholder_and_whitespace_are_missing(self) -> None:
        source = BOOT.read_text(encoding="utf-8")

        self.assertIn("selectedOption && selectedOption.disabled", source)
        self.assertIn("String(field.value || '').trim() === ''", source)
        self.assertIn("if (field.disabled)", source)

    def test_profile_forms_render_an_in_page_validation_summary_before_submit(self) -> None:
        source = BOOT.read_text(encoding="utf-8")

        self.assertIn("form.noValidate = true;", source)
        self.assertIn("document.addEventListener('submit', function (event)", source)
        self.assertIn("event.preventDefault();", source)
        self.assertIn("event.stopPropagation();", source)
        self.assertIn("showValidationSummary(form, invalid);", source)
        self.assertIn("'Please fix this field:'", source)
        self.assertIn("'Please fix these fields:'", source)
        self.assertIn("field.setAttribute('aria-invalid', 'true');", source)
        self.assertIn("if (first && first.focus) first.focus();", source)

    def test_account_page_reuses_its_existing_error_box(self) -> None:
        source = BOOT.read_text(encoding="utf-8")

        self.assertIn(
            "if (form.id === 'customer-attr-form') return document.getElementById('error-content');",
            source,
        )


if __name__ == "__main__":
    unittest.main()
