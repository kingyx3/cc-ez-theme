# Customer signup and profile completion

This store uses **mobile number signup only**. A customer verifies their mobile number with EasyStore's OTP flow before the theme treats signup as finished.

**Guest checkout is disabled.** A shopper must have a customer account before continuing to checkout.

## Required signup flow

When an unauthenticated shopper starts from a product or another storefront page and enters the sign-in/signup flow:

1. The theme remembers the product or prior storefront page in `sessionStorage`.
2. Visiting `/account/register` starts a tab-scoped signup marker for the password step.
3. The customer enters their mobile number and completes EasyStore OTP verification. The signup marker survives those platform-owned OTP pages, including an `/account/login` URL if EasyStore uses it as an intermediate authentication step.
4. If any required human profile field is still blank, the theme routes the authenticated customer to `/account/details` before the originally requested storefront page can paint.
5. The completion form always requires first name, last name, gender and date of birth. **Set password is shown and required only when the customer arrived through the active signup trip.**
6. The Click ID attribution field remains hidden and automatic; it never replaces or satisfies a human profile field.
7. The customer cannot use in-store navigation to leave the completion form while one of the four required human fields is still missing. Browser Back/Reload/leave receives the browser's native leave-page protection, and another in-store page immediately gates the customer back to `/account/details` while those required fields remain incomplete.
8. After EasyStore accepts the details/password save, its existing `update_success` acknowledgement clears the signup password marker. Once first name, last name, gender and date of birth are all present, the profile gate releases and the pending redirect resumes to the remembered product or prior storefront page.

## Profile-completion rule

The mandatory gate is based only on the four human fields this store requires:

- first name;
- last name;
- gender;
- date of birth.

EasyStore also exposes `customer.is_optional_fields_filled`. That value is **not** used as a hard completion requirement. It can remain false because of unrelated optional or custom fields even after this store's required profile fields have been saved. Using it as a gate can create an indefinite `/account/details` loop.

Therefore, when all four required human fields are present, `customer.is_optional_fields_filled == false` does not keep the gate locked. Click ID still cannot make a profile complete because the gate checks these four customer properties explicitly and does not use customer attributes.

## Password rule

**Set password is signup-only.** It is not a permanent field in mandatory profile completion.

The account-details template contains EasyStore's normal password-change controls:

- `details[password1]` — current password
- `details[password2]` — new password

For a new mobile/OTP signup there is no old password to enter. While the tab is in the signup trip, mandatory completion surfaces only `details[password2]`, labels it **Set password**, and marks it required. There is **no current-password field** in the signup completion UI.

The signup trip is identified with `cc:signup-password-setup` in `sessionStorage`. The marker is set on `/account/register`, kept through OTP and any platform-owned authentication route, and cleared when EasyStore confirms the account-details save with `update_success`.

An `/account/login` URL by itself does **not** clear the marker because EasyStore can use that route while a registration is still in progress. The marker is cleared early only when the shopper explicitly follows the registration page's sign-in link or submits the existing-customer password form. That prevents a real returning customer from inheriting a stale signup prompt without dropping the password requirement from a new signup.

Outside an active signup trip, `/account/details` does **not** move, relabel, or require `details[password2]`. Normal account-details visits keep both password controls in EasyStore's hidden **Change password** panel. Customers who deliberately want to change a password later use that normal account feature.

This means the theme does not guess whether a customer "has a password" from profile completeness or keep a long-lived browser-side password-state marker. The only browser state is the short-lived, tab-scoped fact that the shopper is currently finishing signup.

## Returning customer login

The theme-rendered `/account/login` form is **password-first**: it asks for the customer's email/mobile identity and `customer[password]`, then renders EasyStore's optional `login/button` methods below the normal password submit. OTP remains appropriate for registration verification and password recovery; the theme does not auto-select OTP as the returning-customer login method.

EasyStore can also render parts of the account flow itself. Theme code must not write values into, dispatch events into, or auto-click controls in those platform-owned verification widgets. If a live EasyStore-owned login screen chooses OTP despite the password-first theme template, that authentication-mode choice must be corrected in EasyStore's customer/login settings or platform behavior rather than by scripting the OTP widget from the theme.

## Return to the page before signup

The page the shopper was on before entering login/signup is stored under `cc:pending-login-redirect` in `sessionStorage`. A Buy Now flow preserves its product URL; a signup/login opened from another storefront page preserves that prior same-origin storefront page instead.

The profile gate never consumes this value while required fields are missing. As soon as the four required human profile fields are complete, the account landing code consumes the saved target once and navigates there with `window.location.replace(target)`. This means completing `/account/details` returns the shopper to the product or storefront page they were on before signup rather than leaving them in the account area.

Unsafe, stale, off-site, or `/account` targets are not followed. The saved target expires after 30 minutes.

## Completion and return-target invariants

The signup/profile gate must preserve these behaviors:

- an incomplete authenticated customer cannot bypass `/account/details` by following the stored Buy Now redirect;
- the pending product/prior-page target is not consumed until the four required human profile fields are complete;
- `customer.is_optional_fields_filled` does not keep the gate locked after those required fields are present;
- a machine-only Click ID cannot make a human profile complete;
- **Set password appears only during signup** and stays hidden for later mandatory-profile or normal account-details visits;
- signup never asks for a current password;
- platform auth route changes do not erase the signup-only password marker;
- deliberately switching from registration to password sign-in clears the signup-only password marker;
- the theme-rendered returning-customer login keeps password as its primary form;
- once EasyStore accepts the completed required profile, the customer returns to the product or prior storefront page they were trying to continue from.

The implementation lives in `theme/snippets/login-redirect-boot.liquid`, with regression coverage in `tests/test_profile_completion_gate.py` and the login-redirect browser suite.
