"""First password creation must stay on EasyStore's registration contract."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"
REGISTER = THEME / "templates" / "customers" / "register.liquid"
LOGIN = THEME / "templates" / "customers" / "login.liquid"
DETAILS = THEME / "templates" / "customers" / "details.liquid"
BOOT = THEME / "snippets" / "login-redirect-boot.liquid"
RUNTIME = THEME / "assets" / "account-login-redirect.js"
EDITOR = THEME / "editor_assets" / "account-login-redirect.js"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class FirstPasswordProfileCompletionTests(unittest.TestCase):
    def test_registration_contract_creates_the_first_password(self) -> None:
        register = read(REGISTER)

        self.assertIn('action="/account/register"', register)
        marker = 'name="customer[password]"'
        self.assertIn(marker, register)
        field = register[register.index(marker) - 200 : register.index(marker) + 350]
        self.assertIn('type="password"', field)
        self.assertIn("required", field)

    def test_profile_details_password_pair_is_change_password_only(self) -> None:
        details = read(DETAILS)
        boot = read(BOOT)
        runtime = read(RUNTIME)

        self.assertIn('name="details[password1]"', details)
        self.assertIn('name="details[password2]"', details)
        self.assertNotIn('querySelector(\'[name="details[password1]"]\')', boot)
        self.assertNotIn('querySelector(\'[name="details[password2]"]\')', boot)
        self.assertNotIn('details[password2]', runtime)
        self.assertNotIn("requireProfileCompletionPassword", runtime)

    def test_profile_gate_waits_for_native_first_password_markup(self) -> None:
        boot = read(BOOT)

        self.assertIn("function nativeFirstPasswordStep()", boot)
        self.assertIn('input[name="customer[password]"]', boot)
        self.assertIn('/^\\/account\\/login(?:[?#]|$)/i.test(action)', boot)
        self.assertIn("function routeAfterNativeAccountSetup()", boot)
        self.assertIn("if (nativeFirstPasswordStep()) return;", boot)
        self.assertIn("document.addEventListener('DOMContentLoaded', routeAfterNativeAccountSetup);", boot)

        route = boot[boot.index("function routeAfterNativeAccountSetup()") :]
        self.assertLess(
            route.index("if (nativeFirstPasswordStep()) return;"),
            route.index("window.location.replace(PROFILE_PATH);"),
        )

    def test_returning_customer_theme_login_is_password_first(self) -> None:
        login = read(LOGIN)

        password = login.index('name="customer[password]"')
        submit = login.index('<button type="submit" class="btn">', password)
        optional_methods = login.index("{% app_snippet 'login/button' %}", submit)
        self.assertLess(password, submit)
        self.assertLess(submit, optional_methods)
        self.assertIn('autocomplete="current-password"', login[password - 200 : password + 300])

    def test_runtime_and_editor_assets_stay_identical(self) -> None:
        self.assertEqual(read(RUNTIME), read(EDITOR))


if __name__ == "__main__":
    unittest.main()
