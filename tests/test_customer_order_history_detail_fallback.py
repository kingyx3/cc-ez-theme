from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "theme"


class CustomerOrderHistoryDetailFallbackTests(unittest.TestCase):
    def read(self, path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    def test_runtime_and_editor_purchase_limit_assets_match(self) -> None:
        self.assertEqual(
            self.read("assets/customer-order-limits.js"),
            self.read("editor_assets/customer-order-limits.js"),
        )

    def test_detail_fallback_is_scoped_to_the_purchase_limit_loader(self) -> None:
        snippet = self.read("snippets/customer-order-limits.liquid")
        limits = self.read("assets/customer-order-limits.js")

        self.assertFalse((ROOT / "assets/customer-order-history-fallback.js").exists())
        self.assertFalse((ROOT / "editor_assets/customer-order-history-fallback.js").exists())
        self.assertNotIn("customer-order-history-fallback.js", snippet)
        self.assertIn("customer-order-limits.js", snippet)
        self.assertIn("const hydrateHistoryDetails =", limits)
        self.assertIn(
            ".then((documentPayload) => hydrateHistoryDetails(documentPayload, detailFetched));",
            limits,
        )

        # The OTP regression came back when the detail fallback wrapped the
        # browser's shared fetch API and returned a synthetic Response. History
        # enrichment must stay inside the loader that owns its requests.
        self.assertNotIn("window.fetch =", limits)
        self.assertNotIn("new Response(", limits)
        self.assertNotIn("nativeFetch", limits)

    def test_no_theme_asset_replaces_the_browser_fetch_api(self) -> None:
        replacement = re.compile(r"\bwindow\.fetch\s*=")
        for directory in (ROOT / "assets", ROOT / "editor_assets"):
            for path in directory.glob("*.js"):
                with self.subTest(path=path.relative_to(ROOT)):
                    self.assertNotRegex(path.read_text(encoding="utf-8"), replacement)

    def test_only_empty_account_history_payloads_are_hydrated(self) -> None:
        limits = self.read("assets/customer-order-limits.js")
        self.assertIn("existingLines.length", limits)
        self.assertIn("payloadDiagnostics.ordersSeen", limits)
        self.assertIn("article.flex-table-tr", limits)
        self.assertIn("/account/orders/", limits)
        self.assertIn("const HISTORY_MAX_DETAIL_REQUESTS = 24;", limits)
        self.assertIn("const detailFetched = new Set();", limits)

    def test_order_details_supply_handle_quantity_and_stable_identity(self) -> None:
        limits = self.read("assets/customer-order-limits.js")
        self.assertIn(".product-qty-badge", limits)
        self.assertIn('a[href*="/products/"]', limits)
        self.assertIn("detail:${token}:${index}", limits)
        self.assertIn(".label-tag-alert", limits)

    def test_history_loading_stays_off_authentication_and_profile_steps(self) -> None:
        limits = self.read("assets/customer-order-limits.js")
        self.assertIn(
            "const AUTH_PATH = /^\\/account\\/(login|register|recover|auth|activate|reset)/i;",
            limits,
        )
        self.assertIn("#otp-form", limits)
        self.assertIn(".otp-input", limits)
        self.assertIn("window.ccProfileCompletionRequired === true", limits)
        self.assertIn(
            "if (shopperSignedOut() || accountSetupInProgress() || !historySupported())",
            limits,
        )


if __name__ == "__main__":
    unittest.main()
