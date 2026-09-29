"""A bare Singapore mobile number must not be sent to EasyStore ambiguously.

Typing the local 8-digit number "96556718" (no leading "+") into the
login/register/recover mobile field sent that ambiguous string straight to
EasyStore, which read it as Kuwait's "+965" calling code plus a 5-digit
remainder instead of this store's own Singapore number - sending the OTP to
the wrong country. The `mobile-number-normalize` snippet rewrites a bare
local SG mobile to an explicit "+65" value before each form submits.
"""
from __future__ import annotations

import unittest
from pathlib import Path


THEME = Path(__file__).resolve().parents[1] / "theme"
LOGIN = THEME / "templates" / "customers" / "login.liquid"
REGISTER = THEME / "templates" / "customers" / "register.liquid"
SNIPPET = THEME / "snippets" / "mobile-number-normalize.liquid"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class MobileNumberNormalizeSnippetTests(unittest.TestCase):
    def test_snippet_only_rewrites_bare_local_or_partial_sg_numbers(self) -> None:
        snippet = read(SNIPPET)
        self.assertIn("window.ccNormalizeSgMobile", snippet)
        # An email or an already-"+"-prefixed value is returned untouched.
        self.assertIn("trimmed.indexOf('@') !== -1", snippet)
        self.assertIn("trimmed.charAt(0) === '+'", snippet)
        # Only a bare 8-digit local mobile or an SG number missing its "+" is
        # rewritten -- anything else is left exactly as typed.
        self.assertIn(r"/^65\d{8}$/", snippet)
        self.assertIn(r"/^[89]\d{7}$/", snippet)


class LoginFormWiringTests(unittest.TestCase):
    def test_recover_and_login_fields_are_normalized_before_submit(self) -> None:
        login = read(LOGIN)
        self.assertIn("{% include 'mobile-number-normalize' %}", login)

        recover_position = login.index('form[action="/account/recover"]')
        recover_field_position = login.index(
            "document.querySelector('#RecoverEmail')", recover_position
        )
        self.assertLess(recover_position, recover_field_position)
        self.assertIn(
            "field.value = window.ccNormalizeSgMobile(field.value);",
            login[recover_position:recover_field_position + 200],
        )

        self.assertIn(
            "document.querySelector('#CustomerEmail')",
            login[login.rindex("addEventListener('submit'"):],
        )


class RegisterFormWiringTests(unittest.TestCase):
    def test_register_field_is_normalized_before_submit(self) -> None:
        register = read(REGISTER)
        self.assertIn("{% include 'mobile-number-normalize' %}", register)
        self.assertIn(
            "document.querySelector('#RegisterForm-EmailOrPhone')", register
        )

        submit_position = register.index("#form-register")
        field_position = register.index("#RegisterForm-EmailOrPhone", submit_position)
        normalize_call_position = register.index(
            "window.ccNormalizeSgMobile(field.value)", field_position
        )
        self.assertLess(submit_position, field_position)
        self.assertLess(field_position, normalize_call_position)


if __name__ == "__main__":
    unittest.main()
