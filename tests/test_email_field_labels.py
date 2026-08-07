from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAYOUT = ROOT / "theme" / "layout" / "theme.liquid"
DETAILS = ROOT / "theme" / "templates" / "customers" / "details.liquid"
FALLBACK = ROOT / "theme" / "snippets" / "translation-fallback.liquid"
SCRIPT = ROOT / "theme" / "assets" / "email-field-label.js"
EDITOR_SCRIPT = ROOT / "theme" / "editor_assets" / "email-field-label.js"


class EmailFieldLabelsTest(unittest.TestCase):
    def test_layout_loads_email_field_label_script(self):
        self.assertIn(
            "<script src=\"{{ 'email-field-label.js' | asset_url }}\" defer=\"defer\"></script>",
            LAYOUT.read_text(encoding="utf-8"),
        )

    def test_account_details_renders_a_nonempty_email_title(self):
        details = DETAILS.read_text(encoding="utf-8")
        email_lines = "\n".join(
            line for line in details.splitlines() if "DetailEmail" in line
        )

        self.assertIn('id="DetailEmail"', email_lines)
        self.assertIn('name="details[email]"', email_lines)
        self.assertIn('<label for="DetailEmail">', email_lines)
        self.assertEqual(2, email_lines.count("translation-fallback"))
        self.assertEqual(2, email_lines.count("translation_key: 'customer.login.email'"))
        self.assertEqual(2, email_lines.count("fallback: 'Email'"))
        self.assertNotIn("'customer.login.email' | t", email_lines)

    def test_translation_fallback_handles_empty_platform_values(self):
        fallback = FALLBACK.read_text(encoding="utf-8")
        self.assertIn("translation_fallback_probe == ''", fallback)
        self.assertIn("| append: '' | strip", fallback)
        self.assertIn("translation_fallback_probe == translation_key", fallback)
        self.assertIn("contains 'translation missing'", fallback)

    def test_account_email_label_is_repaired_after_runtime_mutations(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("document.getElementById('DetailEmail')", script)
        self.assertIn("const FALLBACK_LABEL = 'Email'", script)
        self.assertIn("field.classList.add('on_focus')", script)
        self.assertIn("label.textContent = text", script)
        self.assertIn("attributes: true", script)
        self.assertIn("characterData: true", script)
        self.assertIn("'hidden', 'aria-hidden'", script)

    def test_hidden_account_label_is_forced_visible(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("label.classList.remove('label--hidden', 'visually-hidden', 'hidden', 'hide')", script)
        self.assertIn("label.style.removeProperty('display')", script)
        self.assertIn("label.style.setProperty('display', 'block', 'important')", script)
        self.assertIn("label.style.setProperty('visibility', 'visible', 'important')", script)
        self.assertIn("label.style.setProperty('opacity', '1', 'important')", script)

    def test_checkout_email_fields_receive_floating_labels(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("/\\/checkouts?(?:\\/|$)/i", script)
        self.assertIn("document.querySelectorAll('input')", script)
        self.assertIn("input.classList.remove('no-float-label')", script)
        self.assertIn("input.insertAdjacentElement('afterend', label)", script)
        self.assertIn("field.classList.add('on_focus')", script)

    def test_dynamically_rendered_fields_are_supported(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("new MutationObserver(queueRepair)", script)
        self.assertIn("childList: true", script)
        self.assertIn("subtree: true", script)
        self.assertIn("window.requestAnimationFrame", script)

    def test_runtime_and_editor_scripts_stay_in_sync(self):
        self.assertEqual(
            SCRIPT.read_text(encoding="utf-8"),
            EDITOR_SCRIPT.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
