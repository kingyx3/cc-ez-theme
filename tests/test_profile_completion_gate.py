"""Profile completion must finish before a signed-in shopper returns to shopping.

A Buy Now login carries the product/prior-page target in sessionStorage. The
customer may be authenticated before EasyStore considers their profile complete,
so the target must stay pending until the human profile fields and any first-time
password requirement are accepted.
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

    def test_signup_asks_only_for_a_new_password(self) -> None:
        boot = read(BOOT)
        details = read(DETAILS)

        # Keep EasyStore's account-details password contract. The template still
        # owns both controls for the later Change password feature.
        self.assertIn('name="details[password1]"', details)
        self.assertIn('name="details[password2]"', details)

        # Mandatory mobile/OTP signup must never surface current password.
        self.assertNotIn("form.querySelector('[name=\"details[password1]\"]')", boot)
        self.assertIn("form.querySelector('[name=\"details[password2]\"]')", boot)
        self.assertNotIn("currentPassword", boot)
        self.assertNotIn("currentWrapper", boot)

        self.assertIn("password.setAttribute('required', 'required');", boot)
        self.assertIn("password.setAttribute('autocomplete', 'new-password');", boot)
        self.assertIn("password.setAttribute('placeholder', 'Set password');", boot)
        self.assertIn("passwordLabel.textContent = 'Set password';", boot)
        self.assertIn("saveArea.insertBefore(passwordWrapper, saveRow);", boot)

    def test_password_is_required_only_until_first_successful_completion(self) -> None:
        boot = read(BOOT)

        # Password state is scoped to the authenticated customer rather than one
        # global browser flag shared by different accounts.
        self.assertIn('<meta name="cc-profile-customer-id" content="{{ customer.id }}">', boot)
        self.assertIn("PASSWORD_SET_PREFIX = 'cc:profile-password-set:'", boot)
        self.assertIn("PASSWORD_SUBMIT_PREFIX = 'cc:profile-password-submit:'", boot)
        self.assertIn("var needsFirstPassword = !passwordWasSet();", boot)
        self.assertIn("if (needsFirstPassword && password) {", boot)

        # A password is not remembered merely because the shopper clicked Save.
        # Submit records a pending attempt; EasyStore's existing update_success
        # response is the server acknowledgement that promotes it.
        self.assertIn("if (needsFirstPassword && password && password.value) {", boot)
        self.assertIn("rememberPasswordSubmit();", boot)
        self.assertIn("{% if update_success %}", boot)
        self.assertIn('<meta name="cc-profile-update-success" content="true">', boot)
        self.assertIn("var profileUpdateSucceeded = Boolean(", boot)
        self.assertIn("if (profileUpdateSucceeded && passwordSubmitPending()) {", boot)
        self.assertIn("markPasswordSet();", boot)

        # The accepted marker survives later renders in the same browser, with a
        # session fallback for browsers that reject localStorage.
        self.assertIn("window.localStorage.setItem(passwordSetKey, '1');", boot)
        self.assertIn("window.sessionStorage.setItem(passwordSetKey, '1');", boot)
        self.assertIn("window.sessionStorage.removeItem(passwordSubmitKey);", boot)
        self.assertIn("storageHas('localStorage', passwordSetKey)", boot)
        self.assertIn("storageHas('sessionStorage', passwordSetKey)", boot)

    def test_signup_policy_is_documented(self) -> None:
        documentation = read(SIGNUP_DOC).lower()

        self.assertIn("mobile number", documentation)
        self.assertIn("otp", documentation)
        self.assertIn("guest checkout is disabled", documentation)
        self.assertIn("set password", documentation)
        self.assertIn("no current-password field", documentation)
        self.assertIn("first successful", documentation)
        self.assertIn("then is not required again", documentation)
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
