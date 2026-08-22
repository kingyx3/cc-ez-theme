"""Profile completion must finish before a signed-in shopper returns to shopping.

A Buy Now login carries the product/prior-page target in sessionStorage.  The
customer may be authenticated before EasyStore considers their profile complete,
so the target must stay pending until the human profile fields and a password are
accepted.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"
BOOT = THEME / "snippets" / "login-redirect-boot.liquid"
DETAILS = THEME / "templates" / "customers" / "details.liquid"
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

        # This runs from the layout head on every storefront page.  The source
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
        self.assertNotIn("removeItem", required)

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

    def test_password_is_a_visible_required_part_of_profile_completion(self) -> None:
        boot = read(BOOT)
        details = read(DETAILS)

        # Use EasyStore's existing account-details password contract rather than
        # introducing an unsupported field name or separate endpoint.
        self.assertIn('name="details[password1]"', details)
        self.assertIn('name="details[password2]"', details)
        self.assertIn("form.querySelector('[name=\"details[password1]\"]')", boot)
        self.assertIn("form.querySelector('[name=\"details[password2]\"]')", boot)

        # A just-created OTP account may not have an old password yet, so current
        # password stays optional while the new password is mandatory.
        self.assertIn("currentPassword.removeAttribute('required');", boot)
        self.assertIn("password.setAttribute('required', 'required');", boot)
        self.assertIn("password.setAttribute('autocomplete', 'new-password');", boot)
        self.assertIn("password.setAttribute('placeholder', 'Password');", boot)

        # Both real password fields are moved out of the template's hidden
        # Change-password panel and into the visible profile form before Save.
        self.assertIn("saveArea.insertBefore(currentWrapper, saveRow);", boot)
        self.assertIn("saveArea.insertBefore(passwordWrapper, saveRow);", boot)

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
