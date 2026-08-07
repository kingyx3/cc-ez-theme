"""The limit script must send nothing from the pages a shopper signs in on.

`customer-order-limits.js` loads purchase history by crawling `/account/orders`
with `credentials: 'same-origin'`, following every order tab up to
`HISTORY_MAX_REQUESTS`. Its guard against doing that while signed out was
`shopperSignedOut()`, and that returned false for any path under `/account/` -
including `/account/login`, `/account/register` and `/account/auth`, which are
the pages a shopper is on precisely *because* they are not signed in.

So every visit to the login page and to EasyStore's phone OTP step at
`/account/auth` fired a burst of cookie-bearing requests at a protected endpoint,
in the middle of a verification the theme knows nothing about. The reported
symptom was no OTP SMS arriving at all.

These assertions execute the real asset rather than reading it, because the
defect is behavioural: the source never mentions `/account/auth`, so no string
assertion over it would have caught this or would catch its return.

The probe's DOMParser stub returns no payload, so the crawl stops after its
first request. That is deliberate - the property under test is "any request at
all", not how far the crawl gets.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "theme"
PROBE = Path(__file__).resolve().parent / "js" / "auth_page_history_probe.js"

NODE = shutil.which("node")
# Skipping is for a developer with no node on PATH. CI runners always have it,
# so a missing binary there is a broken build, not a reason to pass quietly.
REQUIRE_NODE = bool(os.environ.get("CI"))

# Every path EasyStore uses to sign a shopper in, verify them, or recover them.
AUTH_ENTRY_PATHS = (
    "/account/login",
    "/account/register",
    "/account/auth",
    "/account/recover",
    "/account/activate",
    "/account/reset",
    "/account/guest",
)

# Pages where loading history is the whole point of the feature.
SHOPPING_PATHS = ("/products/some-product", "/collections/all", "/cart", "/account/orders")

ASSETS = ("assets", "editor_assets")


@unittest.skipIf(NODE is None and not REQUIRE_NODE, "node is not on PATH")
class AuthPageHistoryRequestTests(unittest.TestCase):
    def probe(self, directory: str, pathname: str, markup: str = "none") -> dict:
        if NODE is None:
            self.fail("node is required in CI: this is the only behavioural check here.")
        asset = THEME / directory / "customer-order-limits.js"
        result = subprocess.run(
            [NODE, str(PROBE), str(asset), pathname, markup],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return json.loads(result.stdout)

    def test_the_script_runs_at_all_in_the_probe(self) -> None:
        # Without this, an asset that threw on load would pass every assertion
        # below by making no requests.
        for directory in ASSETS:
            with self.subTest(directory=directory):
                self.assertTrue(self.probe(directory, "/products/some-product")["ran"])

    def test_no_request_leaves_an_auth_entry_page(self) -> None:
        for directory in ASSETS:
            for pathname in AUTH_ENTRY_PATHS:
                with self.subTest(directory=directory, path=pathname):
                    report = self.probe(directory, pathname)
                    self.assertTrue(report["authEntryPage"])
                    self.assertEqual([], report["requested"])

    def test_the_otp_step_is_covered_whatever_the_header_renders(self) -> None:
        # The sign-in markers are the other input to the old guard, so the OTP
        # page has to stay silent under all three.
        for markup in ("none", "in", "out"):
            with self.subTest(markup=markup):
                self.assertEqual(
                    [], self.probe("assets", "/account/auth", markup)["requested"]
                )

    def test_history_still_loads_where_a_purchase_can_happen(self) -> None:
        # The gate must be the auth pages, not history loading in general.
        for pathname in SHOPPING_PATHS:
            with self.subTest(path=pathname):
                report = self.probe("assets", pathname)
                self.assertFalse(report["authEntryPage"])
                self.assertEqual(["/account/orders"], report["requested"])

    def test_storefront_and_editor_assets_stay_mirrored(self) -> None:
        self.assertEqual(
            (THEME / "assets" / "customer-order-limits.js").read_text(encoding="utf-8"),
            (THEME / "editor_assets" / "customer-order-limits.js").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
