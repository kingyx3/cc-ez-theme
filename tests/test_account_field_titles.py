"""Checks the copy and the field titles a shopper reads on the account pages.

Two production symptoms are covered here. The recovery form asked for a mobile
number under platform copy that promised a reset email, and the email field on
/account/details rendered with no title at all because this store's translation
for `customer.login.email` comes back empty — an empty placeholder and an empty
floating label leave an address on screen with nothing naming it.

The rendering test executes the real fallback snippet against the real markup
from the template, which is the only way to prove a title survives a store with
no translation for the key.
"""
from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

try:  # pragma: no cover - exercised by the absence of the dependency
    from liquid import DictLoader, Environment
except ImportError:  # pragma: no cover
    DictLoader = None
    Environment = None

# Skipping is for a developer who has not installed requirements-dev yet. CI
# pins the dependency, so a missing engine there is a broken build.
REQUIRE_ENGINE = bool(os.environ.get("CI"))

THEME = Path(__file__).resolve().parents[1] / "theme"
LOGIN = THEME / "templates" / "customers" / "login.liquid"
DETAILS = THEME / "templates" / "customers" / "details.liquid"
FALLBACK = THEME / "snippets" / "translation-fallback.liquid"
EMAIL_KEY = "customer.login.email"


def strip_comments(source: str) -> str:
    """Drops Liquid comments so assertions read the markup, not the prose."""
    return re.sub(r"{%-?\s*comment.*?endcomment\s*-?%}", "", source, flags=re.DOTALL)


def recovery_subtext(source: str) -> str:
    """The paragraph between the recovery heading and its form."""
    body = source.split('id="recover"', 1)[1].split("<form", 1)[0]
    paragraph = re.search(r"<p>(.*?)</p>", strip_comments(body), flags=re.DOTALL)
    assert paragraph, "the recovery form lost its explanatory paragraph"
    return " ".join(paragraph.group(1).split())


def email_field_markup(source: str) -> str:
    return "\n".join(
        line for line in source.splitlines() if "DetailEmail" in line
    )


class RecoveryCopyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = LOGIN.read_text(encoding="utf-8")

    def test_the_recovery_form_asks_for_a_mobile_otp(self) -> None:
        subtext = recovery_subtext(self.source).lower()
        self.assertIn("otp", subtext)
        self.assertIn("mobile", subtext)
        self.assertIn("one-time password", subtext)

    def test_the_recovery_form_no_longer_promises_an_email(self) -> None:
        # The store recovers an account by OTP. Copy that mentions email sends
        # the shopper off to wait for a message that never arrives.
        subtext = recovery_subtext(self.source).lower()
        self.assertNotIn("email", subtext)
        self.assertNotIn("recover_password.subtext", strip_comments(self.source))


class AccountEmailFieldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = DETAILS.read_text(encoding="utf-8")
        self.field = email_field_markup(self.source)

    def test_the_email_field_still_has_a_placeholder_and_a_label(self) -> None:
        self.assertIn("placeholder=", self.field)
        self.assertIn('<label for="DetailEmail">', self.field)

    def test_the_email_title_falls_back_when_the_store_has_no_translation(self) -> None:
        self.assertEqual(2, self.field.count("translation-fallback"))
        self.assertEqual(2, self.field.count(f"translation_key: '{EMAIL_KEY}'"))
        self.assertEqual(2, self.field.count("fallback: 'Email'"))

    def test_the_bare_translation_is_gone_from_the_email_field(self) -> None:
        # A bare `| t` is exactly what rendered blank in production.
        self.assertNotIn(f"'{EMAIL_KEY}' | t", self.field)

    def test_the_attribute_copy_is_escaped(self) -> None:
        placeholder = self.field.split("placeholder=", 1)[1]
        self.assertIn("escape_output: true", placeholder.split(">", 1)[0])


class TranslationFallbackSnippetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snippet = FALLBACK.read_text(encoding="utf-8")

    def test_emptiness_is_detected_by_value_not_only_by_blank(self) -> None:
        # `blank` behaves differently across Liquid engines; the empty string
        # comparison is the one that holds on EasyStore.
        self.assertIn("translated_value == blank", self.snippet)
        self.assertIn("translation_fallback_probe == ''", self.snippet)
        self.assertIn("| append: '' | strip", self.snippet)

    def test_a_missing_key_is_detected_however_the_platform_reports_it(self) -> None:
        self.assertIn("translated_value == translation_key", self.snippet)
        self.assertIn("translation_fallback_probe == translation_key", self.snippet)
        self.assertIn("contains 'translation missing'", self.snippet)

    def test_the_escaped_form_is_still_available(self) -> None:
        self.assertIn("escape_output", self.snippet)
        self.assertIn("translated_value | escape", self.snippet)


@unittest.skipIf(
    Environment is None and not REQUIRE_ENGINE,
    "python-liquid is not installed; run pip install -r requirements-dev.txt",
)
class EmailFieldRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        if Environment is None:
            self.fail(
                "python-liquid is required in CI: this is the only check that "
                "executes the fallback the account email field depends on."
            )
        self.markup = email_field_markup(DETAILS.read_text(encoding="utf-8"))

    def render(self, translation: str) -> str:
        loader = DictLoader({
            "translation-fallback": FALLBACK.read_text(encoding="utf-8"),
        })
        environment = Environment(loader=loader)
        environment.filters["t"] = lambda key, *args, **kwargs: translation
        return environment.from_string(self.markup).render(
            customer={"cust_email": "shopper@example.com"},
        )

    def test_a_store_with_no_translation_still_names_the_field(self) -> None:
        for missing in ("", "   ", EMAIL_KEY, "Translation missing: en.customer.login.email"):
            with self.subTest(translation=missing):
                rendered = self.render(missing)
                self.assertIn('placeholder="Email"', rendered)
                self.assertIn(">Email</label>", rendered)

    def test_a_store_translation_is_still_preferred(self) -> None:
        rendered = self.render("E-mel")
        self.assertIn('placeholder="E-mel"', rendered)
        self.assertIn(">E-mel</label>", rendered)
        self.assertNotIn('placeholder="Email"', rendered)
        self.assertNotIn(">Email</label>", rendered)

    def test_the_customer_email_is_still_the_value(self) -> None:
        self.assertIn('value="shopper@example.com"', self.render(""))


if __name__ == "__main__":
    unittest.main()
