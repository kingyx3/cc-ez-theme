"""Profile completion must finish before a signed-in shopper returns to shopping.

A Buy Now login carries the product/prior-page target in sessionStorage. The
customer may be authenticated before EasyStore considers their profile complete,
so the target must stay pending until the required human profile fields are
accepted. Set password is surfaced only during the mobile/OTP signup trip.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"
BOOT = THEME / "snippets" / "login-redirect-boot.liquid"
DETAILS = THEME / "templates" / "customers" / "details.liquid"
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
    def test_incomplete_means_platform_flag_or_missing_human_fields(self) -> None:
        boot = read(BOOT)
        code = liquid_code(boot)

        self.assertIn("customer.is_optional_fields_filled == false", code)
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

    def test_signup_surfaces_only_the_new_password_field(self) -> None:
        boot = read(BOOT)
        details = read(DETAILS)

        # Keep EasyStore's normal account password-change pair intact.
        self.assertIn('name="details[password1]"', details)
        self.assertIn('name="details[password2]"', details)

        # Signup must never surface or query the current-password control.
        self.assertNotIn("form.querySelector('[name=\"details[password1]\"]')", boot)
        self.assertIn("form.querySelector('[name=\"details[password2]\"]')", boot)
        self.assertNotIn("currentPassword", boot)
        self.assertNotIn("currentWrapper", boot)

        self.assertIn("password.setAttribute('required', 'required');", boot)
        self.assertIn("password.setAttribute('autocomplete', 'new-password');", boot)
        self.assertIn("password.setAttribute('placeholder', 'Set password');", boot)
        self.assertIn("passwordLabel.textContent = 'Set password';", boot)
        self.assertIn("saveArea.insertBefore(passwordWrapper, saveRow);", boot)

    def test_set_password_is_visible_only_during_signup(self) -> None:
        boot = read(BOOT)

        # Visiting the real registration route starts a tab-scoped signup trip.
        self.assertIn("SIGNUP_PASSWORD_KEY = 'cc:signup-password-setup'", boot)
        self.assertIn("if (/^\\/account\\/register(?:\\/|$)/i.test(path)) {", boot)
        self.assertIn("window.sessionStorage.setItem(SIGNUP_PASSWORD_KEY, '1');", boot)

        # Returning to ordinary login means signup was abandoned, so an existing
        # customer cannot inherit the signup-only password prompt.
        self.assertIn("if (/^\\/account\\/login(?:\\/|$)/i.test(path)) {", boot)
        self.assertIn("window.sessionStorage.removeItem(SIGNUP_PASSWORD_KEY);", boot)

        # The mandatory details gate promotes the new-password field only while
        # that signup marker is present. Normal profile completion leaves it hidden.
        self.assertIn("var signupPasswordSetup = signupPasswordPending();", boot)
        self.assertIn("if (signupPasswordSetup && password) {", boot)
        self.assertNotIn("PASSWORD_SET_PREFIX", boot)
        self.assertNotIn("cc-profile-customer-id", boot)
        self.assertNotIn("localStorage", boot)

        # EasyStore's server acknowledgement ends the signup-only password step.
        self.assertIn("{% if update_success %}", boot)
        self.assertIn('<meta name="cc-profile-update-success" content="true">', boot)
        self.assertIn("if (profileUpdateSucceeded && signupPasswordPending()) {", boot)
        self.assertIn("clearSignupPasswordPending();", boot)

    def test_signup_policy_is_documented(self) -> None:
        documentation = read(SIGNUP_DOC).lower()

        self.assertIn("mobile number", documentation)
        self.assertIn("otp", documentation)
        self.assertIn("guest checkout is disabled", documentation)
        self.assertIn("set password", documentation)
        self.assertIn("no current-password field", documentation)
        self.assertIn("signup-only", documentation)
        self.assertIn("/account/register", documentation)
        self.assertIn("normal account-details", documentation)
        self.assertIn("update_success", documentation)
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

    def test_editor_asset_stays_identical(self) -> None:
        self.assertEqual(read(ASSET), read(EDITOR_ASSET))


if __name__ == "__main__":
    unittest.main()
