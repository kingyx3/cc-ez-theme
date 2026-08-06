from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"
RUNTIME_TEST = REPOSITORY_ROOT / "tests" / "otp_verification_coordinator_runtime_test.js"


class OtpVerificationCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.storefront_script = (
            THEME_ROOT / "assets" / "otp-verification-coordinator.js"
        ).read_text(encoding="utf-8")
        cls.editor_script = (
            THEME_ROOT / "editor_assets" / "otp-verification-coordinator.js"
        ).read_text(encoding="utf-8")
        cls.currencies = (
            THEME_ROOT / "snippets" / "currencies.liquid"
        ).read_text(encoding="utf-8")

    def test_coordinator_loads_immediately_after_otp_owner(self) -> None:
        owner = "<script src=\"{{ 'otp-cell-autofill.js' | asset_url }}\"></script>"
        coordinator = (
            "<script src=\"{{ 'otp-verification-coordinator.js' | asset_url }}\"></script>"
        )
        self.assertIn(owner, self.currencies)
        self.assertIn(coordinator, self.currencies)
        self.assertLess(self.currencies.index(owner), self.currencies.index(coordinator))

    def test_storefront_and_editor_scripts_match(self) -> None:
        self.assertEqual(self.storefront_script, self.editor_script)

    def test_submit_coordination_is_capture_phase_and_idempotent(self) -> None:
        self.assertIn("const activeSubmissions = new WeakSet()", self.storefront_script)
        self.assertIn("documentObject.__cardboardOtpSubmitCoordinatorBound", self.storefront_script)
        self.assertIn("'submit'", self.storefront_script)
        self.assertIn("coordinateSubmit(event, documentObject, windowObject)", self.storefront_script)
        self.assertIn("true,\n    );", self.storefront_script)

    def test_long_lock_is_replaced_by_same_task_reentrancy_protection(self) -> None:
        self.assertIn("delete form.dataset.otpSubmissionInFlight", self.storefront_script)
        self.assertIn("activeSubmissions.has(form)", self.storefront_script)
        self.assertIn("activeSubmissions.add(form)", self.storefront_script)
        self.assertIn("activeSubmissions.delete(form)", self.storefront_script)
        self.assertIn("queueMicrotask", self.storefront_script)

    def test_submit_state_is_reconciled_without_clearing_valid_codes(self) -> None:
        self.assertIn("const reconcileOtpState", self.storefront_script)
        self.assertIn("visibleCode.length === expectedLength", self.storefront_script)
        self.assertIn("proxyCode.length === expectedLength", self.storefront_script)
        self.assertIn("source: 'partial'", self.storefront_script)

    def test_runtime_regression_covers_mobile_desktop_and_follow_up_submit(self) -> None:
        completed = subprocess.run(
            ["node", str(RUNTIME_TEST)],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("OTP verification coordinator runtime regression passed", completed.stdout)


if __name__ == "__main__":
    unittest.main()
