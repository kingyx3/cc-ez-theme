"""Regression guardrails for avoiding unused assets on public storefront pages."""
from __future__ import annotations

import unittest
from pathlib import Path

from liquid import Template


THEME = Path(__file__).resolve().parents[2] / "theme"


def read(relative_path: str) -> str:
    return (THEME / relative_path).read_text(encoding="utf-8")


class StorefrontAssetBudgetTests(unittest.TestCase):
    def test_listing_cart_assets_follow_the_same_global_toggle_as_the_button(self) -> None:
        card = read("snippets/product-card.liquid")
        toggle = "{% if show_listing_add_to_cart %}"
        asset_guard = "{% unless product_card_cart_controls_assets_loaded %}"
        css = "component-product-card-cart-controls.css"
        js = "product-card-cart-feedback.js"
        button = "<add-to-cart-button>"

        self.assertIn("settings.show_add_to_cart_button == false", card)
        self.assertIn("settings.show_add_to_cart_button == 0", card)
        self.assertIn("settings.show_add_to_cart_button == '0'", card)
        self.assertEqual(card.count("{% assign show_listing_add_to_cart = true %}"), 1)
        self.assertEqual(card.count(toggle), 2)
        self.assertLess(card.index(toggle), card.index(asset_guard))
        self.assertLess(card.index(asset_guard), card.index(css))
        self.assertLess(card.index(css), card.index(js))
        self.assertLess(card.index(js), card.index(button))
        # One set of asset tags per page even with many product cards.
        self.assertEqual(card.count(css), 1)
        self.assertEqual(card.count(js), 1)

    def test_account_details_validation_is_not_loaded_on_public_templates(self) -> None:
        layout = read("layout/theme.liquid")
        script = "account-details-validation.js"
        guard = "{% if template contains 'customers' and template contains 'details' %}"
        self.assertEqual(layout.count(script), 1)
        self.assertIn(guard, layout)
        self.assertLess(layout.index(guard), layout.index(script))
        self.assertIn("{% endif %}", layout[layout.index(script):layout.index(script) + 150])

    def test_performance_workflow_observes_desktop_and_mobile(self) -> None:
        workflow = (
            THEME.parent / ".github" / "workflows" / "performance-observability.yml"
        ).read_text(encoding="utf-8")
        script = (
            THEME.parent / "tests" / "e2e" / "performance.spec.js"
        ).read_text(encoding="utf-8")
        self.assertIn("project: [chromium-desktop, mobile-chrome]", workflow)
        self.assertIn("- name: Validate recorded observations", workflow)
        self.assertIn("Insufficient successful performance samples", workflow)
        self.assertNotIn("continue-on-error: true", workflow)
        self.assertIn('playwright test tests/e2e/performance.spec.js --project=', workflow)
        self.assertIn('browserProject: testInfo.project.name', script)

    def test_listing_cart_toggle_renders_for_all_easystore_setting_types(self) -> None:
        """Exercise the Liquid condition, not only the presence of its source text."""
        card = read("snippets/product-card.liquid")
        start = card.index("{% assign show_listing_add_to_cart = true %}")
        end = card.index("{% endif %}", start) + len("{% endif %}")
        guard = card[start:end]
        source = guard + "{% if show_listing_add_to_cart %}ENABLED{% else %}DISABLED{% endif %}"
        for value, expected in (
            (False, "DISABLED"),
            (0, "DISABLED"),
            ("0", "DISABLED"),
            (True, "ENABLED"),
            (1, "ENABLED"),
            ("1", "ENABLED"),
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    Template(source).render(settings={"show_add_to_cart_button": value}).strip(),
                    expected,
                )

    def test_account_validation_renders_only_for_details_template(self) -> None:
        layout = read("layout/theme.liquid")
        guard = "{% if template contains 'customers' and template contains 'details' %}"
        start = layout.index(guard)
        end = layout.index("{% endif %}", start) + len("{% endif %}")
        source = layout[start:end].replace(
            '<script src="{{ \'account-details-validation.js\' | asset_url }}" defer="defer"></script>',
            "VALIDATION_LOADED",
        )
        for template, expected in (
            ("customers/details", True),
            ("customers/login", False),
            ("customers/orders", False),
            ("customers/register", False),
            ("product", False),
            ("collection", False),
        ):
            with self.subTest(template=template):
                rendered = Template(source).render(template=template)
                self.assertEqual("VALIDATION_LOADED" in rendered, expected)

    def test_global_login_redirect_precedes_customer_only_guard(self) -> None:
        layout = read("layout/theme.liquid")
        self.assertLess(
            layout.index("account-login-redirect.js"),
            layout.index("{% if template contains 'customers' and template contains 'details' %}"),
        )

    def test_grid_images_decode_without_blocking_the_main_thread(self) -> None:
        card = read("snippets/product-card.liquid")
        main = card.split('srcset="{{ product.featured_image.src', 1)[1].split(">", 1)[0]
        self.assertIn('decoding="async"', main)
        self.assertIn('loading="eager"', main)
        self.assertIn('loading="lazy"', main)
        self.assertIn('fetchpriority="high"', main)


if __name__ == "__main__":
    unittest.main()
