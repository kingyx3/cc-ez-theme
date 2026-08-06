from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


class OtpCellAutofillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.storefront_script = (
            THEME_ROOT / "assets" / "otp-cell-autofill.js"
        ).read_text(encoding="utf-8")
        cls.editor_script = (
            THEME_ROOT / "editor_assets" / "otp-cell-autofill.js"
        ).read_text(encoding="utf-8")
        cls.currencies = (
            THEME_ROOT / "snippets" / "currencies.liquid"
        ).read_text(encoding="utf-8")

    def test_otp_fix_is_loaded_after_the_existing_global_assets(self) -> None:
        self.assertIn("otp-cell-autofill.js", self.currencies)
        self.assertIn('defer="defer"', self.currencies)

    def test_storefront_and_editor_scripts_match(self) -> None:
        self.assertEqual(self.storefront_script, self.editor_script)

    def test_cells_are_detected_structurally_rather_than_by_url(self) -> None:
        # The platform renders the verification step under form actions and URLs
        # the theme cannot predict, so detection keys off the widget shape.
        self.assertIn("const looksLikeOtpCell", self.storefront_script)
        self.assertIn("input.maxLength === 1", self.storefront_script)
        self.assertIn("'size') === '1'", self.storefront_script)
        self.assertIn("const findOtpGroups", self.storefront_script)
        self.assertIn("document.querySelectorAll('input')", self.storefront_script)

    def test_cells_outside_a_form_are_still_enhanced(self) -> None:
        self.assertIn("const groupContainer", self.storefront_script)
        self.assertIn("node.contains(candidate)", self.storefront_script)
        self.assertIn("MAX_CONTAINER_DEPTH", self.storefront_script)
        self.assertIn("node !== document.body", self.storefront_script)

    def test_unrelated_code_fields_are_never_treated_as_otp_cells(self) -> None:
        self.assertIn("NON_OTP_NAME_PATTERN", self.storefront_script)
        for token in ("country", "postal", "discount", "search"):
            self.assertIn(token, self.storefront_script)

    def test_autofilled_code_is_distributed_across_otp_cells(self) -> None:
        self.assertIn("const distributeOtpCode", self.storefront_script)
        self.assertIn("digits[index - begin] || ''", self.storefront_script)
        self.assertIn("if (digits.length > 1)", self.storefront_script)
        self.assertIn("cell.addEventListener('input'", self.storefront_script)
        # Some autofill paths only report a "change".
        self.assertIn("cell.addEventListener('change'", self.storefront_script)

    def test_a_full_length_code_always_starts_at_the_first_cell(self) -> None:
        self.assertIn("digits.length >= cells.length", self.storefront_script)

    def test_every_cell_accepts_the_whole_code_for_autofill(self) -> None:
        # maxlength="1" makes browsers truncate the autofilled code to a single
        # digit, which is why only the first cell used to be filled.
        self.assertIn("'maxlength', String(cells.length)", self.storefront_script)
        self.assertIn("'autocomplete', 'one-time-code'", self.storefront_script)

    def test_web_otp_credential_is_spread_over_every_cell(self) -> None:
        self.assertIn("'OTPCredential' in window", self.storefront_script)
        self.assertIn("otp: { transport: ['sms'] }", self.storefront_script)
        self.assertIn("distributeOtpCode(cells, credential.code, 0)", self.storefront_script)

    def test_only_one_change_event_is_emitted_per_distribution(self) -> None:
        # Firing "change" per cell makes widgets that submit on change post the
        # verification twice, which fails with "Customer already exists (phone)".
        self.assertEqual(
            self.storefront_script.count("new Event('change', { bubbles: true })"),
            1,
        )

    def test_duplicate_verification_submits_are_dropped(self) -> None:
        self.assertIn("const guardDuplicateSubmit", self.storefront_script)
        self.assertIn("otpSubmitInFlight", self.storefront_script)
        self.assertIn("event.stopImmediatePropagation()", self.storefront_script)
        self.assertIn("DUPLICATE_SUBMIT_LOCK_MS", self.storefront_script)
        self.assertIn("guardDuplicateSubmit(cells[0].form)", self.storefront_script)

    def test_email_fallback_is_hidden_during_mobile_otp(self) -> None:
        self.assertIn("continue\\s+with\\s+email\\s+instead", self.storefront_script)
        self.assertIn("element.hidden = true", self.storefront_script)
        self.assertIn("mobileOtpFallbackHidden", self.storefront_script)

    def test_single_field_verification_forms_skip_search_boxes(self) -> None:
        self.assertIn("SEARCH_FORM_SELECTOR", self.storefront_script)
        self.assertIn("data-search-history-form", self.storefront_script)
        self.assertIn('role="search"', self.storefront_script)

    def test_dynamic_verification_markup_is_observed(self) -> None:
        self.assertIn("new MutationObserver", self.storefront_script)
        self.assertIn("enhanceDocument()", self.storefront_script)
        self.assertIn("scheduleEnhance", self.storefront_script)


class AccountSubmitGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.global_script = (THEME_ROOT / "assets" / "global.js").read_text(
            encoding="utf-8"
        )
        cls.editor_global_script = (
            THEME_ROOT / "editor_assets" / "global.js"
        ).read_text(encoding="utf-8")
        cls.templates = {
            name: (THEME_ROOT / "templates" / "customers" / f"{name}.liquid").read_text(
                encoding="utf-8"
            )
            for name in ("login", "register", "activate_account")
        }

    def test_storefront_and_editor_globals_match(self) -> None:
        self.assertEqual(self.global_script, self.editor_global_script)

    def test_account_forms_drop_duplicate_submits(self) -> None:
        self.assertIn("function guardSingleAccountSubmit", self.global_script)
        self.assertIn("submitInFlight", self.global_script)
        self.assertIn("event.stopImmediatePropagation()", self.global_script)
        self.assertIn("}, true);", self.global_script)

    def test_the_submit_button_is_never_disabled(self) -> None:
        # A disabled submit control is dropped from the payload and some
        # browsers cancel the in-flight submission along with it.
        self.assertNotIn("button.disabled = true", self.global_script)
        self.assertIn("btn--loading", self.global_script)

    def test_the_lock_is_released_when_the_page_stays_put(self) -> None:
        self.assertIn("window.setTimeout(release", self.global_script)
        self.assertIn("'pageshow', release", self.global_script)

    def test_customer_forms_use_the_shared_guard(self) -> None:
        for name, template in self.templates.items():
            with self.subTest(template=name):
                self.assertIn("guardSingleAccountSubmit", template)
                # global.js is deferred, so the call has to wait for it.
                self.assertIn("DOMContentLoaded", template)
                # The old inline handler dereferenced a missing element.
                self.assertNotIn(".btn').classList.add", template)

    def test_every_guarded_form_actually_has_a_loading_button(self) -> None:
        for name, template in self.templates.items():
            with self.subTest(template=name):
                self.assertIn('type="submit" class="btn"', template)


if __name__ == "__main__":
    unittest.main()
