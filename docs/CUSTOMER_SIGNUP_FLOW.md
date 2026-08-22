# Customer signup and profile completion

This store uses **mobile number signup only**. A customer verifies their mobile number with EasyStore's OTP flow before the theme treats signup as finished.

**Guest checkout is disabled.** A shopper must have a customer account before continuing to checkout.

## Required signup flow

When an unauthenticated shopper starts from a product or another storefront page and enters the sign-in/signup flow:

1. The theme remembers the product or prior storefront page in `sessionStorage`.
2. Visiting `/account/register` starts a tab-scoped signup marker for the password step.
3. The customer enters their mobile number and completes EasyStore OTP verification. The signup marker survives those platform-owned OTP pages.
4. If the authenticated customer profile is incomplete, the theme routes them to `/account/details` before the originally requested storefront page can paint.
5. The completion form always requires first name, last name, gender and date of birth. **Set password is shown and required only when the customer arrived through the active signup trip.**
6. The Click ID attribution field remains hidden and automatic; it never replaces or satisfies a human profile field.
7. The customer cannot use in-store navigation to leave the completion form while required fields are missing. Browser Back/Reload/leave receives the browser's native leave-page protection, and another in-store page immediately gates the customer back to `/account/details` while the profile is incomplete.
8. After EasyStore accepts the details/password save, its existing `update_success` acknowledgement clears the signup marker. The pending redirect then resumes to the remembered product or prior storefront page once profile completion is satisfied.

## Password rule

**Set password is signup-only.** It is not a permanent field in mandatory profile completion.

The account-details template contains EasyStore's normal password-change controls:

- `details[password1]` — current password
- `details[password2]` — new password

For a new mobile/OTP signup there is no old password to enter. While the tab is in the signup trip, mandatory completion surfaces only `details[password2]`, labels it **Set password**, and marks it required. There is **no current-password field** in the signup completion UI.

The signup trip is identified with `cc:signup-password-setup` in `sessionStorage`. The marker is set on `/account/register`, kept through OTP, and cleared when EasyStore confirms the account-details save with `update_success`. Visiting the normal `/account/login` route clears an abandoned signup marker so an existing customer does not inherit the signup prompt.

Outside an active signup trip, `/account/details` does **not** move, relabel, or require `details[password2]`. Normal account-details visits keep both password controls in EasyStore's hidden **Change password** panel. Customers who deliberately want to change a password later use that normal account feature.

This means the theme no longer needs to guess whether a customer "has a password" from profile completeness or keep a long-lived browser-side password-state marker. The only browser state is the short-lived, tab-scoped fact that the shopper is currently finishing signup.

## Completion and return-target invariants

The signup/profile gate must preserve these behaviors:

- an incomplete authenticated customer cannot bypass `/account/details` by following the stored Buy Now redirect;
- the pending product/prior-page target is not consumed until profile completion succeeds;
- a machine-only Click ID cannot make a human profile complete;
- **Set password appears only during signup** and stays hidden for later mandatory-profile or normal account-details visits;
- signup never asks for a current password;
- leaving signup for normal login clears the signup-only password marker;
- once EasyStore accepts the completed profile, the customer returns to the product or prior storefront page they were trying to continue from.

The implementation lives in `theme/snippets/login-redirect-boot.liquid`, with regression coverage in `tests/test_profile_completion_gate.py` and the login-redirect browser suite.
