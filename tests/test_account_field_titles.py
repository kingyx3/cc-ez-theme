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


def code_only(source: str) -> str:
    """Strips JS comments so assertions read the code, not the prose."""
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return "\n".join(
        line for line in without_blocks.splitlines()
        if not line.strip().startswith("//")
    )


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


class AuthFieldTitleTests(unittest.TestCase):
    """The sign-in, register and activate templates read the same class of key.

    `customer.login.email` comes back empty on this store, and it is the key
    behind the sign-in field whenever phone accounts are switched off — the same
    empty placeholder and empty label that left /account/details untitled.
    """

    TEMPLATES = ("login", "register", "activate_account")

    def template(self, name: str) -> str:
        return (THEME / "templates" / "customers" / f"{name}.liquid").read_text(
            encoding="utf-8"
        )

    def test_the_account_field_title_has_a_literal_fallback(self) -> None:
        for name in self.TEMPLATES:
            source = self.template(name)
            with self.subTest(template=name):
                self.assertIn("{% assign account_fallback = 'Email' %}", source)
                self.assertIn(
                    "{% assign account_fallback = 'Email or mobile number' %}",
                    source,
                )
                self.assertIn(
                    "translation_key: account_placeholder, "
                    "fallback: account_fallback",
                    source,
                )

    def test_no_account_field_reads_a_bare_translation(self) -> None:
        for name in self.TEMPLATES:
            with self.subTest(template=name):
                self.assertNotIn(
                    "{{ account_placeholder | t }}", self.template(name)
                )

    def test_every_use_of_the_key_is_covered(self) -> None:
        # A placeholder attribute and a label in each form; missing one of them
        # is what produced a field with a title on only some pages.
        for name, expected in (("login", 4), ("register", 2), ("activate_account", 2)):
            with self.subTest(template=name):
                self.assertEqual(
                    expected,
                    self.template(name).count(
                        "translation_key: account_placeholder"
                    ),
                )


class RecoveryCopyOverrideTests(unittest.TestCase):
    """The script that replaces the reset-email sentence wherever it renders.

    `/account/auth` may be EasyStore's own flow, and the copy there is the
    platform's translation, so the template fix cannot reach it. This override
    can - but it must stay text-only: theme scripts writing into that flow's
    fields are what broke signup with "Customer already exists (phone)".
    """

    RUNTIME = THEME / "assets" / "account-recovery-copy.js"
    EDITOR = THEME / "editor_assets" / "account-recovery-copy.js"

    @classmethod
    def setUpClass(cls) -> None:
        cls.script = cls.RUNTIME.read_text(encoding="utf-8")

    def test_the_layout_loads_it(self) -> None:
        layout = (THEME / "layout" / "theme.liquid").read_text(encoding="utf-8")
        self.assertIn("'account-recovery-copy.js' | asset_url", layout)

    def test_runtime_and_editor_copies_stay_in_sync(self) -> None:
        self.assertEqual(
            self.RUNTIME.read_text(encoding="utf-8"),
            self.EDITOR.read_text(encoding="utf-8"),
        )

    def test_it_replaces_the_email_promise_with_otp_copy(self) -> None:
        self.assertIn("reset\\s+your\\s+password", self.script)
        self.assertIn("Confirm your mobile OTP to proceed", self.script)
        self.assertIn("one-time password", self.script)

    def test_it_writes_text_and_nothing_else(self) -> None:
        # The whole safety argument for touching the platform's auth flow.
        code = code_only(self.script)
        self.assertIn("element.textContent = OTP_COPY", code)
        self.assertNotIn("dispatchEvent", code)
        self.assertNotIn(".value =", code)
        self.assertNotIn("innerHTML", code)
        self.assertNotIn("submit()", code)
        self.assertNotIn("one-time-code", code)

    def test_it_leaves_the_rest_of_the_storefront_alone(self) -> None:
        # No observer anywhere without a recovery step on the page, and no
        # page-path heuristics - the trap that once turned the search box into
        # an OTP field.
        code = code_only(self.script)
        self.assertIn("if (!hasRecoveryStep()) return;", code)
        self.assertIn('form[action="/account/recover"]', code)
        self.assertNotIn("location.pathname", code)

    def test_it_only_rewrites_elements_that_hold_their_own_text(self) -> None:
        code = code_only(self.script)
        self.assertIn("element.children.length === 0", code)
        self.assertIn("if (!isLeaf(element)) return;", code)


class ConsoleCheckTests(unittest.TestCase):
    """The console check that says why a copy change is not showing.

    A deployed copy change that stays invisible has two very different causes —
    a stale published build, or a page EasyStore renders itself — and they need
    opposite fixes. The script has to separate them.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "account-copy-check.console.js"
        ).read_text(encoding="utf-8")

    def test_it_looks_for_markup_only_this_theme_emits(self) -> None:
        self.assertIn('form[action="/account/recover"]', self.script)
        self.assertIn("#RecoverEmail", self.script)
        self.assertIn("#form-login", self.script)

    def test_it_reads_the_published_stylesheet(self) -> None:
        # "I deployed main" is checkable rather than assumed: the rules in the
        # served CSS say which build is live.
        self.assertIn('link[rel="stylesheet"]', self.script)
        self.assertIn(".field__input.no-float-label::placeholder", self.script)
        self.assertIn(":not(:has(~ label))::placeholder", self.script)

    def test_it_separates_a_stale_build_from_a_platform_page(self) -> None:
        self.assertIn("PLATFORM PAGE", self.script)
        self.assertIn("THEME PAGE, OLD BUILD", self.script)
        self.assertIn("THEME PAGE, CURRENT BUILD", self.script)
        self.assertIn("customer.recover_password.subtext", self.script)

    def test_it_reports_the_account_email_field(self) -> None:
        self.assertIn('label[for="DetailEmail"]', self.script)
        self.assertIn("UNTITLED", self.script)
        self.assertIn(EMAIL_KEY, self.script)

    def test_it_lists_platform_fields_that_carry_no_label(self) -> None:
        self.assertIn(".field__input", self.script)
        self.assertIn("fields with no label", self.script)


if __name__ == "__main__":
    unittest.main()
