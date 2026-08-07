from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOGIN_TEMPLATE = ROOT / "theme" / "templates" / "customers" / "login.liquid"


class PasswordRecoveryCopyTest(unittest.TestCase):
    def setUp(self):
        self.template = LOGIN_TEMPLATE.read_text(encoding="utf-8")
        self.normalized_template = self.template.replace("\r\n", "\n")

    def test_recovery_paragraph_uses_the_platform_translation(self):
        expected = (
            "    <p>\n"
            "      {{ 'customer.recover_password.subtext' | t }}\n"
            "    </p>"
        )
        self.assertIn(expected, self.normalized_template)
        self.assertNotIn(
            "    <p>\n      Confirm your mobile to proceed\n    </p>",
            self.normalized_template,
        )

    def test_client_fallback_is_scoped_to_the_recovery_view_and_known_copy(self):
        expected_fragments = (
            "const recoveryPath = /\\/account\\/auth\\/?$/;",
            "window.location.hash === '#recover'",
            "const originalCopy = 'We will send you an email to reset your password.';",
            "const replacementCopy = 'Confirm your mobile to proceed';",
            "normaliseCopy(element.textContent || '') === originalCopy",
            "new MutationObserver(replaceRecoveryCopy)",
        )
        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.template)


if __name__ == "__main__":
    unittest.main()
