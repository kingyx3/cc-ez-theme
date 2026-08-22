# Customer signup and profile completion

This store uses **mobile number signup only**. A customer verifies their mobile number with EasyStore's OTP flow before the theme treats signup as finished.

**Guest checkout is disabled.** A shopper must have a customer account before continuing to checkout.

## Required signup flow

When an unauthenticated shopper starts from a product or another storefront page and enters the sign-in/signup flow:

1. The theme remembers the product or prior storefront page in `sessionStorage`.
2. The customer enters their mobile number and completes EasyStore OTP verification.
3. If the authenticated customer profile is incomplete, the theme routes them to `/account/details` before the originally requested storefront page can paint.
4. The completion form requires first name, last name, gender and date of birth. On the **first successful completion only**, it also requires **Set password**.
5. The Click ID attribution field remains hidden and automatic; it never replaces or satisfies a human profile field.
6. The customer cannot use in-store navigation to leave the completion form while required fields are missing. Browser Back/Reload/leave receives the browser's native leave-page protection, and another in-store page immediately gates the customer back to `/account/details` while the profile is incomplete.
7. After EasyStore accepts the completed profile and first-time password, the pending redirect resumes to the remembered product or prior storefront page.

## Password rule

Signup asks for **one password field only: Set password**, and it is a **first-time requirement**.

The account-details template contains EasyStore's normal password-change controls:

- `details[password1]` — current password
- `details[password2]` — new password

For a new mobile/OTP signup there is no old password to enter. Mandatory profile completion therefore surfaces only `details[password2]`, labels it **Set password**, and marks it required. There is **no current-password field** in the signup completion UI.

After the first successful profile/password save, the completion gate records that the password has already been initialized for that customer and does **not ask for it again** on later renders of the mandatory profile form. The normal password-change controls remain untouched inside the hidden Change password panel for customers who deliberately change their password later from account settings.

A password is not considered initialized merely because the shopper clicked Save. The form first records a pending password submission; EasyStore's existing `update_success` value on the following `/account/details` response is the server acknowledgement that promotes that state to "password set". If EasyStore rejects the POST, there is no `update_success`, so **Set password** remains required. If EasyStore accepts the password/profile update but another completion requirement still keeps the form open, the password is nevertheless treated as already set and the form does not ask for it again.

EasyStore's documented Liquid `customer` object exposes profile fields and `customer.is_optional_fields_filled`, but no password-exists flag. The theme therefore stores the acknowledged first-time password marker in the browser, namespaced by `customer.id`, using `localStorage` with a `sessionStorage` fallback. Clearing browser storage can make the form ask to set a password again; it cannot remove or change the actual EasyStore account password.

## Completion and return-target invariants

The signup/profile gate must preserve these behaviors:

- an incomplete authenticated customer cannot bypass `/account/details` by following the stored Buy Now redirect;
- the pending product/prior-page target is not consumed until profile completion succeeds;
- a machine-only Click ID cannot make a human profile complete;
- Set password is required for the first successful completion, then is not required again on the mandatory form for that customer in the same browser;
- signup never asks for a current password;
- once EasyStore accepts the completed profile, the customer returns to the product or prior storefront page they were trying to continue from.

The implementation lives in `theme/snippets/login-redirect-boot.liquid`, with regression coverage in `tests/test_profile_completion_gate.py` and the login-redirect browser suite.
