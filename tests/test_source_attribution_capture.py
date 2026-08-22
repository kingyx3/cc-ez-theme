"""The theme is the only place the Cloudflare click id can enter EasyStore.

The Worker mints a click id and records the channel it came from; the join script
reads that channel back out of D1 and writes it onto a HubSpot contact. Neither
end works unless the storefront carries the id from the landing page into an
EasyStore customer attribute, and the parts have to agree on the cookie name, the
value's shape and the attribute's name to do it.

Those agreements are what is pinned here. They are invisible to any single file:
a cookie renamed in the Worker or an attribute renamed in the join script leaves
every test in its own suite passing and the chain silently broken.

The other thing pinned here is the split between the two snippets, because
getting it wrong took the storefront down. `shop.attribute_settings` is populated
on the four customer pages that ask for it; the first version of this feature
looped it from the layout head, so every page in the store - the homepage
included - resolved a shop object it had never touched before, and EasyStore
errored on deploy. The head snippet now reads nothing but the browser, and the
attribute lookup lives only on the pages that already do it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"
CUSTOMER_TEMPLATES = THEME_ROOT / "templates" / "customers"
WORKER = REPOSITORY_ROOT / "cloudflare" / "attribution-worker" / "src" / "index.js"
JOIN_SCRIPT = REPOSITORY_ROOT / "scripts" / "cloudflare_hubspot_attribution.py"

# The customer templates that render `shop.attribute_settings`, and so the ones
# the field snippet is included from.
ATTRIBUTE_TEMPLATES = (
    "account.liquid",
    "activate_account.liquid",
    "details.liquid",
    "register.liquid",
)

CAPTURE = "attribution-click-id"
FIELD = "attribution-click-id-field"
COOKIE = "cb_click_id"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def capture() -> str:
    return read(THEME_ROOT / "snippets" / f"{CAPTURE}.liquid")


def field() -> str:
    return read(THEME_ROOT / "snippets" / f"{FIELD}.liquid")


def liquid_tags(source: str) -> str:
    """Return only the Liquid tags, with comment bodies removed.

    Prose in a `{% comment %}` block describes the very constructs these tests
    forbid, so scanning the raw file would fail on its own explanation.
    """

    without_comments = re.sub(
        r"{%-?\s*comment\s*-?%}.*?{%-?\s*endcomment\s*-?%}",
        "",
        source,
        flags=re.DOTALL,
    )
    return "\n".join(re.findall(r"{%-?.*?-?%}", without_comments))


class TheCaptureSnippetTouchesNoLiquidObjectTests(unittest.TestCase):
    """The rule that broke the storefront, kept by a test rather than a memory."""

    def test_it_reads_no_shop_customer_or_settings_object(self) -> None:
        tags = liquid_tags(capture())

        # Running on every page means every page pays for whatever this reads.
        # `shop.attribute_settings` resolved from the layout head is what took
        # the store down; nothing here may reach for a Liquid object again.
        self.assertNotIn("shop.", tags)
        self.assertNotIn("customer.", tags)
        self.assertNotIn("settings.", tags)

    def test_it_contains_no_liquid_logic_at_all(self) -> None:
        # No loop, no branch, no assignment: there is nothing for EasyStore's
        # Liquid engine to evaluate on a product page or the homepage.
        self.assertEqual(liquid_tags(capture()).strip(), "")

    def test_the_layout_includes_only_the_capture_snippet(self) -> None:
        layout = read(THEME_ROOT / "layout" / "theme.liquid")

        self.assertIn(f"{{% include '{CAPTURE}' %}}", layout)
        # The field snippet must never be reachable from a non-customer page.
        self.assertNotIn(FIELD, layout)

    def test_it_is_included_in_the_head_before_the_body_is_parsed(self) -> None:
        layout = read(THEME_ROOT / "layout" / "theme.liquid")
        include = layout.index(f"{{% include '{CAPTURE}' %}}")

        # The click id arrives as a query parameter on the landing page. A
        # shopper's first tap can navigate away from that URL, so the value has
        # to be stored before the page is interactive.
        self.assertLess(include, layout.index("</head>"))
        self.assertLess(include, layout.index("<body"))


class TheFieldSnippetLivesWhereTheLookupWorksTests(unittest.TestCase):
    def test_every_template_that_renders_attributes_includes_it(self) -> None:
        rendering = sorted(
            path.name
            for path in CUSTOMER_TEMPLATES.glob("*.liquid")
            if "shop.attribute_settings" in liquid_tags(read(path))
        )
        self.assertEqual(rendering, list(ATTRIBUTE_TEMPLATES))
        for name in rendering:
            template = read(CUSTOMER_TEMPLATES / name)
            self.assertIn(f"{{% include '{FIELD}' %}}", template, name)
            self.assertIn(
                'id="DetailAttribute{{ attribute_setting.id }}"',
                template,
                name,
            )

    def test_the_templates_were_not_rewritten_to_unix_line_endings(self) -> None:
        # These templates are predominantly CRLF - `account.liquid` has always
        # been a mix, the rest are pure. Appending the include as text instead of
        # bytes normalized all of it, turning a one-line addition into a
        # 2,400-line rewrite of a production template. What matters is not
        # purity, which was never true, but that CRLF survives: a tool that
        # normalizes takes it to zero.
        # Only the four this feature appends to. `addresses.liquid` is natively
        # LF and is nobody's business here.
        for name in ATTRIBUTE_TEMPLATES:
            data = (CUSTOMER_TEMPLATES / name).read_bytes()
            path = CUSTOMER_TEMPLATES / name
            crlf = data.count(b"\r\n")
            self.assertGreater(crlf, 0, f"{path.name} was normalized to LF")
            self.assertGreater(
                crlf * 2,
                data.count(b"\n"),
                f"{path.name} is no longer predominantly CRLF",
            )

    def test_nothing_else_in_the_theme_reads_attribute_settings(self) -> None:
        readers = sorted(
            path.relative_to(THEME_ROOT).as_posix()
            for path in THEME_ROOT.rglob("*.liquid")
            if "shop.attribute_settings" in liquid_tags(read(path))
        )
        self.assertEqual(
            readers,
            [
                f"snippets/{FIELD}.liquid",
                "templates/customers/account.liquid",
                "templates/customers/activate_account.liquid",
                "templates/customers/details.liquid",
                "templates/customers/register.liquid",
            ],
        )


class TheFieldSnippetUsesOnlyProvenLiquidTests(unittest.TestCase):
    def test_the_title_is_coerced_the_way_the_rest_of_the_theme_coerces(self) -> None:
        # `default: '' | append: '' | downcase | strip` is this theme's idiom for
        # reading a value that may not be a string, used by
        # customer-order-limit-rule and low-inventory-notice alike.
        self.assertIn(
            "| default: '' | append: '' | downcase | strip %}",
            field(),
        )

    def test_titles_are_matched_by_equality_rather_than_array_membership(self) -> None:
        tags = liquid_tags(field())

        # Testing an array with `contains` appears nowhere else in this theme, so
        # it is not known to work on EasyStore's Liquid engine.
        self.assertNotIn("contains", tags)
        self.assertNotIn("| split:", tags)
        self.assertIn("attribution_candidate_title == 'click id'", tags)

    def test_the_recognised_titles_are_all_lowercase(self) -> None:
        # They are compared against a downcased title, so an uppercase letter
        # here is a title that can never match.
        compared = re.findall(r"attribution_candidate_title == '([^']*)'", field())
        self.assertIn("click id", compared)
        for title in compared:
            self.assertEqual(title, title.lower(), title)


class TheChainAgreesOnItsNamesTests(unittest.TestCase):
    def test_the_theme_reads_the_cookie_the_worker_writes(self) -> None:
        self.assertIn(f'const CLICK_COOKIE = "{COOKIE}";', read(WORKER))
        self.assertIn(f"var COOKIE = '{COOKIE}';", capture())

    def test_the_theme_reads_the_query_parameter_the_worker_redirects_with(self) -> None:
        self.assertIn(f'destination.searchParams.set("{COOKIE}", clickId);', read(WORKER))
        self.assertIn(f"var PARAM = '{COOKIE}';", capture())

    def test_the_attribute_the_theme_fills_is_the_property_the_join_reads(self) -> None:
        # The Contact sync names an attribute property after its EasyStore label,
        # slugged: an attribute titled "Click ID" becomes
        # `easystore_attr_click_id`, which is what the join script looks for.
        self.assertIn("== 'click id'", field())
        self.assertIn('"easystore_attr_click_id"', read(JOIN_SCRIPT))

    def test_the_cookie_lifetime_matches_the_worker(self) -> None:
        ninety_days = 60 * 60 * 24 * 90

        self.assertIn("const CLICK_COOKIE_MAX_AGE = 60 * 60 * 24 * 90;", read(WORKER))
        # The storefront refreshes the same cookie, so a shorter window here
        # would quietly shorten the Worker's.
        self.assertIn(f"var NINETY_DAYS_SECONDS = {ninety_days};", capture())

    def test_the_two_snippets_hand_the_value_over_by_one_agreed_name(self) -> None:
        self.assertIn("window.ccSourceClickId = clickId || null;", capture())
        self.assertIn("var clickId = window.ccSourceClickId;", field())


class TheStoredValueIsNeverTrustedTests(unittest.TestCase):
    def test_only_a_worker_shaped_uuid_is_stored_or_submitted(self) -> None:
        # The query parameter is shopper-supplied. Anything that is not the shape
        # `crypto.randomUUID` produces must never reach the customer record.
        self.assertRegex(
            capture(),
            r"var CLICK_ID = /\^\[0-9a-f\]\{8}-\[0-9a-f\]\{4}-\[0-9a-f\]\{4}-"
            r"\[0-9a-f\]\{4}-\[0-9a-f\]\{12}\$/i;",
        )
        self.assertIn("CLICK_ID.test(text)", capture())

    def test_every_source_of_the_value_goes_through_validation(self) -> None:
        source = capture()
        for reader in ("fromCookie", "fromStorage"):
            body = source[source.index(f"function {reader}()") :]
            body = body[: body.index("\n    }")]
            self.assertIn("valid(", body, reader)


class TheAcquisitionIsWrittenOnceTests(unittest.TestCase):
    def test_an_existing_answer_is_never_overwritten(self) -> None:
        self.assertIn("if (!String(field.value || '').trim())", field())

    def test_the_field_is_hidden_and_never_blocks_a_sign_up(self) -> None:
        source = field()
        self.assertIn("display: none !important", source)
        self.assertIn("wrapper.setAttribute('hidden', 'hidden')", source)
        # A merchant marking the attribute required must not make an invisible
        # input refuse the form.
        self.assertIn("field.removeAttribute('required')", source)

    def test_the_field_is_hidden_by_id_rather_than_by_position(self) -> None:
        # Every template renders attributes from the same loop; the id is the
        # only stable handle.
        self.assertIn("#DetailAttribute{{ attribution_click_id_setting }}", field())


class AStoreWithoutTheAttributeIsUntouchedTests(unittest.TestCase):
    def test_no_matching_attribute_setting_emits_nothing(self) -> None:
        source = field()

        self.assertIn("{% assign attribution_click_id_setting = '' %}", source)
        self.assertIn("{% if attribution_click_id_setting != '' %}", source)
        # Neither the stylesheet nor the script is rendered at all, so a store
        # that never creates the attribute carries no dead markup.
        self.assertLess(
            source.index("{% if attribution_click_id_setting"),
            source.index("<style>"),
        )
        self.assertLess(source.index("<script>"), source.rindex("{% endif %}"))

    def test_the_click_id_is_still_captured_without_the_attribute(self) -> None:
        # Creating the attribute later must lose nothing, so capture cannot
        # depend on the field existing - and it cannot, being a separate snippet.
        self.assertNotIn("DetailAttribute", capture())
        self.assertIn("remember(fromUrl)", capture())


class TheSnippetSurvivesABrowserThatRefusesStorageTests(unittest.TestCase):
    def test_cookie_and_storage_writes_are_both_guarded(self) -> None:
        source = capture()
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
        self.assertIn("window.location.protocol === 'https:'", capture())


if __name__ == "__main__":
    unittest.main()
