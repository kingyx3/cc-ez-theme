"""The sign-in redirect a purchase surface starts has to be finished by the theme.

`customer-order-limits.js` sends a guest who tries to buy a limited product to
`/account/login?redirect_uri=<the page>`. EasyStore ignores that parameter and
lands the customer on its own account page, so the shopper who clicked Buy Now
arrived at their order history. `account-login-redirect.js` closes the gap by
remembering the target and completing the trip once the page proves the shopper
is signed in.

Behaviour is asserted by `e2e/login-redirect.spec.js`, which runs the real module
through real page loads. What is asserted here is the wiring behaviour cannot see:
that the module ships in both asset trees, that it loads on every page rather than
only on account templates, and that the two files still agree on the parameter
they hand each other.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THEME_ROOT = REPOSITORY_ROOT / "theme"

MODULE = "account-login-redirect.js"


def code_only(source: str) -> str:
    """Strip comments so assertions describe behaviour, not prose."""
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return "\n".join(
        line for line in without_blocks.splitlines()
        if not line.strip().startswith("//")
    )


def read(relative: str) -> str:
    return (THEME_ROOT / relative).read_text(encoding="utf-8")


class LoginRedirectShipsWithTheThemeTests(unittest.TestCase):
    def test_the_module_is_mirrored_into_the_editor_assets(self) -> None:
        self.assertEqual(read(f"assets/{MODULE}"), read(f"editor_assets/{MODULE}"))

    def test_the_layout_loads_it_on_every_page(self) -> None:
        layout = read("layout/theme.liquid")

        # EasyStore chooses the page a signed-in customer lands on, so the
        # module cannot be scoped to the customer templates: the landing page
        # may be any page the store serves.
        self.assertIn(
            f"""<script src="{{{{ '{MODULE}' | asset_url }}}}" defer="defer"></script>""",
            layout,
        )
        customer_only = layout.index("{% if template contains 'customers' %}")
        self.assertLess(layout.index(MODULE), customer_only)

    def test_the_signed_in_markers_match_the_ones_the_theme_renders(self) -> None:
        module = code_only(read(f"assets/{MODULE}"))
        limits = read("assets/customer-order-limits.js")
        layout = read("layout/theme.liquid")
        header = read("sections/header.liquid")

        markers = (
            "'body.customer-logged-in, [data-customer-authenticated=\"true\"], "
            "a[href^=\"/account/logout\"]'"
        )
        # One definition of "signed in" across the redirect and the limits, and
        # both halves of it are really rendered by the theme.
        self.assertIn(markers, module)
        self.assertIn(markers, limits)
        self.assertIn("{% if customer %}customer-logged-in {% endif %}", layout)
        self.assertIn('data-customer-authenticated="true"', header)


class LoginRedirectRefusesUnsafeTargetsTests(unittest.TestCase):
    def test_only_a_same_origin_path_is_ever_followed(self) -> None:
        module = code_only(read(f"assets/{MODULE}"))

        # A target is validated in one place, and every source of one - the URL
        # parameter and the stored entry - goes through it.
        self.assertEqual(module.count("const safeTarget = (value) =>"), 1)
        self.assertIn(
            "return safeTarget(new URLSearchParams(window.location.search).get('redirect_uri'));",
            module,
        )
        self.assertIn("return safeTarget(pending && pending.target);", module)
        self.assertIn("if (!target || target.charAt(0) !== '/') return '';", module)
        self.assertIn("if (/^\\/[/\\\\]/.test(target)) return '';", module)
        self.assertIn("if (/^\\/account(\\/|$)/i.test(target)) return '';", module)

    def test_the_stored_target_expires_and_is_consumed_once(self) -> None:
        module = code_only(read(f"assets/{MODULE}"))

        self.assertIn("const MAX_AGE_MS = 30 * 60 * 1000;", module)
        self.assertIn("if (new Date().getTime() - storedAt > MAX_AGE_MS) return '';", module)
        # Removed as it is read, so a target can never divert a second sign-in.
        self.assertIn("window.sessionStorage.removeItem(KEY);", module)
        self.assertLess(
            module.index("window.sessionStorage.removeItem(KEY);"),
            module.index("if (!raw) return '';"),
        )

    def test_the_platform_login_post_is_left_alone(self) -> None:
        module = code_only(read(f"assets/{MODULE}"))
        login = read("templates/customers/login.liquid")

        # Writing into EasyStore's account forms and its one-time-code cells is
        # what once broke signup outright. This module names them in a selector
        # and asks whether they are on the page; it writes nothing, submits
        # nothing, dispatches nothing, and listens to nothing but the document's
        # own ready event.
        for forbidden in (".value =", ".submit(", "dispatchEvent", "MutationObserver"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, module)
        self.assertEqual(module.count("document.addEventListener"), 1)
        self.assertIn("document.addEventListener('DOMContentLoaded', start);", module)
        # Every form and cell reference lives in that one selector list.
        self.assertEqual(module.count("form[action"), 2)
        self.assertEqual(module.count(".otp-input"), 1)
        self.assertEqual(module.count("document.querySelector(AUTHENTICATING_MARKUP)"), 1)
        self.assertIn('<form id="form-login" action="/account/login" method="post">', login)

    def test_a_page_still_asking_for_a_step_is_never_left(self) -> None:
        module = code_only(read(f"assets/{MODULE}"))

        # Reported from the live store: EasyStore counts a shopper who has
        # passed the mobile-number step as a customer, so the signed-in markers
        # are all present while the one-time code is still outstanding. Reading
        # them there threw the shopper to the product page unauthenticated.
        self.assertIn(
            "  const stillAuthenticating = () => (\n"
            "    AUTH_PATH.test(path()) || Boolean(document.querySelector(AUTHENTICATING_MARKUP))\n"
            "  );",
            module,
        )
        # The step is checked before the markers, and returns without leaving.
        self.assertIn(
            "    if (stillAuthenticating()) {\n"
            "      if (requested) store(requested);\n"
            "      return;\n"
            "    }\n"
            "\n"
            "    if (!signedIn()) return;",
            module,
        )
        self.assertLess(
            module.index("stillAuthenticating()"),
            module.index("if (!signedIn()) return;"),
        )
        # The markup half matters on its own: the OTP step renders no form, and
        # the platform owns its URL, so neither signal can carry the check alone.
        for marker in ("#otp-form", ".otp-input", 'input[name="customer[password]"]'):
            with self.subTest(marker=marker):
                self.assertIn(marker, module)


class LoginRedirectFinishesBeforeTheLandingPagePaintsTests(unittest.TestCase):
    """The deferred module runs at DOMContentLoaded, which is a paint too late.

    Reported from the live store: EasyStore's account page was visible for a
    moment on the way to the product. `snippets/login-redirect-boot.liquid` runs
    in the head instead, before the body is parsed, so the trip finishes without
    that page appearing.
    """

    BOOT = "snippets/login-redirect-boot.liquid"

    def test_it_runs_in_the_head_before_anything_else_does(self) -> None:
        layout = read("layout/theme.liquid")

        self.assertIn("{% include 'login-redirect-boot' %}", layout)
        # Before the platform's own header scripts and before the deferred
        # module: everything after this assumes the page it is on is staying.
        self.assertLess(
            layout.index("{% include 'login-redirect-boot' %}"),
            layout.index("{{ content_for_header }}"),
        )
        self.assertLess(
            layout.index("{% include 'login-redirect-boot' %}"),
            layout.index(MODULE),
        )
        self.assertLess(layout.index("{% include 'login-redirect-boot' %}"), layout.index("<body"))

    def test_it_is_inline_and_only_rendered_for_a_customer(self) -> None:
        boot = read(self.BOOT)

        # An external script early enough to beat the paint would block parsing
        # on every page of the store, so this one is inline.
        self.assertIn("<script>", boot)
        self.assertNotIn("<script src", boot)
        self.assertIn("{% if customer %}", boot)
        self.assertIn("{% endif %}", boot)

    def test_it_acts_on_the_landing_page_and_no_other(self) -> None:
        boot = read(self.BOOT)

        # The body is not parsed yet, so the markup check that keeps a half
        # authenticated shopper on the one-time-code step cannot run here. It
        # judges by path, and every step of the sign-in is excluded.
        self.assertIn("if (!/^\\/account(\\/|$)/i.test(path)) return;", boot)
        self.assertIn(
            "if (/^\\/account\\/(login|register|recover|auth|activate|reset)/i.test(path)) return;",
            boot,
        )

    def test_it_agrees_with_the_module_it_stands_in_for(self) -> None:
        boot = read(self.BOOT)
        module = code_only(read(f"assets/{MODULE}"))

        # Two copies of one rule, pinned together: the same entry, the same
        # half-hour window, and the same refusals.
        self.assertIn("'cc:pending-login-redirect'", boot)
        self.assertIn("const KEY = 'cc:pending-login-redirect';", module)
        self.assertIn("> 1800000", boot)
        self.assertIn("const MAX_AGE_MS = 30 * 60 * 1000;", module)
        self.assertEqual(30 * 60 * 1000, 1800000)
        self.assertIn("if (target.charAt(0) !== '/') return;", boot)
        self.assertIn("if (/^\\/[\\/\\\\]/.test(target)) return;", boot)
        self.assertIn("if (/^\\/account(\\/|$)/i.test(target)) return;", boot)
        # Consumed as it is used, exactly as the module consumes it.
        self.assertIn("window.sessionStorage.removeItem('cc:pending-login-redirect');", boot)
        self.assertIn("window.location.replace(target);", boot)


class LoginRedirectMatchesWhatThePurchaseSurfacesSendTests(unittest.TestCase):
    def test_the_parameter_name_is_the_one_the_purchase_surfaces_use(self) -> None:
        module = code_only(read(f"assets/{MODULE}"))
        limits = read("assets/customer-order-limits.js")
        cart = read("assets/cart.js")

        self.assertIn("/account/login?redirect_uri=${encodeURIComponent(target)}", limits)
        self.assertIn("/account/login?redirect_uri=", cart)
        self.assertIn("get('redirect_uri')", module)

    def test_the_login_page_is_recognised_as_a_step_of_signing_in(self) -> None:
        module = code_only(read(f"assets/{MODULE}"))

        # The theme's own login and register templates, plus the platform-rendered
        # steps they hand off to, which is where the OTP is confirmed.
        auth_path = module.split("AUTH_PATH")[1].splitlines()[0]
        for step in ("login", "register", "recover", "auth", "activate", "reset"):
            with self.subTest(step=step):
                self.assertIn(step, auth_path)

        # Those steps are real pages: the theme renders these templates, and the
        # ones it does not render belong to the platform's own flow.
        for template in ("login", "register", "reset_password", "activate_account"):
            with self.subTest(template=template):
                self.assertTrue(
                    (THEME_ROOT / "templates" / "customers" / f"{template}.liquid").is_file()
                )


if __name__ == "__main__":
    unittest.main()
