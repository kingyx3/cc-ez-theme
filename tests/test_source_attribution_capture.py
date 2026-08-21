"""The theme is the only place the Cloudflare click id can enter EasyStore.

The Worker mints a click id and records the channel it came from; the join script
reads that channel back out of D1 and writes it onto a HubSpot contact. Neither
end works unless the storefront carries the id from the landing page into an
EasyStore customer attribute, and the three parts have to agree on the cookie
name, the value's shape and the attribute's name to do it.

Those agreements are what is pinned here. They are invisible to any single file:
a cookie renamed in the Worker or an attribute renamed in the join script leaves
every test in its own suite passing and the chain silently broken.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"
WORKER = REPOSITORY_ROOT / "cloudflare" / "attribution-worker" / "src" / "index.js"
JOIN_SCRIPT = REPOSITORY_ROOT / "scripts" / "cloudflare_hubspot_attribution.py"

SNIPPET = "attribution-click-id"
COOKIE = "cb_click_id"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def snippet() -> str:
    return read(THEME_ROOT / "snippets" / f"{SNIPPET}.liquid")


class TheSnippetIsWiredIntoEveryPageTests(unittest.TestCase):
    def test_the_layout_includes_it(self) -> None:
        self.assertIn(f"{{% include '{SNIPPET}' %}}", read(THEME_ROOT / "layout" / "theme.liquid"))

    def test_it_is_included_in_the_head_before_the_body_is_parsed(self) -> None:
        layout = read(THEME_ROOT / "layout" / "theme.liquid")
        include = layout.index(f"{{% include '{SNIPPET}' %}}")

        # The click id arrives as a query parameter on the landing page. A
        # shopper's first tap can navigate away from that URL, so the value has
        # to be stored before the page is interactive.
        self.assertLess(include, layout.index("</head>"))
        self.assertLess(include, layout.index("<body"))


class TheChainAgreesOnItsNamesTests(unittest.TestCase):
    def test_the_theme_reads_the_cookie_the_worker_writes(self) -> None:
        self.assertIn(f'const CLICK_COOKIE = "{COOKIE}";', read(WORKER))
        self.assertIn(f"var COOKIE = '{COOKIE}';", snippet())

    def test_the_theme_reads_the_query_parameter_the_worker_redirects_with(self) -> None:
        self.assertIn(f'destination.searchParams.set("{COOKIE}", clickId);', read(WORKER))
        self.assertIn(f"var PARAM = '{COOKIE}';", snippet())

    def test_the_attribute_the_theme_fills_is_the_property_the_join_reads(self) -> None:
        # The Contact sync names an attribute property after its EasyStore label,
        # slugged: an attribute titled "Click ID" becomes
        # `easystore_attr_click_id`, which is what the join script looks for.
        self.assertIn("'click id", snippet())
        self.assertIn('"easystore_attr_click_id"', read(JOIN_SCRIPT))

    def test_the_cookie_lifetime_matches_the_worker(self) -> None:
        worker = read(WORKER)
        ninety_days = 60 * 60 * 24 * 90

        self.assertIn("const CLICK_COOKIE_MAX_AGE = 60 * 60 * 24 * 90;", worker)
        # The storefront refreshes the same cookie, so a shorter window here
        # would quietly shorten the Worker's.
        self.assertIn(f"var NINETY_DAYS_SECONDS = {ninety_days};", snippet())


class TheStoredValueIsNeverTrustedTests(unittest.TestCase):
    def test_only_a_worker_shaped_uuid_is_stored_or_submitted(self) -> None:
        # The query parameter is shopper-supplied. Anything that is not the shape
        # `crypto.randomUUID` produces must never reach the customer record.
        self.assertRegex(
            snippet(),
            r"var CLICK_ID = /\^\[0-9a-f\]\{8}-\[0-9a-f\]\{4}-\[0-9a-f\]\{4}-"
            r"\[0-9a-f\]\{4}-\[0-9a-f\]\{12}\$/i;",
        )
        self.assertIn("CLICK_ID.test(text)", snippet())

    def test_every_source_of_the_value_goes_through_validation(self) -> None:
        source = snippet()
        for reader in ("fromCookie", "fromStorage"):
            body = source[source.index(f"function {reader}()") :]
            body = body[: body.index("\n    }")]
            self.assertIn("valid(", body, reader)


class TheAcquisitionIsWrittenOnceTests(unittest.TestCase):
    def test_an_existing_answer_is_never_overwritten(self) -> None:
        # The cookie is last touch; the attribute records how the account was
        # acquired. `details.liquid` and `account.liquid` repopulate the field
        # from `customer.attributes` while the page parses, so a value present by
        # the time this runs is one EasyStore already holds.
        self.assertIn("if (!String(field.value || '').trim())", snippet())

    def test_the_field_is_hidden_and_never_blocks_a_sign_up(self) -> None:
        source = snippet()
        self.assertIn("display: none !important", source)
        self.assertIn("wrapper.setAttribute('hidden', 'hidden')", source)
        # A merchant marking the attribute required must not make an invisible
        # input refuse the form.
        self.assertIn("field.removeAttribute('required')", source)

    def test_the_field_is_hidden_by_id_rather_than_by_position(self) -> None:
        # Every template renders attributes from the same loop over
        # `shop.attribute_settings`; the id is the only stable handle.
        self.assertIn("#DetailAttribute{{ attribution_click_id_setting }}", snippet())

    def test_every_template_that_renders_attributes_is_covered(self) -> None:
        # A new customer attribute appears as a visible input on all of these.
        # The snippet hides it from the layout head, which reaches every one; a
        # template added to this list later needs no change, but a template that
        # renders attributes some other way would.
        rendering = sorted(
            path.name
            for path in (THEME_ROOT / "templates" / "customers").glob("*.liquid")
            if "shop.attribute_settings" in read(path)
        )
        self.assertEqual(
            rendering,
            ["account.liquid", "activate_account.liquid", "details.liquid", "register.liquid"],
        )
        for name in rendering:
            self.assertIn(
                'id="DetailAttribute{{ attribute_setting.id }}"',
                read(THEME_ROOT / "templates" / "customers" / name),
                name,
            )


class AStoreWithoutTheAttributeIsUntouchedTests(unittest.TestCase):
    def test_no_matching_attribute_setting_means_no_markup_and_no_writes(self) -> None:
        source = snippet()

        self.assertIn("{% assign attribution_click_id_setting = '' %}", source)
        self.assertIn("{% if attribution_click_id_setting != '' %}", source)
        # Nothing to fill, so the script stops before touching the form - but
        # after storing the id, so creating the attribute later loses nothing.
        self.assertIn("if (!SETTING_ID || !clickId) return;", source)
        self.assertLess(source.index("remember(fromUrl)"), source.index("!SETTING_ID"))

    def test_the_recognised_titles_are_matched_case_insensitively(self) -> None:
        source = snippet()
        self.assertIn("| downcase | strip", source)
        titles = re.search(
            r"attribution_click_id_titles = '([^']+)' \| split",
            source,
        )
        self.assertIsNotNone(titles)
        self.assertIn("click id", titles.group(1).split("|"))


class TheSnippetSurvivesABrowserThatRefusesStorageTests(unittest.TestCase):
    def test_cookie_and_storage_writes_are_both_guarded(self) -> None:
        source = snippet()
        remember = source[source.index("function remember(") :]
        remember = remember[: remember.index("\n    }")]

        # Private browsing throws on localStorage, and a browser refusing
        # cookies throws on document.cookie. Neither may break a page.
        self.assertEqual(remember.count("try {"), 2)
        self.assertIn("document.cookie", remember)
        self.assertIn("localStorage.setItem", remember)

    def test_the_cookie_is_only_marked_secure_over_https(self) -> None:
        # A local or preview storefront on http would otherwise set a cookie the
        # browser immediately discards.
        self.assertIn("window.location.protocol === 'https:'", snippet())


if __name__ == "__main__":
    unittest.main()
