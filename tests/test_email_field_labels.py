from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAYOUT = ROOT / "theme" / "layout" / "theme.liquid"
SCRIPT = ROOT / "theme" / "assets" / "email-field-label.js"


class EmailFieldLabelsTest(unittest.TestCase):
    def test_layout_loads_email_field_label_script(self):
        self.assertIn(
            "<script src=\"{{ 'email-field-label.js' | asset_url }}\" defer=\"defer\"></script>",
            LAYOUT.read_text(encoding="utf-8"),
        )

    def test_account_details_email_label_is_repaired(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("document.getElementById('DetailEmail')", script)
        self.assertIn("ensureEmailLabel", script)
        self.assertIn("label.textContent = text", script)

    def test_checkout_email_fields_receive_floating_labels(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("/\\/checkouts?(?:\\/|$)/i", script)
        self.assertIn("document.querySelectorAll('input')", script)
        self.assertIn("input.classList.remove('no-float-label')", script)
        self.assertIn("input.insertAdjacentElement('afterend', label)", script)

    def test_dynamically_rendered_checkout_fields_are_supported(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("new MutationObserver", script)
        self.assertIn("observer.observe(document.body, { childList: true, subtree: true })", script)


if __name__ == "__main__":
    unittest.main()
