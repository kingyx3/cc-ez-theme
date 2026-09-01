"""Delivery guardrails for account-only DOM work loaded on every page."""
from __future__ import annotations

import unittest
from pathlib import Path


THEME = Path(__file__).resolve().parents[1] / "theme"


def read(asset: str) -> str:
    return (THEME / "assets" / asset).read_text(encoding="utf-8")


class AccountCopyDeliveryTests(unittest.TestCase):
    def test_recovery_copy_checks_for_a_step_before_the_broad_dom_scan(self) -> None:
        script = read("account-recovery-copy.js")
        guard = "if (!hasRecoveryStep()) return;"
        scan = "rewriteWithin(document.body);"

        self.assertEqual(script.count(guard), 2)
        self.assertLess(script.index(guard), script.index(scan))

    def test_otp_copy_checks_for_a_step_before_walking_links_and_buttons(self) -> None:
        script = read("account-otp-copy.js")
        guard = "if (!hasAccountStep()) return;"
        scan = "hideEmailSignup();"

        self.assertEqual(script.count(guard), 2)
        self.assertLess(script.index(guard), script.index(scan))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
