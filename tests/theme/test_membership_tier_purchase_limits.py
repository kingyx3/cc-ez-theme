import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2] / "theme"

class MembershipTierLimitTests(unittest.TestCase):
    def test_override_resolves_before_rule_is_published(self):
        source = (ROOT / "snippets/customer-order-limit-row.liquid").read_text()
        self.assertIn("customer.membership.membership_tier.id", source)
        self.assertIn("customer_order_limit_override_tier_id", source)
        self.assertIn("customer_order_limit_override_maximum > customer_order_limit_row_maximum", source)
        self.assertLess(source.index("customer_order_limit_override_tier_id"), source.index("{% include 'customer-order-limit-rule'"))
        self.assertIn("{% assign limit_tier_id = '' %}", source)
        self.assertIn("{% assign limit_tier_maximum = 0 %}", source)

    def test_no_default_product_limit_changes(self):
        config = (ROOT / "snippets/customer-order-limit-config.liquid").read_text()
        self.assertNotIn("limit_tier_id:", config)
        self.assertIn("limit_handle: '1010-drop-06', limit_maximum: 1", config)

if __name__ == "__main__":
    unittest.main()
