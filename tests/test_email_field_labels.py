from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAYOUT = ROOT / "theme" / "layout" / "theme.liquid"
RUNTIME_SCRIPT = ROOT / "theme" / "assets" / "email-field-label.js"
EDITOR_SCRIPT = ROOT / "theme" / "editor_assets" / "email-field-label.js"


class EmailFieldLabelsTest(unittest.TestCase):
    def test_layout_loads_email_field_label_script(self):
        self.assertIn(
            "<script src=\"{{ 'email-field-label.js' | asset_url }}\" defer=\"defer\"></script>",
            LAYOUT.read_text(encoding="utf-8"),
        )

    def test_account_details_email_label_is_repaired(self):
        script = RUNTIME_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("/\\/account\\/details(?:\\/|$)/i", script)
        self.assertIn("document.getElementById('DetailEmail')", script)
        self.assertIn("label.textContent = text", script)
        self.assertIn("field.classList.add('on_focus')", script)
        self.assertIn("const FALLBACK_LABEL = 'Email'", script)

    def test_checkout_email_fields_receive_floating_labels(self):
        script = RUNTIME_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("/\\/checkouts?(?:\\/|$)/i", script)
        self.assertIn("document.querySelectorAll('input')", script)
        self.assertIn("input.classList.remove('no-float-label')", script)
        self.assertIn("input.insertAdjacentElement('afterend', label)", script)

    def test_dynamically_rendered_target_fields_are_supported(self):
        script = RUNTIME_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("const isTargetPage = () => isCheckout() || isAccountDetails()", script)
        self.assertIn("new MutationObserver", script)
        self.assertIn("observer.observe(document.body, { childList: true, subtree: true })", script)

    def test_runtime_and_editor_scripts_stay_in_sync(self):
        self.assertEqual(
            RUNTIME_SCRIPT.read_text(encoding="utf-8"),
            EDITOR_SCRIPT.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
