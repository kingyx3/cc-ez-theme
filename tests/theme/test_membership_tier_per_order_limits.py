import pathlib
import unittest

THEME = pathlib.Path(__file__).resolve().parents[2] / "theme"

class MembershipTierPerOrderTests(unittest.TestCase):
    def test_override_resolves_before_per_order_rule(self):
        row = (THEME / "snippets/per-order-limit-row.liquid").read_text()
        self.assertIn("customer.membership.membership_tier.id", row)
        self.assertIn("per_order_limit_override_tier_id", row)
        self.assertIn("per_order_limit_override_maximum > per_order_limit_row_maximum", row)
        self.assertLess(row.index("per_order_limit_override_tier_id"), row.index("window.perOrderLimitsV1.rules"))
        self.assertIn("{% assign order_limit_tier_id = '' %}", row)
        self.assertIn("{% assign order_limit_tier_maximum = 0 %}", row)

    def test_defaults_remain_unchanged(self):
        config = (THEME / "snippets/per-order-limit-config.liquid").read_text()
        self.assertNotIn("order_limit_tier_id:", config)
        self.assertIn("order_limit_handle: 'MTG-HOB-CBB-EN', order_limit_maximum: 1", config)

if __name__ == "__main__":
    unittest.main()
