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
    def test_no_js_fallback_keeps_easystore_country_code_contract(self) -> None:
        source = SNIPPET.read_text(encoding="utf-8")

        self.assertIn('name="{{ country_code_field_name | escape }}"', source)
        self.assertIn('value="{{ default_country_code | escape }}"', source)
        self.assertIn("data-phone-country-code", source)
        self.assertIn('data-phone-input-id="{{ phone_input_id | escape }}"', source)
        self.assertIn("'account-phone-input.js' | asset_url", source)

    def test_local_number_country_choices_match_crm_normalizer_exactly(self) -> None:
        self.assertEqual(crm_country_dial_codes(), storefront_country_dial_codes())

    def test_ui_adds_country_selector_next_to_existing_phone_field(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("wrapper.className = 'account-phone-input';", source)
        self.assertIn("countryField.className = 'field on_focus account-phone-input__country';", source)
        self.assertIn("label.textContent = 'Country code';", source)
        self.assertIn("other.textContent = 'Other (+ full number)';", source)
        self.assertIn("grid-template-columns: minmax(12rem, 14rem) minmax(0, 1fr);", source)
        self.assertIn("phone.setAttribute('type', 'tel');", source)

    def test_unlisted_country_requires_explicit_international_number(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("For Other, enter the full international phone number starting with +.", source)
        self.assertIn("if (!select.value && !international)", source)
        self.assertIn("phone.value = '+' + international;", source)
        self.assertIn("hiddenCountry.value = '';", source)

    def test_known_international_number_uses_easystore_iso_contract(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("countryMatchesForInternational", source)
        self.assertIn("phone.value = international.slice(country.dial.length);", source)
        self.assertIn("hiddenCountry.value = country.iso;", source)
        self.assertIn("+1 is shared by the US and Canada. Do not guess between them.", source)

    def test_phone_length_stays_within_crm_identity_bounds(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")

        self.assertIn("const PHONE_MIN_DIGITS = 7;", source)
        self.assertIn("const PHONE_MAX_DIGITS = 15;", source)

    def test_runtime_and_editor_assets_stay_identical(self) -> None:
        self.assertEqual(
            RUNTIME.read_text(encoding="utf-8"),
            EDITOR.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
