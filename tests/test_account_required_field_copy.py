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
        self.assertIn("'details[gender]': 'Gender'", source)
        self.assertIn("'details[birthdate]': 'Date of Birth'", source)
        self.assertIn("'details[email]': 'Email'", source)
        self.assertIn("fieldLabel ? 'Please complete the \"' + fieldLabel + '\" field.'", source)
        self.assertIn(": 'Please complete this field.'", source)
        self.assertNotIn("return 'required field';", source)

    def test_label_lookup_uses_rendered_controls_before_generic_copy(self) -> None:
        source = BOOT.read_text(encoding="utf-8")

        self.assertIn("field.labels && field.labels.length", source)
        self.assertIn("field.closest('.field')", source)
        self.assertIn("field.getAttribute('aria-label')", source)
        self.assertIn("field.getAttribute('placeholder')", source)
        self.assertIn("field.options[field.selectedIndex]", source)
        self.assertIn("optionText.replace(/^select\\s+/i, '')", source)
        self.assertIn("var match = name.match(/\\[([^\\[\\]]+)\\]$/);", source)

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

    def test_validation_summary_deduplicates_controls_with_the_same_label(self) -> None:
        source = BOOT.read_text(encoding="utf-8")

        self.assertIn("var seenLabels = {};", source)
        self.assertIn("if (labelKey && seenLabels[labelKey]) return;", source)
        self.assertIn("if (labelKey) seenLabels[labelKey] = true;", source)
        self.assertIn("heading.textContent = list.children.length === 1", source)

    def test_account_page_reuses_its_existing_error_box(self) -> None:
        source = BOOT.read_text(encoding="utf-8")

        self.assertIn(
            "if (form.id === 'customer-attr-form') return document.getElementById('error-content');",
            source,
        )


if __name__ == "__main__":
    unittest.main()
