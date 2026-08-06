from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (
    REPOSITORY_ROOT / "theme" / "templates" / "customers" / "account.liquid"
)


class MembershipCardLayoutTests(unittest.TestCase):
    """The membership card overflowed itself on a phone.

    The QR trigger is a bare <button>, so it inherited `.customer button`:
    12rem min-width, 4rem min-height and an accent fill. That rendered a 192px
    pill which ran past the card's right edge, and the only override was scoped
    to `.card-type_customize`, leaving the simple card - the one this store
    uses - unstyled. The tier name was separately capped at a fixed 220px, so it
    showed an ellipsis whether or not there was room.

    Measured in Chromium at 320, 360, 390 and 1280px: the button is 44px square
    and stays inside the card at every width, and "Basic Membership" renders in
    full from 360px up.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.template = TEMPLATE.read_text(encoding="utf-8")

    def test_the_qr_trigger_is_sized_as_an_icon_button(self) -> None:
        # The element qualifier matters: `.customer button` is (0,1,1), so a
        # bare `.qr-modal-toggle` class selector loses to it.
        self.assertIn(".member-card button.qr-modal-toggle{", self.template)
        self.assertIn("width: 44px;", self.template)
        self.assertIn("height: 44px;", self.template)
        self.assertIn("min-width: 0;", self.template)
        self.assertIn("min-height: 0;", self.template)

    def test_both_card_types_style_the_qr_trigger(self) -> None:
        # The old rule only covered the customize card type.
        self.assertIn(
            ".member-card.card-type_customize button.qr-modal-toggle{",
            self.template,
        )
        self.assertNotIn(".card-type_customize .qr-modal-toggle{", self.template)

    def test_the_tier_name_uses_the_width_the_card_has(self) -> None:
        self.assertNotIn("max-width: 220px;", self.template)
        self.assertIn("font-size: clamp(18px, 5.5vw, 30px);", self.template)
        # Long names still truncate gracefully rather than overflowing.
        self.assertIn("text-overflow: ellipsis;", self.template)

    def test_the_text_column_yields_space_to_the_button(self) -> None:
        # Flex items default to min-width:auto and refuse to shrink; a zero
        # basis sizes the column from the space left after the button.
        self.assertIn(".member-card_detail > div{", self.template)
        self.assertIn(".member-card_detail > div:first-child{", self.template)
        self.assertIn("flex: 1 1 0;", self.template)


if __name__ == "__main__":
    unittest.main()
