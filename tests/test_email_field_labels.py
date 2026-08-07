from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DETAILS = ROOT / "theme" / "templates" / "customers" / "details.liquid"
FALLBACK = ROOT / "theme" / "snippets" / "translation-fallback.liquid"


class EmailFieldLabelsTest(unittest.TestCase):
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
        self.assertIn("translated_value == blank", fallback)
        self.assertIn("translation_fallback_probe == ''", fallback)
        self.assertIn("| append: '' | strip", fallback)
        self.assertIn("translation_fallback_probe == translation_key", fallback)
        self.assertIn("contains 'translation missing'", fallback)

    def test_email_field_keeps_the_customer_value(self):
        details = DETAILS.read_text(encoding="utf-8")
        email_lines = "\n".join(
            line for line in details.splitlines() if "DetailEmail" in line
        )
        self.assertIn('value="{{customer.cust_email}}"', email_lines)


if __name__ == "__main__":
    unittest.main()
