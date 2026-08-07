"""The account identifier field on the phone-OTP entry points.

With `shop.phone_account_enabled`, one text field carries either an email
address or a mobile number, and the mobile number is the value EasyStore texts
the one-time password to. Two properties of that field are covered here.

`autocomplete` must not claim the field holds an email address. It shipped as
`autocomplete="email"` on every entry point, so browsers and password managers
offered a saved address on a field that needs a phone number for an OTP to
arrive; accepting that suggestion submits an address the store cannot text and
no SMS is sent. `username` is the token for an identifier that may be either.

`label[for]` must name the input's real id. It read `RegisterForm-email` while
the input is `RegisterForm-EmailOrPhone`, so the signup form's one identifier
field had a title associated with nothing.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


THEME = Path(__file__).resolve().parents[1] / "theme"
CUSTOMERS = THEME / "templates" / "customers"

# Every template rendering the shared email-or-phone account identifier.
IDENTIFIER_TEMPLATES = ("login", "register", "activate_account")


def strip_comments(source: str) -> str:
    return re.sub(r"{%-?\s*comment.*?endcomment\s*-?%}", "", source, flags=re.DOTALL)


def read(name: str) -> str:
    return strip_comments((CUSTOMERS / f"{name}.liquid").read_text(encoding="utf-8"))


def identifier_inputs(source: str) -> list[str]:
    """Every `<input>` tag whose name is the email-or-phone identifier."""
    return [
        tag for tag in re.findall(r"<input\b[^>]*>", source, flags=re.DOTALL)
        if re.search(r'name="(customer\[email_or_phone\]|email_or_phone)"', tag)
    ]


def labels(source: str) -> list[str]:
    return re.findall(r'<label\s+for="([^"]+)"', source)


def ids(source: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', source))


class IdentifierAutocompleteTests(unittest.TestCase):
    def test_every_template_renders_an_identifier_field(self) -> None:
        # Guards the rest of this class against silently matching nothing.
        for name in IDENTIFIER_TEMPLATES:
            with self.subTest(template=name):
                self.assertTrue(identifier_inputs(read(name)))

    def test_the_identifier_field_is_never_hardcoded_as_an_email_field(self) -> None:
        for name in IDENTIFIER_TEMPLATES:
            for tag in identifier_inputs(read(name)):
                with self.subTest(template=name, tag=tag):
                    self.assertNotIn('autocomplete="email"', tag)

    def test_the_identifier_field_switches_autocomplete_with_the_placeholder(self) -> None:
        for name in IDENTIFIER_TEMPLATES:
            source = read(name)
            with self.subTest(template=name):
                for tag in identifier_inputs(source):
                    self.assertIn('autocomplete="{{ account_autocomplete }}"', tag)
                # Set in the same `phone_account_enabled` branch that chooses the
                # field's title, so the two can never disagree.
                self.assertIn("assign account_autocomplete = 'email'", source)
                self.assertIn("assign account_autocomplete = 'username'", source)
                phone_branch = source.split("shop.phone_account_enabled", 1)[1]
                self.assertIn(
                    "assign account_autocomplete = 'username'",
                    phone_branch.split("{% endif %}", 1)[0],
                )

    def test_the_password_fields_keep_their_own_autocomplete(self) -> None:
        # The switch above must not have been applied with a blunt replace.
        self.assertIn('autocomplete="current-password"', read("login"))
        self.assertIn('autocomplete="new-password"', read("reset_password"))


class IdentifierLabelTests(unittest.TestCase):
    def test_every_label_points_at_an_element_that_exists(self) -> None:
        for name in IDENTIFIER_TEMPLATES:
            source = read(name)
            rendered = ids(source)
            for target in labels(source):
                with self.subTest(template=name, label=target):
                    self.assertIn(target, rendered)

    def test_the_signup_identifier_label_names_the_identifier_input(self) -> None:
        for name in ("register", "activate_account"):
            source = read(name)
            with self.subTest(template=name):
                self.assertIn("RegisterForm-EmailOrPhone", ids(source))
                self.assertIn("RegisterForm-EmailOrPhone", labels(source))
                # The id that never existed.
                self.assertNotIn("RegisterForm-email", labels(source))


if __name__ == "__main__":
    unittest.main()
