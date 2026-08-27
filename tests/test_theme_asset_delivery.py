"""How the theme delivers its own CSS and JavaScript to a shopper.

Every rule here is about a cost the storefront paid on every page view rather
than about what the page renders. They are easy to undo by accident - a snippet
of inline script is the shortest way to add behaviour to a section - so the
shape that keeps them cheap is pinned.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"

INLINE_SCRIPT = re.compile(
    r"<script(?![^>]*\bsrc=)[^>]*>(?P<body>.*?)</script>", re.DOTALL
)
INLINE_STYLE = re.compile(r"<style[^>]*>(?P<body>.*?)</style>", re.DOTALL)


def read(relative: str) -> str:
    return (THEME_ROOT / relative).read_text(encoding="utf-8")


class EditorAssetsMirrorRuntimeAssetsTests(unittest.TestCase):
    """The editor renders the storefront, so it has to be given the same files.

    `scripts/theme_ci.py` proves the two directories hold the same *names*. Equal
    names with different contents is the drift that matters: the merchant styles
    a page in the editor that the shopper never sees.
    """

    def test_every_asset_is_byte_for_byte_identical(self) -> None:
        assets = THEME_ROOT / "assets"
        for path in sorted(assets.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(assets).as_posix()
            with self.subTest(asset=relative):
                self.assertEqual(
                    path.read_bytes(),
                    (THEME_ROOT / "editor_assets" / relative).read_bytes(),
                )


class HeaderShipsItsCodeAsCacheableAssetsTests(unittest.TestCase):
    """The header renders on every page, so its inline code is never cached.

    Its sticky bar, its disclosure menus and the referral invitation were ~16KB
    of <script> and <style> re-sent inside the HTML of every page view. Only the
    declarations a merchant setting feeds have to be rendered by Liquid.
    """

    def test_the_behaviour_lives_in_deferred_assets(self) -> None:
        header = read("sections/header.liquid")

        self.assertIn(
            "<script src=\"{{ 'header.js' | asset_url }}\" defer=\"defer\"></script>",
            header,
        )
        self.assertIn(
            "<script src=\"{{ 'referral-notification.js' | asset_url }}\" "
            "defer=\"defer\"></script>",
            header,
        )
        self.assertNotIn("class StickyHeader", header)
        self.assertNotIn("class DetailsDisclosure", header)
        self.assertNotIn("localStorage", header)
        self.assertNotIn("fetch(", header)

    def test_the_only_inline_script_left_is_the_referral_config(self) -> None:
        header = read("sections/header.liquid")
        inline = INLINE_SCRIPT.findall(header)

        self.assertEqual(len(inline), 1)
        body = inline[0]
        self.assertIn("window.referralNotificationConfig", body)
        # Three Liquid values and nothing else: no behaviour, no DOM work.
        self.assertNotIn("function", body)
        self.assertNotIn("document", body)

    def test_the_inline_style_holds_only_merchant_settings(self) -> None:
        header = read("sections/header.liquid")

        # The first block is the one rendered on every page. The second is behind
        # `{% if section.settings.transparent_header %}`, so it costs a store that
        # does not use a transparent header nothing at all.
        always_rendered = INLINE_STYLE.findall(header)[0]
        for block in always_rendered.split("}"):
            declarations = block.partition("{")[2]
            if not declarations.strip():
                continue
            with self.subTest(block=" ".join(block.split())[:80]):
                self.assertIn("{{ section.settings.", declarations)

    def test_the_referral_surfaces_are_styled_by_a_cached_stylesheet(self) -> None:
        header = read("sections/header.liquid")
        stylesheet = read("assets/component-referral-notification.css")

        self.assertIn(
            "{{ 'component-referral-notification.css' | asset_url "
            "| stylesheet_tag }}",
            header,
        )
        self.assertNotIn("referral-notification", INLINE_STYLE.findall(header)[0])
        self.assertIn(".referral-notification {", stylesheet)
        self.assertIn(".referral-modal__dialog {", stylesheet)
        self.assertIn("#referralNotification,", stylesheet)

    def test_the_actions_global_js_dispatches_are_still_exported(self) -> None:
        referral = read("assets/referral-notification.js")
        global_js = read("assets/global.js")

        # `global.js` resolves a data-theme-action through `window[name]`, so
        # moving the code into a module scope has to keep these four reachable.
        for action, name in (
            ("dismiss-referral-notification", "dismissReferralNotification"),
            ("open-referral-signup", "goToSignupPage"),
            ("close-mobile-referral", "closeMobileReferralModal"),
            ("open-mobile-referral-signup", "goToSignupPageFromMobile"),
        ):
            with self.subTest(action=action):
                self.assertIn(f"'{action}': ", global_js)
                self.assertIn(f"callThemeFunction('{name}')", global_js)
                self.assertIn(f"window.{name} =", referral)


class NavigationRendersItsIconsOnceTests(unittest.TestCase):
    """`svg-definitions` is a 44-branch case over the theme's whole icon set.

    The browse menu asked it for an icon per node, on both the drawer and the
    desktop flyout, so a catalogue of a few dozen collections re-entered that
    snippet hundreds of times per page for markup that never varies.
    """

    def test_the_icons_are_captured_before_the_catalogue_loop(self) -> None:
        browse = read("snippets/navigation-browse.liquid")

        includes = re.findall(r"{% include 'svg-definitions'[^%]*%}", browse)
        self.assertEqual(len(includes), 3)

        loop_start = browse.index("{% for browse_link in browse_links %}")
        for include in includes:
            with self.subTest(include=include):
                # Each one is captured, once, above the catalogue loop.
                line = next(
                    text for text in browse.splitlines() if include in text
                )
                self.assertTrue(line.startswith("{% capture "))
                self.assertTrue(line.endswith("{% endcapture %}"))
                self.assertLess(browse.index(include), loop_start)

        # The markup itself is emitted from the captured strings.
        self.assertIn("{{ icon_arrow }}", browse)
        self.assertIn("{{ icon_caret }}", browse)
        self.assertIn("{{ icon_caret_rotated }}", browse)

    def test_the_captures_put_the_callers_class_back(self) -> None:
        browse = read("snippets/navigation-browse.liquid")

        # The rotated caret passes `class`, and `include` shares one scope, so
        # without this the icons the surrounding section renders next inherit it.
        save = "{% assign navigation_browse_outer_class = class %}"
        restore = "{% assign class = navigation_browse_outer_class %}"
        self.assertIn(save, browse)
        self.assertIn(restore, browse)
        self.assertLess(browse.index(save), browse.index("{% capture icon_arrow %}"))
        self.assertLess(browse.index("class : 'rotate-90'"), browse.index(restore))
        self.assertLess(
            browse.index(restore),
            browse.index("{% for browse_link in browse_links %}"),
        )


class TheHeadOpensItsConnectionsEarlyTests(unittest.TestCase):
    def test_the_jquery_cdn_is_preconnected_before_it_is_requested(self) -> None:
        layout = read("layout/theme.liquid")

        preconnect = '<link rel="preconnect" href="https://code.jquery.com" crossorigin>'
        self.assertIn(preconnect, layout)
        self.assertIn('<link rel="dns-prefetch" href="https://code.jquery.com">', layout)
        # These two are the only requests that leave EasyStore's hosts, and they
        # block parsing, so the handshake has to be under way before them.
        self.assertLess(
            layout.index(preconnect),
            layout.index("https://code.jquery.com/jquery-3.7.1.min.js"),
        )
        self.assertLess(
            layout.index(preconnect),
            layout.index("https://code.jquery.com/jquery-migrate-3.6.0.min.js"),
        )

    def test_the_last_stylesheets_are_preloaded_without_moving_them(self) -> None:
        layout = read("layout/theme.liquid")
        currencies = read("snippets/currencies.liquid")

        for asset in ("compact-spacing.css", "card-navigation-polish.css"):
            with self.subTest(asset=asset):
                preload = (
                    f"<link rel=\"preload\" href=\"{{{{ '{asset}' | asset_url }}}}\" "
                    "as=\"style\">"
                )
                self.assertIn(preload, layout)
                # Preloaded in the head, still linked last: these two override
                # every section stylesheet, so the cascade needs them at the end
                # of the body even though the download starts with the head.
                self.assertIn(
                    f"{{{{ '{asset}' | asset_url | stylesheet_tag }}}}", currencies
                )
                self.assertLess(layout.index(preload), layout.index("</head>"))

    def test_the_purchase_limit_module_no_longer_blocks_the_page_end(self) -> None:
        currencies = read("snippets/currencies.liquid")

        self.assertIn(
            "<script src=\"{{ 'purchase-limit-feedback.js' | asset_url }}\" "
            "defer=\"defer\"></script>",
            currencies,
        )
        # Every script this snippet loads is deferred.
        for tag in re.findall(r"<script [^>]*src=[^>]*>", currencies):
            with self.subTest(tag=tag):
                self.assertIn('defer="defer"', tag)


class ProductGridsFetchTheirFirstRowEagerlyTests(unittest.TestCase):
    """A lazy image cannot be the largest contentful paint without a delay.

    Every card in every grid was `loading="lazy"`, including the one at the top
    of a collection page, so the browser deliberately waited before starting the
    request the shopper is waiting on.
    """

    CALLERS = (
        "sections/main-collection.liquid",
        "snippets/featured-collection-products.liquid",
    )

    def test_the_card_offers_an_eager_image_and_lowers_the_flag_again(self) -> None:
        card = read("snippets/product-card.liquid")

        self.assertIn(
            '{% if product_card_image_eager %}loading="eager" '
            'fetchpriority="high"{% else %}loading="lazy"{% endif %}',
            card,
        )
        # `include` shares one scope, so an unreset flag would make every later
        # card on the page eager - including cards of sections that never asked.
        self.assertTrue(
            card.rstrip().endswith("{% assign card_image_eager = false %}")
        )
        # The hover image is never the largest contentful paint.
        self.assertIn("product.secondary_image.src", card)
        secondary = card.split("product.secondary_image.src", maxsplit=1)[1]
        self.assertIn('loading="lazy"', secondary.split(">", maxsplit=1)[0])

    def test_each_grid_sets_the_flag_on_every_iteration(self) -> None:
        for caller in self.CALLERS:
            with self.subTest(caller=caller):
                source = read(caller)
                self.assertIn("{% assign card_image_eager = false %}", source)
                self.assertIn("{% assign card_image_eager = true %}", source)
                self.assertIn(
                    "{% if forloop.index <= eager_card_count %}", source
                )
                # Lowered before the branch that raises it, so the reset runs on
                # every pass rather than only on the first row.
                self.assertLess(
                    source.index("{% assign card_image_eager = false %}"),
                    source.index("{% assign card_image_eager = true %}"),
                )


class NoStylesheetIsSentTwiceTests(unittest.TestCase):
    def test_article_css_holds_only_what_the_article_page_owns(self) -> None:
        template = read("templates/article.liquid")
        article = re.sub(
            r"/\*.*?\*/", "", read("assets/article.css"), flags=re.DOTALL
        )
        blog = read("assets/blog.css")
        base = read("assets/base.css")

        # Both are already on the page, and every page carries base.css.
        self.assertIn("{{ 'blog.css' | asset_url | stylesheet_tag }}", template)
        self.assertIn("{{ 'article.css' | asset_url | stylesheet_tag }}", template)

        self.assertNotIn(".article-template", article)
        self.assertIn(".article-template", blog)
        for selector in (
            ".share-button__button",
            ".share-button__message",
            ".share-button__close",
        ):
            with self.subTest(selector=selector):
                self.assertNotIn(selector, article)
                self.assertIn(selector, base)

        self.assertIn(".animate-arrow .icon-wrap .icon-arrow", article)

    def test_no_section_links_a_stylesheet_it_has_commented_out(self) -> None:
        for path in sorted(THEME_ROOT.rglob("*.liquid")):
            source = path.read_text(encoding="utf-8")
            for comment in re.findall(r"<!--.*?-->", source, flags=re.DOTALL):
                with self.subTest(template=path.name):
                    self.assertNotIn("stylesheet_tag", comment)
                    self.assertNotIn("script_tag", comment)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
