"""International customer phone input stays aligned with EasyStore and CRM normalization."""

from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SNIPPET = ROOT / "theme" / "snippets" / "phone-country-picker.liquid"
RUNTIME = ROOT / "theme" / "assets" / "account-phone-input.js"
EDITOR = ROOT / "theme" / "editor_assets" / "account-phone-input.js"
DETAILS_RUNTIME = ROOT / "theme" / "assets" / "account-details-validation.js"
DETAILS_EDITOR = ROOT / "theme" / "editor_assets" / "account-details-validation.js"
CRM_SYNC = ROOT / "scripts" / "easystore_hubspot_sync.py"


def crm_country_dial_codes() -> dict[str, str]:
    tree = ast.parse(CRM_SYNC.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "COUNTRY_DIAL_CODES" for target in node.targets):
            continue
        value = ast.literal_eval(node.value)
        return {str(key): str(dial) for key, dial in value.items()}
    raise AssertionError("COUNTRY_DIAL_CODES is missing from CRM sync")


def storefront_country_dial_codes() -> dict[str, str]:
    source = RUNTIME.read_text(encoding="utf-8")
    return dict(re.findall(r"\{ iso: '([A-Z]{2})', dial: '(\d+)', label: '[^']+' \}", source))


class InternationalAccountPhoneTests(unittest.TestCase):
    def test_no_js_details_fallback_keeps_easystore_country_code_contract(self) -> None:
        source = SNIPPET.read_text(encoding="utf-8")

        self.assertIn('name="{{ country_code_field_name | escape }}"', source)
        self.assertIn('value="{{ default_country_code | escape }}"', source)
        self.assertIn("data-phone-country-code", source)
        self.assertIn('data-phone-input-id="{{ phone_input_id | escape }}"', source)
        self.assertNotIn("account-phone-input.js", source)

    def test_phone_helper_is_loaded_from_existing_global_account_asset(self) -> None:
        source = DETAILS_RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const loadAccountPhoneInput = () =>", source)
        self.assertIn("account-details-validation.js", source)
        self.assertIn("account-phone-input.js", source)
        self.assertIn("source.pathname = source.pathname.replace", source)
        self.assertIn("data-account-phone-input-loader", source)
        self.assertIn("document.head.appendChild(script);", source)

    def test_local_number_country_choices_match_crm_normalizer_exactly(self) -> None:
        self.assertEqual(crm_country_dial_codes(), storefront_country_dial_codes())

    def test_ui_adds_country_selector_and_numeric_other_dial_code(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("wrapper.className = 'account-phone-input';", source)
        self.assertIn("countryField.className = 'field on_focus account-phone-input__country';", source)
        self.assertIn("label.textContent = 'Country code';", source)
        self.assertIn("other.textContent = 'Other';", source)
        self.assertIn("const createDialField = (phone) =>", source)
        self.assertIn("input.inputMode = 'numeric';", source)
        self.assertIn("input.maxLength = 3;", source)
        self.assertIn("label.textContent = '+ code';", source)
        self.assertIn("account-phone-input--other", source)

    def test_phone_only_auth_fields_receive_the_same_country_component(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("'#RegisterForm-EmailOrPhone'", source)
        self.assertIn("'#CustomerEmail'", source)
        self.assertIn("'#RecoverEmail'", source)
        self.assertIn("const enhanceAuthPhone = (phone) =>", source)
        self.assertIn("phone.setAttribute('inputmode', 'numeric');", source)
        self.assertIn("phone.setAttribute('aria-label', 'Mobile number');", source)
        self.assertIn("phone.placeholder = 'Mobile number';", source)
        self.assertIn("if (phone.labels && phone.labels.length) phone.labels[0].textContent = 'Mobile number';", source)

    def test_insert_code_dom_adjustments_are_observed_briefly(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("if (!window.MutationObserver) return;", source)
        self.assertIn("const observer = new MutationObserver(enhanceAll);", source)
        self.assertIn("observer.observe(document.documentElement, { childList: true, subtree: true });", source)
        self.assertIn("window.setTimeout(() => observer.disconnect(), 5000);", source)

    def test_singapore_auth_submission_keeps_existing_local_identity_shape(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("if (country && country.iso === 'SG')", source)
        self.assertIn("phone.value = local;", source)
        self.assertIn("Preserve the store's current Singapore login/signup identity shape.", source)

    def test_foreign_auth_submission_combines_country_code_and_local_number(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const prepareInternationalValue = (country, dial, local) =>", source)
        self.assertIn("return '+' + digitsOnly(dial) + national;", source)
        self.assertIn("phone.value = prepareInternationalValue(country, dial, local);", source)
        self.assertIn("const DROP_DOMESTIC_ZERO = new Set([", source)
        self.assertIn("'MY', 'ID', 'PH', 'TH', 'VN', 'TW', 'JP', 'KR', 'IN', 'AU', 'NZ', 'GB'", source)

    def test_unlisted_country_uses_numeric_custom_calling_code(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const DIAL_MESSAGE = 'Please enter a valid country calling code.';", source)
        self.assertIn("if (!country && (dial.length < 1 || dial.length > 3))", source)
        self.assertIn("component.dialInput.setCustomValidity(DIAL_MESSAGE);", source)
        self.assertIn("phone.value = prepareInternationalValue(null, component.dialInput.value, local);", source)
        self.assertIn("hiddenCountry.value = '';", source)

    def test_known_details_country_keeps_easystore_iso_contract(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("phone.value = stripDomesticZero(country.iso, local);", source)
        self.assertIn("hiddenCountry.value = country.iso;", source)
        self.assertIn("countryMatchesForInternational", source)
        self.assertIn("+1 is shared by the US and Canada. Keep the calling code without guessing ISO.", source)

    def test_phone_length_stays_within_crm_identity_bounds(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const PHONE_MIN_DIGITS = 7;", source)
        self.assertIn("const PHONE_MAX_DIGITS = 15;", source)

    def test_runtime_and_editor_assets_stay_identical(self) -> None:
        self.assertEqual(
            RUNTIME.read_text(encoding="utf-8"),
            EDITOR.read_text(encoding="utf-8"),
        )
        self.assertEqual(
            DETAILS_RUNTIME.read_text(encoding="utf-8"),
            DETAILS_EDITOR.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
