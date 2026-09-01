"""Mandatory first profile completion must require a password without route state."""
from __future__ import annotations

import unittest
from pathlib import Path


THEME = Path(__file__).resolve().parents[1] / "theme"
RUNTIME = THEME / "assets" / "account-login-redirect.js"
EDITOR = THEME / "editor_assets" / "account-login-redirect.js"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class FirstPasswordProfileCompletionTests(unittest.TestCase):
    def test_profile_gate_itself_requires_set_password(self) -> None:
        script = read(RUNTIME)

        self.assertIn("const requireProfileCompletionPassword = () => {", script)
        self.assertIn("document.getElementById('details_form')", script)
        self.assertIn("form.querySelector('[name=\"details[password2]\"]')", script)
        self.assertIn("password.setAttribute('required', 'required');", script)
        self.assertIn("password.setAttribute('autocomplete', 'new-password');", script)
        self.assertIn("password.setAttribute('placeholder', 'Set password');", script)
        self.assertIn("passwordLabel.textContent = 'Set password';", script)
        self.assertIn("saveArea.insertBefore(passwordWrapper, saveRow);", script)

    def test_profile_gate_does_not_depend_on_signup_session_marker(self) -> None:
        script = read(RUNTIME)
        gate = script[script.index("if (window.ccProfileCompletionRequired) {") :]

        self.assertIn("requireProfileCompletionPassword();", gate)
        self.assertNotIn("cc:signup-password-setup", script)
        self.assertNotIn("signupPasswordPending", script)
        self.assertNotIn("sessionStorage.getItem", gate.split("if (!signedIn()) return;", 1)[0])

    def test_normal_account_visit_does_not_promote_password(self) -> None:
        script = read(RUNTIME)
        gate = script[script.index("if (window.ccProfileCompletionRequired) {") :]

        self.assertIn("requireProfileCompletionPassword();\n      return;", gate)
        self.assertLess(
            gate.index("requireProfileCompletionPassword();"),
            gate.index("if (!signedIn()) return;"),
        )

    def test_runtime_and_editor_assets_stay_identical(self) -> None:
        self.assertEqual(read(RUNTIME), read(EDITOR))


if __name__ == "__main__":
    unittest.main()
