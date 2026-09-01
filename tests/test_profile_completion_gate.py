"""Profile completion must finish before a signed-in shopper returns to shopping.

A Buy Now login carries the product/prior-page target in sessionStorage. The
customer may be authenticated before EasyStore considers their profile complete,
so the target must stay pending until EasyStore's native first-password step and
the required human profile fields are accepted.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"
BOOT = THEME / "snippets" / "login-redirect-boot.liquid"
DETAILS = THEME / "templates" / "customers" / "details.liquid"
REGISTER = THEME / "templates" / "customers" / "register.liquid"
SIGNUP_DOC = ROOT / "docs" / "CUSTOMER_SIGNUP_FLOW.md"
ASSET = THEME / "assets" / "account-login-redirect.js"
EDITOR_ASSET = THEME / "editor_assets" / "account-login-redirect.js"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def liquid_code(source: str) -> str:
    return re.sub(
        r"{%-?\s*comment\s*-?%}.*?{%-?\s*endcomment\s*-?%}",
        "",
        source,
        flags=re.DOTALL,
    )


class ProfileCompletionGateTests(unittest.TestCase):
    def test_incomplete_means_missing_required_human_fields_only(self) -> None:
        boot = read(BOOT)
        code = liquid_code(boot)

        # EasyStore's aggregate optional-fields flag can remain false because of
        # unrelated optional/custom fields. It must never keep this gate locked.
        self.assertNotIn("customer.is_optional_fields_filled", code)
        for field in (
            "customer.first_name == blank",
            "customer.last_name == blank",
            "customer.gender == blank",
            "customer.birthdate == blank",
        ):
            with self.subTest(field=field):
                self.assertIn(field, code)

        # This runs from the layout head on every storefront page. The source
        # attribution incident proved that attribute settings are not safe here.
        self.assertNotIn("shop.attribute_settings", code)

    def test_incomplete_customer_is_forced_to_details_before_returning(self) -> None:
        boot = read(BOOT)
        required = boot[boot.index("if (profileRequired) {") : boot.index("// The landing page")]

        self.assertIn("window.ccProfileCompletionRequired = true;", required)
        self.assertIn("var PROFILE_PATH = '/account/details';", required)
        self.assertIn("window.location.replace(PROFILE_PATH);", required)

        # The pending Buy Now target is preserved, never consumed by the gate.
        self.assertIn("cc:pending-login-redirect", required)
        self.assertIn("if (pendingTarget()) return;", required)
        self.assertNotIn("window.sessionStorage.removeItem(KEY)", required)

    def test_prior_storefront_page_is_remembered_when_buy_now_did_not_supply_one(self) -> None:
        boot = read(BOOT)

        self.assertIn("safeTarget(path + String(window.location.search || '')) || referrerTarget()", boot)
        self.assertIn("previous.origin !== window.location.origin", boot)
        self.assertIn("if (/^\\/account(\\/|$)/i.test(target)) return '';", boot)
        self.assertIn("window.sessionStorage.setItem(KEY", boot)

    def test_completed_profile_returns_to_the_saved_storefront_target(self) -> None:
        boot = read(BOOT)
        landing = boot[boot.index("// The landing page") :]

        # Once none of the four required human fields are blank, the gate is not
        # rendered. The account landing path then consumes the target that was
        # deliberately preserved during signup/profile completion and replaces
        # the account landing page with the original storefront page.
        self.assertIn("window.sessionStorage.removeItem('cc:pending-login-redirect');", landing)
        self.assertIn("window.location.replace(target);", landing)
        self.assertLess(
            landing.index("window.sessionStorage.removeItem('cc:pending-login-redirect');"),
            landing.index("window.location.replace(target);"),
        )

    def test_details_form_requires_the_human_profile_fields(self) -> None:
        boot = read(BOOT)

        for name in (
            "details[first_name]",
            "details[last_name]",
            "details[gender]",
            "details[birthdate]",
        ):
            with self.subTest(name=name):
                self.assertIn(name, boot)
        self.assertIn("field.setAttribute('required', 'required');", boot)
        self.assertIn("form.checkValidity", boot)
        self.assertIn("form.reportValidity", boot)

    def test_profile_gate_never_reuses_change_password_fields_for_signup(self) -> None:
        boot = liquid_code(read(BOOT))
        details = read(DETAILS)
        register = read(REGISTER)

        # EasyStore keeps a distinct contract for first password creation and
        # later password changes. Do not silently turn the latter into the former.
        self.assertIn('name="customer[password]"', register)
        self.assertIn('name="details[password1]"', details)
        self.assertIn('name="details[password2]"', details)
        self.assertNotIn('details[password1]', boot)
        self.assertNotIn('details[password2]', boot)
        self.assertNotIn("cc:signup-password-setup", boot)
        self.assertNotIn("signupPasswordPending", boot)

    def test_native_first_password_step_precedes_details_redirect(self) -> None:
        boot = read(BOOT)

        self.assertIn("function nativeFirstPasswordStep()", boot)
        self.assertIn('input[name="customer[password]"]', boot)
        self.assertIn("function routeAfterNativeAccountSetup()", boot)
        self.assertIn("if (nativeFirstPasswordStep()) return;", boot)
        self.assertIn("document.addEventListener('DOMContentLoaded', routeAfterNativeAccountSetup);", boot)

        route = boot[boot.index("function routeAfterNativeAccountSetup()") :]
        self.assertLess(
            route.index("if (nativeFirstPasswordStep()) return;"),
            route.index("window.location.replace(PROFILE_PATH);"),
        )

    def test_signup_policy_is_documented(self) -> None:
        documentation = read(SIGNUP_DOC).lower()

        self.assertIn("mobile number", documentation)
        self.assertIn("otp", documentation)
        self.assertIn("guest checkout is disabled", documentation)
        self.assertIn("customer[password]", documentation)
        self.assertIn("details[password1]", documentation)
        self.assertIn("details[password2]", documentation)
        self.assertIn("change password", documentation)
        self.assertIn("native", documentation)
        self.assertIn("password-first", documentation)
        self.assertIn("is_optional_fields_filled", documentation)
        self.assertIn("does not keep the gate locked", documentation)
        self.assertIn("product or prior storefront page", documentation)

    def test_navigation_is_locked_until_a_valid_details_post(self) -> None:
        boot = read(BOOT)

        self.assertIn("a[href], [data-theme-action=\"history-back\"]", boot)
        self.assertIn("event.stopImmediatePropagation();", boot)
        self.assertIn("window.addEventListener('beforeunload'", boot)
        self.assertIn("var allowUnload = false;", boot)
        self.assertIn("allowUnload = true;", boot)

    def test_deferred_login_redirect_cannot_bypass_the_profile_gate(self) -> None:
        asset = read(ASSET)

        marker = "if (window.ccProfileCompletionRequired) return;"
        self.assertIn(marker, asset)
        self.assertLess(asset.index("if (stillAuthenticating())"), asset.index(marker))
        self.assertLess(asset.index(marker), asset.index("if (!signedIn()) return;"))
        self.assertNotIn("details[password2]", asset)

    def test_editor_asset_stays_identical(self) -> None:
        self.assertEqual(read(ASSET), read(EDITOR_ASSET))


if __name__ == "__main__":
    unittest.main()
