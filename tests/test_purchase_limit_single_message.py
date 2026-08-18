from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"


class PurchaseLimitSingleMessageTests(unittest.TestCase):
    """A product form says a limit once.

    It has two places a message can land: the note under the quantity picker and
    the alert under the buttons. They sit a few centimetres apart, and typing an
    over-limit quantity and then clicking Buy Now put the same sentence in both.
    """

    def read(self, relative: str) -> str:
        return (THEME_ROOT / relative).read_text(encoding="utf-8")

    def test_the_note_steps_in_front_of_a_limit_alert(self) -> None:
        product = self.read("assets/product-form.js")

        self.assertIn(
            "if (alertBox && alertBox.dataset.purchaseLimitMessage === 'true') {",
            product,
        )
        self.assertIn("this.hideErrorMsg();", product)

    def test_whoever_writes_the_alert_records_what_it_wrote(self) -> None:
        # Reading the alert's own wording to decide is what the first attempt at
        # this did, and it failed: the refined copy names no limit at all —
        # "You can add 2 more units (2 units per order)." — so the note appeared
        # beside an alert it had been asked to replace.
        product = self.read("assets/product-form.js")
        feedback = self.read("assets/purchase-limit-feedback.js")
        limits = self.read("assets/customer-order-limits.js")

        self.assertIn(
            "container.dataset.purchaseLimitMessage ="
            " this.isQuantityLimitError(html) ? 'true' : 'false';",
            product,
        )
        self.assertIn("container.dataset.purchaseLimitMessage = 'true';", feedback)
        self.assertIn("container.dataset.purchaseLimitMessage = 'false';", feedback)
        self.assertIn("formMessage.dataset.purchaseLimitMessage = 'true';", limits)

    def test_a_blocked_purchase_writes_the_note_when_the_form_has_one(self) -> None:
        limits = self.read("assets/customer-order-limits.js")

        self.assertIn("productForm?.quantityInput", limits)
        self.assertIn("productForm?.quantityLimitMessage", limits)
        self.assertIn("typeof productForm.showQuantityLimit === 'function'", limits)
        # The validator clears a note it considers unsolicited. A click is not
        # unsolicited, so it counts as an interaction or the message vanishes on
        # the next pass.
        self.assertIn("productForm.purchaseLimitInteracted = true;", limits)

    def test_a_store_rejection_stays_in_the_alert(self) -> None:
        # Routing this to the note lost it outright: `setSubmitting` revalidates
        # straight afterwards, and a quantity that no longer breaches the
        # rejected maximum clears the note, leaving no message anywhere.
        feedback = self.read("assets/purchase-limit-feedback.js")

        self.assertIn("const text = format({ ...context, rawMessage: cleanMessage });", feedback)
        self.assertIn("content.textContent = text;", feedback)
        self.assertNotIn("this.showQuantityLimit(text, 'error');", feedback)

    def test_reaching_the_ceiling_says_nothing_only_being_refused_does(self) -> None:
        # Stepping the quantity up to the last unit a shopper may buy is a
        # permitted action, and the plus handler fired on ">= the maximum", so
        # selecting exactly what was allowed produced "Limit: 2 units per
        # customer." The handler cannot see whether `quantity-input` actually
        # stepped the field, so the value before the click is recorded for it.
        feedback = self.read("assets/purchase-limit-feedback.js")

        self.assertIn("stepper.dataset.purchaseLimitQuantityBefore = String(", feedback)
        self.assertIn("{ capture: true }", feedback)
        self.assertIn(
            "if (Number.isFinite(before) && selectedQuantity !== before) return;",
            feedback,
        )

    def test_a_landed_addition_leaves_the_shopper_unwarned(self) -> None:
        # The field keeps the quantity just bought while the allowance behind it
        # shrinks by that much, so revalidating on that number told someone who
        # had successfully added 2 of 3 that they could "add 1 more unit".
        product = self.read("assets/product-form.js")

        self.assertIn("if (cartConfirmed) this.purchaseLimitInteracted = false;", product)

    def test_storefront_and_editor_copies_match(self) -> None:
        for name in (
            "product-form.js",
            "purchase-limit-feedback.js",
            "customer-order-limits.js",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    self.read(f"assets/{name}"),
                    self.read(f"editor_assets/{name}"),
                )


if __name__ == "__main__":
    unittest.main()
