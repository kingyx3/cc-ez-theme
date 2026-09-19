"""International customer phone input stays aligned with EasyStore, Insert Code, and CRM."""

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

    def test_phone_picker_marks_only_easystore_verified_phone_authentication(self) -> None:
        source = SNIPPET.read_text(encoding="utf-8")

        self.assertIn("{% for kv in customer.authentications %}", source)
        self.assertIn("auth_key == 'phone' and auth_value.is_connected and auth_value.is_verified", source)
        self.assertIn('data-phone-verified="{% if phone_auth_verified %}true{% else %}false{% endif %}"', source)

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

    def test_country_and_number_controls_use_one_explicit_geometry(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("align-items:center", source)
        self.assertIn("margin:0!important; padding:0!important; align-self:center", source)
        self.assertIn("height:4rem!important; min-height:4rem!important; margin:0!important", source)
        self.assertIn("border-radius:3.5rem!important", source)
        self.assertIn(".account-phone-input--auth .account-phone-input__number { display:block!important; height:4rem!important", source)
        self.assertIn(".account-phone-input--details .account-phone-input__country select { padding:1.4rem 4rem 0 2rem!important; }", source)

    def test_insert_code_marker_is_the_primary_auth_field_hook(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("'input[data-es-mobile-only=\"true\"]'", source)
        self.assertIn("'input[data-cc-phone-owned=\"true\"]'", source)
        self.assertIn("'#RegisterForm-EmailOrPhone'", source)
        self.assertIn("'#CustomerEmail'", source)
        self.assertIn("'#RecoverEmail'", source)
        self.assertIn("const authPhoneInputsInRoot = (root) =>", source)
        self.assertIn("identity.indexOf('mobile number')", source)

    def test_enhanced_auth_field_takes_ownership_from_insert_code_validator(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const releaseInsertCodeOwnership = (phone) =>", source)
        self.assertIn("phone.removeAttribute('data-es-mobile-only');", source)
        self.assertIn("phone.setAttribute('data-cc-phone-owned', 'true');", source)
        self.assertIn("phone.setAttribute('data-placeholder', 'Mobile number');", source)
        self.assertIn("phone.setAttribute('aria-label', 'Mobile number');", source)
        self.assertIn("phone.placeholder = 'Mobile number';", source)

    def test_insert_code_app_dom_does_not_require_theme_field_wrapper(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("let phoneContainer = phone.closest && phone.closest('.field');", source)
        self.assertIn("if (!phoneContainer)", source)
        self.assertIn("phoneContainer.className = 'account-phone-input__number account-phone-input__number-shell';", source)
        self.assertIn("phoneContainer.appendChild(phone);", source)
        self.assertIn("ensurePhoneId(phone)", source)

    def test_auth_detection_stays_scoped_to_account_flows_and_excludes_otp(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const isOtpInput = (phone) =>", source)
        self.assertIn("const isAuthContext = (phone) =>", source)
        self.assertIn("/(?:otp|one[- ]?time|verification|security code)/", source)
        self.assertIn("/\\/account\\/(?:login|register|recover|activate|auth|signup)", source)

    def test_dynamic_insert_code_and_open_component_roots_are_rechecked(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const visitRoots = (root, callback) =>", source)
        self.assertIn("if (element.shadowRoot) visitRoots(element.shadowRoot, callback);", source)
        self.assertIn("if (element.contentDocument) visitRoots(element.contentDocument, callback);", source)
        self.assertIn("const observer = new MutationObserver(enhanceAll);", source)
        self.assertIn("attributeFilter: ['data-es-mobile-only']", source)
        self.assertIn("window.setTimeout(() => observer.disconnect(), 10000);", source)
        self.assertIn("[250, 750, 1500, 3000, 6000]", source)

    def test_singapore_auth_submission_keeps_existing_eight_digit_identity_shape(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const SG_PHONE_MESSAGE = 'Please enter an 8-digit Singapore mobile number.';", source)
        self.assertIn("if (isAuth && country && country.iso === 'SG' && local.length !== 8)", source)
        self.assertIn("const nextValue = country && country.iso === 'SG'", source)
        self.assertIn("? local", source)

    def test_foreign_auth_submission_combines_country_code_and_local_number(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const prepareInternationalValue = (country, dial, local) =>", source)
        self.assertIn("return '+' + digitsOnly(dial) + national;", source)
        self.assertIn("setFrameworkAwarePhoneValue(phone, nextValue, true);", source)
        self.assertIn("const DROP_DOMESTIC_ZERO = new Set([", source)
        self.assertIn("'MY', 'ID', 'PH', 'TH', 'VN', 'TW', 'JP', 'KR', 'IN', 'AU', 'NZ', 'GB'", source)

    def test_unknown_international_number_keeps_subscriber_after_inferred_dial_code(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("component.dialInput.value = raw.slice(0, guessedDialLength);", source)
        self.assertIn("phone.value = raw.slice(guessedDialLength);", source)

    def test_controlled_auth_input_is_synchronized_before_app_click(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const setFrameworkAwarePhoneValue = (phone, value, notify) =>", source)
        self.assertIn("Object.getOwnPropertyDescriptor(InputCtor.prototype, 'value')", source)
        self.assertIn("descriptor.set.call(phone, nextValue)", source)
        self.assertIn("new view.Event('input', { bubbles: true })", source)
        self.assertIn("data-account-phone-preparing", source)
        self.assertIn("const prepareBeforeAppClick = (event) =>", source)
        self.assertIn("form.addEventListener('pointerdown', prepareBeforeAppClick, true);", source)
        self.assertIn("form.addEventListener('click', prepareBeforeAppClick, true);", source)
        self.assertIn("controlled field state before any click-driven EasyStore/reCAPTCHA flow", source)

    def test_verified_account_phone_is_read_only_and_restored_on_submit(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const lockExistingDetailsPhone = (phone, component, hiddenCountry, initialPhone, initialCountry) =>", source)
        self.assertIn("hiddenCountry.getAttribute('data-phone-verified') !== 'true'", source)
        self.assertIn("phone.readOnly = true;", source)
        self.assertIn("phone.setAttribute('data-verified-phone-locked', 'true');", source)
        self.assertIn("component.select.disabled = true;", source)
        self.assertIn("setFrameworkAwarePhoneValue(phone, initialPhone, false);", source)
        self.assertIn("hiddenCountry.value = initialCountry;", source)
        self.assertIn("if (!locked) interceptSubmit(phone, component, hiddenCountry, false);", source)

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
        self.assertEqual(
            re.findall(r"sessionStorage\.setItem\((AUTH_[A-Z_]+)", runtime),
            ["AUTH_COUNTRY_KEY", "AUTH_DIAL_KEY"],
        )

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

    def test_phone_length_stays_within_crm_identity_bounds(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const PHONE_MIN_DIGITS = 7;", source)
        self.assertIn("const PHONE_MAX_DIGITS = 15;", source)
        self.assertIn("/^\\+[1-9]\\d{6,14}$/", source)

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
