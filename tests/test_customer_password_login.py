"""Password remains the primary theme-rendered customer authentication method."""
from __future__ import annotations

import re
import unittest
from pathlib import Path


THEME = Path(__file__).resolve().parents[1] / "theme"
LOGIN = THEME / "templates" / "customers" / "login.liquid"
REGISTER = THEME / "templates" / "customers" / "register.liquid"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def input_tag(source: str, name: str) -> str:
    match = re.search(
        rf"<input\b(?=[^>]*\bname=\"{re.escape(name)}\")[^>]*>",
        source,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError(f"missing input {name}")
    return match.group(0)


class CustomerPasswordLoginTests(unittest.TestCase):
    def test_returning_customer_form_requires_password(self) -> None:
        login = read(LOGIN)
        password = input_tag(login, "customer[password]")

        self.assertIn('type="password"', password)
        self.assertIn('autocomplete="current-password"', password)
        self.assertRegex(password, r"\brequired\b")
        self.assertIn('action="/account/login"', login)

    def test_password_submit_precedes_optional_login_methods(self) -> None:
        login = read(LOGIN)

        password_position = login.index('name="customer[password]"')
        submit_position = login.index("{{ 'customer.login.sign_in' | t }}", password_position)
        alternate_position = login.index("{% app_snippet 'login/button' %}")

        self.assertLess(password_position, submit_position)
        self.assertLess(submit_position, alternate_position)

    def test_registration_template_keeps_a_required_password_fallback(self) -> None:
        register = read(REGISTER)
        password = input_tag(register, "customer[password]")

        self.assertIn('type="password"', password)
        self.assertRegex(password, r"\brequired\b")


if __name__ == "__main__":
    unittest.main()
