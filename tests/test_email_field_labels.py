from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAYOUT = ROOT / "theme" / "layout" / "theme.liquid"
DETAILS = ROOT / "theme" / "templates" / "customers" / "details.liquid"
SCRIPT = ROOT / "theme" / "assets" / "email-field-label.js"
EDITOR_SCRIPT = ROOT / "theme" / "editor_assets" / "email-field-label.js"


class EmailFieldLabelsTest(unittest.TestCase):
    def test_layout_loads_email_field_label_script(self):
        self.assertIn(
            "<script src=\"{{ 'email-field-label.js' | asset_url }}\" defer=\"defer\"></script>",
            LAYOUT.read_text(encoding="utf-8"),
        )

    def test_account_details_email_label_is_server_rendered(self):
        details = DETAILS.read_text(encoding="utf-8")
        self.assertIn(
            "{% include 'translation-fallback', translation_key: 'customer.login.email', fallback: 'Email' %}",
            details,
        )
        self.assertIn('<div class="field on_focus">', details)
        self.assertIn(
            'value="{{ customer.cust_email | _default: customer.email | escape }}"',
            details,
        )
        self.assertIn(
            'placeholder="{{ account_email_label | strip | escape }}"', details
        )
        self.assertIn(
            '<label for="DetailEmail">{{ account_email_label | strip }}</label>',
            details,
        )

    def test_account_details_does_not_depend_on_javascript_repair(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("DetailEmail", script)
        self.assertNotIn("ACCOUNT_DETAILS_PATH", script)

    def test_checkout_email_fields_receive_floating_labels(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("/\\/checkouts?(?:\\/|$)/i", script)
        self.assertIn("document.querySelectorAll('input')", script)
        self.assertIn("input.classList.remove('no-float-label')", script)
        self.assertIn("input.insertAdjacentElement('afterend', label)", script)
        self.assertIn("field.classList.add('on_focus')", script)

    def test_dynamically_rendered_checkout_fields_are_supported(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("new MutationObserver", script)
        self.assertIn(
            "observer.observe(document.body, { childList: true, subtree: true })",
            script,
        )

    def test_runtime_and_editor_scripts_stay_in_sync(self):
        self.assertEqual(
            SCRIPT.read_text(encoding="utf-8"),
            EDITOR_SCRIPT.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
