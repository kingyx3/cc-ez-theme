# Customer signup and profile completion

This store uses **mobile number signup only**. A new customer verifies their mobile number with EasyStore's OTP flow before account setup is finished.

**Guest checkout is disabled.** A shopper must have a customer account before continuing to checkout.

## Required signup flow

When an unauthenticated shopper starts from a product or another storefront page and enters the sign-in/signup flow:

1. The theme remembers the product or prior storefront page in `sessionStorage`.
2. The customer enters their mobile number and completes EasyStore OTP verification.
3. EasyStore's native first-account completion is allowed to render before the theme sends the customer anywhere else. The real first password is created through EasyStore's registration contract as `customer[password]`.
4. If EasyStore still reports first name, last name, gender, or date of birth as blank after that native account-creation step, the theme routes the customer to `/account/details`.
5. The `/account/details` completion form requires those four human profile fields. It does **not** create or emulate the first password.
6. The Click ID attribution field remains hidden and automatic; it never replaces or satisfies a human profile field.
7. The customer cannot use in-store navigation to leave `/account/details` while one of the four required human fields is still missing. Browser Back/Reload/leave receives the browser's native leave-page protection, and another in-store page immediately gates the customer back to `/account/details` while those required fields remain incomplete.
8. Once the required human profile fields are present, the profile gate releases and the pending redirect resumes to the remembered product or prior storefront page.

## Profile-completion rule

The mandatory theme gate is based only on the four human fields this store requires:

- first name;
- last name;
- gender;
- date of birth.

EasyStore also exposes `customer.is_optional_fields_filled`. That value is **not** used as a hard completion requirement. It can remain false because of unrelated optional or custom fields even after this store's required profile fields have been saved. Using it as a gate can create an indefinite `/account/details` loop.

Therefore, when all four required human fields are present, `customer.is_optional_fields_filled == false` does not keep the gate locked. Click ID still cannot make a profile complete because the gate checks these four customer properties explicitly and does not use customer attributes.

## Password rule

Initial password creation and later password changes are different EasyStore operations and must stay separate.

The registration/account-creation contract uses:

- `customer[password]` — the customer's first login password.

The account-details template contains EasyStore's normal **Change password** controls:

- `details[password1]` — current password;
- `details[password2]` — new password.

The theme must never promote `details[password2]` and relabel it as a first-time **Set password** field. Live testing showed that doing so can produce a successful-looking profile save without creating a password that `/account/login` accepts.

Because the profile gate runs from the document head, EasyStore can already expose the shopper as `customer` immediately after OTP while its native first-account completion page has not rendered yet. For an incomplete customer on a non-details account page, the theme therefore waits until `DOMContentLoaded` and checks for the native `customer[password]` account-creation field before deciding to redirect to `/account/details`. If the native password step exists, the theme leaves the page alone.

There is no signup password state stored in `sessionStorage`, and profile completeness is not treated as proof that a password exists.

## Returning customer login

The intended returning-customer flow is **password-first** after the account has been created: mobile/email identity plus the password created during signup. OTP remains appropriate for initial mobile verification and password recovery.

The theme-rendered `/account/login` form is already password-first: it asks for `customer[email_or_phone]` and `customer[password]`, submits the normal Login form, and only then renders EasyStore's optional `login/button` methods below it.

EasyStore can also render parts of the account flow itself. Theme code must not write values into, dispatch events into, or auto-click controls in those platform-owned verification widgets. The theme's responsibility is to avoid bypassing EasyStore's native first-password creation step; once the account genuinely has a password, the platform can use its normal returning-customer password flow.

## Return to the page before signup

The page the shopper was on before entering login/signup is stored under `cc:pending-login-redirect` in `sessionStorage`. A Buy Now flow preserves its product URL; a signup/login opened from another storefront page preserves that prior same-origin storefront page instead.

The profile gate never consumes this value while EasyStore is still asking for an authentication/account-creation step or while required human profile fields are missing. As soon as account setup is finished and the four required human profile fields are complete, the account landing code consumes the saved target once and navigates there with `window.location.replace(target)`.

Unsafe, stale, off-site, or `/account` targets are not followed. The saved target expires after 30 minutes.

## Completion and return-target invariants

The signup/profile gate must preserve these behaviors:

- OTP verification is left entirely to EasyStore;
- EasyStore's native `customer[password]` first-password step is never pre-empted by the theme's profile redirect;
- `details[password1]` and `details[password2]` remain later Change password controls, not signup password creation fields;
- an incomplete authenticated customer cannot bypass required human profile completion by following the stored Buy Now redirect;
- the pending product or prior storefront page target is not consumed until account setup and the four required human profile fields are complete;
- `customer.is_optional_fields_filled` does not keep the gate locked after those required fields are present;
- a machine-only Click ID cannot make a human profile complete;
- the theme-rendered returning-customer login remains password-first;
- once EasyStore accepts account setup and the required profile, the customer returns to the product or prior storefront page they were trying to continue from.

The implementation lives in `theme/snippets/login-redirect-boot.liquid`, with regression coverage in `tests/test_profile_completion_gate.py`, `tests/test_first_password_profile_completion.py`, and the login-redirect browser suite.
