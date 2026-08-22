# Customer signup and profile completion

This store uses **mobile number signup only**. A customer verifies their mobile number with EasyStore's OTP flow before the theme treats signup as finished.

**Guest checkout is disabled.** A shopper must have a customer account before continuing to checkout.

## Required signup flow

When an unauthenticated shopper starts from a product or another storefront page and enters the sign-in/signup flow:

1. The theme remembers the product or prior storefront page in `sessionStorage`.
2. The customer enters their mobile number and completes EasyStore OTP verification.
3. If the authenticated customer profile is incomplete, the theme routes them to `/account/details` before the originally requested storefront page can paint.
4. The completion form requires first name, last name, gender, date of birth, and **Set password**.
5. The Click ID attribution field remains hidden and automatic; it never replaces or satisfies a human profile field.
6. The customer cannot use in-store navigation to leave the completion form while required fields are missing. Browser Back/Reload/leave receives the browser's native leave-page protection, and another in-store page immediately gates the customer back to `/account/details` while the profile is incomplete.
7. After EasyStore accepts the completed profile and password, the pending redirect resumes to the remembered product or prior storefront page.

## Password rule

Signup asks for **one password field only: Set password**.

The account-details template contains EasyStore's normal password-change controls:

- `details[password1]` — current password
- `details[password2]` — new password

For a new mobile/OTP signup there is no old password to enter. Mandatory profile completion therefore surfaces only `details[password2]`, labels it **Set password**, and marks it required. There is **no current-password field** in the signup completion UI.

The existing current-password control remains untouched inside the normal hidden Change password panel for customers changing a password later from their account settings.

## Completion and return-target invariants

The signup/profile gate must preserve these behaviors:

- an incomplete authenticated customer cannot bypass `/account/details` by following the stored Buy Now redirect;
- the pending product/prior-page target is not consumed until profile completion succeeds;
- a machine-only Click ID cannot make a human profile complete;
- password is required before the completion form can submit;
- signup never asks for a current password;
- once EasyStore accepts the completed profile, the customer returns to the product or prior storefront page they were trying to continue from.

The implementation lives in `theme/snippets/login-redirect-boot.liquid`, with regression coverage in `tests/test_profile_completion_gate.py` and the login-redirect browser suite.
