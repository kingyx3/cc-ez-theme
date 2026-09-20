"""International profile phone input stays aligned with EasyStore and CRM.

Auth identity fields are intentionally excluded: EasyStore/Insert Code own those
inputs because theme-authored writes have previously caused duplicate-account
behaviour in signup/OTP flows.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SNIPPET = ROOT / "theme" / "snippets" / "phone-country-picker.liquid"
DETAILS_TEMPLATE = ROOT / "theme" / "templates" / "customers" / "details.liquid"
REGISTER_TEMPLATE = ROOT / "theme" / "templates" / "customers" / "register.liquid"
LOGIN_TEMPLATE = ROOT / "theme" / "templates" / "customers" / "login.liquid"
ACTIVATE_TEMPLATE = ROOT / "theme" / "templates" / "customers" / "activate_account.liquid"
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

    def test_phone_picker_uses_existing_easystore_phone_authentication_shape(self) -> None:
        source = SNIPPET.read_text(encoding="utf-8")
        details = DETAILS_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("{% for kv in customer.authentications %}", source)
        self.assertIn(
            "auth_key == 'phone' and auth_value.is_connected and auth_value.is_verified and customer.phone != blank",
            source,
        )
        self.assertIn('data-phone-verified="{% if phone_auth_verified %}true{% else %}false{% endif %}"', source)
        self.assertIn("{% for kv in customer.authentications %}", details)
        self.assertIn("{% if value.is_verified %}", details)

    def test_details_page_always_renders_phone_country_hook(self) -> None:
        source = DETAILS_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn(
            "{% include 'phone-country-picker', phone_input_id: 'DetailPhone', country_code_field_name: 'details[country_code]', default_country_code: customer.country_code %}",
            source,
        )
        self.assertNotIn("{% if is_identity_normalizer_canary_enabled %}", source)

    def test_phone_helper_is_loaded_from_existing_global_account_asset(self) -> None:
        source = DETAILS_RUNTIME.read_text(encoding="utf-8")
        self.assertIn("const loadAccountPhoneInput = () =>", source)
        self.assertIn("account-details-validation\\.js", source)
        self.assertIn("account-phone-input.js", source)
        self.assertIn("source.pathname = source.pathname.replace", source)
        self.assertIn("data-account-phone-input-loader", source)
        self.assertIn("document.head.appendChild(script);", source)

    def test_local_number_country_choices_match_crm_normalizer_exactly(self) -> None:
        self.assertEqual(crm_country_dial_codes(), storefront_country_dial_codes())

    def test_details_ui_adds_country_selector_and_numeric_other_dial_code(self) -> None:
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

    def test_country_and_number_controls_use_one_explicit_geometry(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("align-items:center", source)
        self.assertIn("height:4rem!important; min-height:4rem!important; margin:0!important", source)
        self.assertIn("border-radius:3.5rem!important", source)
        self.assertIn(".account-phone-input__number { height:4rem!important; min-height:4rem!important; }", source)
        self.assertIn(".account-phone-input__country .select { display:block; height:4rem!important", source)

    def test_theme_helper_never_takes_ownership_of_auth_identity_inputs(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("Authentication is intentionally out of scope", source)
        self.assertNotIn("data-es-mobile-only", source)
        self.assertNotIn("data-cc-phone-owned", source)
        self.assertNotIn("RegisterForm-EmailOrPhone", source)
        self.assertNotIn("CustomerEmail", source)
        self.assertNotIn("RecoverEmail", source)
        self.assertNotIn("normalizeAuthValue", source)
        self.assertNotIn("prepareBeforeAppClick", source)
        self.assertNotIn("pointerdown", source)
        self.assertNotIn("dispatchEvent", source)
        self.assertNotIn("sessionStorage", source)
        self.assertNotIn("AUTH_COUNTRY_KEY", source)

    def test_stored_iso_wins_when_dial_code_is_ambiguous_after_an_edit(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("const storedCountry = byIso(hiddenCountry.value);", source)
        self.assertIn("raw.indexOf(storedCountry.dial) === 0", source)
        self.assertIn("useCountry(phone, component, hiddenCountry, storedCountry, raw);", source)
        self.assertIn("{ iso: 'US', dial: '1'", source)
        self.assertIn("{ iso: 'CA', dial: '1'", source)

    def test_existing_unsupported_country_is_never_defaulted_to_singapore(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("if (initialCountry && !supportedInitialCountry)", source)
        self.assertIn("lockVerifiedPhone(phone, null, hiddenCountry, initialPhone, initialCountry);", source)
        self.assertNotIn("byIso(initialCountry) ? initialCountry : 'SG'", source)

    def test_untouched_profile_phone_is_restored_before_unrelated_submit(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("const state = { dirty: false, initialPhone, initialCountry };", source)
        self.assertIn("state.dirty = true;", source)
        self.assertIn("if (!state.dirty) {", source)
        self.assertIn("phone.value = state.initialPhone;", source)
        self.assertIn("hiddenCountry.value = state.initialCountry;", source)
        self.assertIn("Initial render is display-only", source)
        self.assertNotIn("DROP_DOMESTIC_ZERO", source)
        self.assertNotIn("stripDomesticZero", source)

    def test_explicit_international_phone_must_match_selected_country(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn(
            "const COUNTRY_MISMATCH_MESSAGE = 'Phone number does not match the selected country code.';",
            source,
        )
        self.assertIn("if (country && digits.indexOf(country.dial) !== 0)", source)
        self.assertIn("phone.setCustomValidity(COUNTRY_MISMATCH_MESSAGE);", source)

    def test_other_country_accepts_explicit_international_identity(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("const validInternational = (value) =>", source)
        self.assertIn("if (isInternational(phone.value))", source)
        self.assertIn("phone.value = '+' + internationalDigits(phone.value);", source)
        self.assertIn("hiddenCountry.value = '';", source)

    def test_verified_account_phone_is_read_only_and_restored_on_submit(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn(
            "const lockVerifiedPhone = (phone, component, hiddenCountry, initialPhone, initialCountry) =>",
            source,
        )
        self.assertIn("hiddenCountry.getAttribute('data-phone-verified') !== 'true'", source)
        self.assertIn("phone.readOnly = true;", source)
        self.assertIn("phone.setAttribute('data-verified-phone-locked', 'true');", source)
        self.assertIn("component.select.disabled = true;", source)
        self.assertIn("phone.value = initialPhone;", source)
        self.assertIn("hiddenCountry.value = initialCountry;", source)
        self.assertIn("if (!locked) interceptDetailsSubmit(phone, component, hiddenCountry, state);", source)

    def test_auth_forms_keep_native_easystore_endpoints_names_and_csrf(self) -> None:
        register = REGISTER_TEMPLATE.read_text(encoding="utf-8")
        login = LOGIN_TEMPLATE.read_text(encoding="utf-8")
        activate = ACTIVATE_TEMPLATE.read_text(encoding="utf-8")
        details = DETAILS_TEMPLATE.read_text(encoding="utf-8")
        runtime = RUNTIME.read_text(encoding="utf-8")
        self.assertIn('action="/account/register"', register)
        self.assertIn('name="customer[email_or_phone]"', register)
        self.assertIn('name="_token" value="{% csrf %}"', register)
        self.assertIn('action="/account/login"', login)
        self.assertIn('name="customer[email_or_phone]"', login)
        self.assertIn('action="/account/recover"', login)
        self.assertIn('name="email_or_phone"', login)
        self.assertIn("action='/account/activate'", activate)
        self.assertIn('name="customer[email_or_phone]"', activate)
        self.assertIn("action='/account/details'", details)
        self.assertIn('name="details[phone]"', details)
        self.assertIn("country_code_field_name: 'details[country_code]'", details)
        self.assertNotIn("fetch(", runtime)
        self.assertNotIn("XMLHttpRequest", runtime)
        self.assertNotIn("setAttribute('action'", runtime)
        self.assertNotIn("setAttribute('name'", runtime)

    def test_phone_length_stays_within_crm_identity_bounds(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("const PHONE_MIN_DIGITS = 7;", source)
        self.assertIn("const PHONE_MAX_DIGITS = 15;", source)

    def test_runtime_and_editor_assets_stay_identical(self) -> None:
        self.assertEqual(RUNTIME.read_text(encoding="utf-8"), EDITOR.read_text(encoding="utf-8"))
        self.assertEqual(DETAILS_RUNTIME.read_text(encoding="utf-8"), DETAILS_EDITOR.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
