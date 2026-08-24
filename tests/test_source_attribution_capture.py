"""Regression tests for the Cloudflare → customer touch attribution handoff."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"
CUSTOMER_TEMPLATES = THEME_ROOT / "templates" / "customers"
WORKER = REPOSITORY_ROOT / "cloudflare" / "attribution-worker" / "src" / "index.js"
JOIN_SCRIPT = REPOSITORY_ROOT / "scripts" / "cloudflare_hubspot_attribution.py"

ATTRIBUTE_TEMPLATES = (
    "account.liquid",
    "activate_account.liquid",
    "details.liquid",
    "register.liquid",
)

CAPTURE = "attribution-click-id"
LEGACY_FIELD = "attribution-click-id-field"
COOKIE = "cb_click_id"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def capture() -> str:
    return read(THEME_ROOT / "snippets" / f"{CAPTURE}.liquid")


def legacy_field() -> str:
    return read(THEME_ROOT / "snippets" / f"{LEGACY_FIELD}.liquid")


def liquid_tags(source: str) -> str:
    without_comments = re.sub(
        r"{%-?\s*comment\s*-?%}.*?{%-?\s*endcomment\s*-?%}",
        "",
        source,
        flags=re.DOTALL,
    )
    return "\n".join(re.findall(r"{%-?.*?-?%}", without_comments))


class CapturePlacementTests(unittest.TestCase):
    def test_layout_includes_capture_in_head_not_legacy_field(self) -> None:
        layout = read(THEME_ROOT / "layout" / "theme.liquid")
        include = layout.index(f"{{% include '{CAPTURE}' %}}")
        self.assertLess(include, layout.index("</head>"))
        self.assertLess(include, layout.index("<body"))
        self.assertNotIn(LEGACY_FIELD, layout)

    def test_capture_has_no_shop_or_settings_lookup(self) -> None:
        tags = liquid_tags(capture())
        self.assertNotIn("shop.", tags)
        self.assertNotIn("settings.", tags)
        self.assertNotIn("for ", tags)
        self.assertNotIn("if ", tags)

    def test_capture_reads_only_customer_id_from_easy_store_identity(self) -> None:
        source = capture()
        self.assertIn("customer.id | default: '' | json", source)
        self.assertNotIn("customer.email", source)
        self.assertNotIn("customer.phone", source)
        self.assertNotIn("customer.first_name", source)
        self.assertNotIn("customer.last_name", source)


class DirectTouchHandoffTests(unittest.TestCase):
    def test_worker_and_theme_agree_on_cookie_and_query_parameter(self) -> None:
        worker = read(WORKER)
        source = capture()
        self.assertIn(f'const CLICK_COOKIE = "{COOKIE}";', worker)
        self.assertIn(f'destination.searchParams.set("{COOKIE}", clickId);', worker)
        self.assertIn(f"var COOKIE = '{COOKIE}';", source)
        self.assertIn(f"var PARAM = '{COOKIE}';", source)

    def test_latest_click_is_posted_directly_to_customer_touch_history(self) -> None:
        source = capture()
        self.assertIn("https://go.cardboard.sg/touch", source)
        self.assertIn("customer_id: String(customerId)", source)
        self.assertIn("click_id: clickId", source)
        self.assertIn("bindTouch(clickId)", source)

    def test_hubspot_join_uses_customer_identity_not_click_id_property(self) -> None:
        join = read(JOIN_SCRIPT)
        self.assertIn('CUSTOMER_ID_PROPERTY = "easystore_customer_id"', join)
        self.assertIn('CUSTOMER_CREATED_AT_PROPERTY = "easystore_customer_created_at"', join)
        self.assertIn("customer_touches", join)
        self.assertNotIn("easystore_attr_click_id", join)
        self.assertNotIn("cc_acquisition_click_id", join)
        self.assertNotIn("ATTRIBUTION_CLICK_ID_PROPERTIES", join)

    def test_click_uuid_is_not_exported_as_a_browser_global(self) -> None:
        self.assertNotIn("window.ccSourceClickId", capture())

    def test_cookie_lifetime_matches_worker(self) -> None:
        ninety_days = 60 * 60 * 24 * 90
        self.assertIn("const CLICK_COOKIE_MAX_AGE = 60 * 60 * 24 * 90;", read(WORKER))
        self.assertIn(f"var NINETY_DAYS_SECONDS = {ninety_days};", capture())


class LegacyEasyStoreFieldRetirementTests(unittest.TestCase):
    def test_only_customer_attribute_pages_include_the_legacy_suppressor(self) -> None:
        rendering = sorted(
            path.name
            for path in CUSTOMER_TEMPLATES.glob("*.liquid")
            if "shop.attribute_settings" in liquid_tags(read(path))
        )
        self.assertEqual(rendering, list(ATTRIBUTE_TEMPLATES))
        for name in rendering:
            self.assertIn(
                f"{{% include '{LEGACY_FIELD}' %}}",
                read(CUSTOMER_TEMPLATES / name),
                name,
            )

    def test_legacy_field_is_never_filled_or_submitted(self) -> None:
        source = legacy_field()
        self.assertIn("setAttribute('disabled', 'disabled')", source)
        self.assertIn("removeAttribute('name')", source)
        self.assertIn("removeAttribute('required')", source)
        self.assertIn("display: none !important", source)
        self.assertNotIn("field.value =", source)
        self.assertNotIn("submitClickId", source)
        self.assertNotIn("window.ccSourceClickId", source)

    def test_legacy_suppressor_becomes_a_noop_after_attribute_deletion(self) -> None:
        source = legacy_field()
        self.assertIn("{% assign attribution_click_id_setting = '' %}", source)
        self.assertIn("{% if attribution_click_id_setting != '' %}", source)


class StoredTransportKeySafetyTests(unittest.TestCase):
    def test_only_worker_shaped_uuid_is_stored_or_bound(self) -> None:
        self.assertRegex(
            capture(),
            r"var CLICK_ID = /\^\[0-9a-f\]\{8}-\[0-9a-f\]\{4}-\[0-9a-f\]\{4}-"
            r"\[0-9a-f\]\{4}-\[0-9a-f\]\{12}\$/i;",
        )
        self.assertIn("CLICK_ID.test(text)", capture())

    def test_cookie_and_storage_writes_are_guarded(self) -> None:
        source = capture()
        remember = source[source.index("function remember(") :]
        remember = remember[: remember.index("\n    }")]
        self.assertEqual(remember.count("try {"), 2)
        self.assertIn("document.cookie", remember)
        self.assertIn("localStorage.setItem", remember)

    def test_cookie_is_only_marked_secure_over_https(self) -> None:
        self.assertIn("window.location.protocol === 'https:'", capture())


if __name__ == "__main__":
    unittest.main()
