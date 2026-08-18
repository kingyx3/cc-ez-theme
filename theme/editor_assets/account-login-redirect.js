/*
 * Finishes the sign-in trip a purchase surface started.
 *
 * A guest who tries to buy a limited product is sent to
 * `/account/login?redirect_uri=<the page they were on>`. EasyStore signs the
 * customer in through its own flow - a password post, then in this store an OTP
 * step on the platform's `/account/auth` page - and lands them on the account
 * area afterwards. The platform picks that landing page itself and ignores the
 * parameter, which is why a shopper who clicked Buy Now arrived at their order
 * history instead of the product. Nothing in a theme can change where EasyStore
 * lands them, so the theme remembers the target and completes the trip on the
 * first page that proves the shopper is signed in.
 *
 * The target is remembered in `sessionStorage`, which is per tab and survives
 * the full page loads the platform's login flow performs. It is consumed on the
 * first signed-in page load whether or not it is used, so a target can never
 * divert a later, unrelated sign-in - and it expires regardless, so a tab left
 * open on the login page overnight does not jump somewhere unexpected.
 *
 * The platform's own login POST is deliberately left alone: no field is added
 * to it and no value is written into it. Theme scripts writing into EasyStore's
 * account forms is what once broke signup outright, and a shopper landing on
 * the right page one paint later is not worth that risk.
 */
(() => {
  'use strict';

  const KEY = 'cc:pending-login-redirect';
  // Long enough for an OTP that arrives slowly, short enough that a target can
  // never outlive the purchase the shopper was making.
  const MAX_AGE_MS = 30 * 60 * 1000;

  // The same markers `customer-order-limits.js` treats as proof of sign-in:
  // the layout class rendered by `{% if customer %}`, the header's account
  // marker, and any sign-out link. Missing markup proves nothing either way,
  // and is read here as "not signed in yet", which only defers the redirect.
  const SIGNED_IN_MARKUP = 'body.customer-logged-in, [data-customer-authenticated="true"], a[href^="/account/logout"]';

  // Pages where a shopper is in the middle of authenticating: the theme's own
  // login and register templates, and the platform-rendered steps they hand off
  // to. A `redirect_uri` is only ever recorded from one of these.
  const AUTH_PATH = /^\/account\/(login|register|recover|auth|activate|reset)/i;

  const path = () => String(window.location.pathname || '');

  const here = () => `${path()}${String(window.location.search || '')}`;

  const signedIn = () => Boolean(document.querySelector(SIGNED_IN_MARKUP));

  // Only a same-origin path this store serves is ever navigated to. A protocol,
  // a protocol-relative `//host`, a backslash host, or anything carrying control
  // characters is discarded rather than repaired, and so is an `/account` target,
  // which would send the shopper back into the flow they just finished.
  const safeTarget = (value) => {
    const target = String(value || '').trim();
    if (!target || target.charAt(0) !== '/') return '';
    if (/^\/[/\\]/.test(target)) return '';
    if (/[\u0000-\u001f\u007f]/.test(target)) return '';
    if (/^\/account(\/|$)/i.test(target)) return '';
    return target;
  };

  const requestedTarget = () => {
    try {
      return safeTarget(new URLSearchParams(window.location.search).get('redirect_uri'));
    } catch (_error) {
      return '';
    }
  };

  // Storage is unavailable in some privacy modes, so every access falls back to
  // "nothing remembered" and the redirect is simply not completed.
  const store = (target) => {
    try {
      window.sessionStorage.setItem(KEY, JSON.stringify({
        target,
        storedAt: new Date().getTime(),
      }));
    } catch (_error) {
      /* no pending target is recorded */
    }
  };

  const take = () => {
    let raw = null;
    try {
      raw = window.sessionStorage.getItem(KEY);
      window.sessionStorage.removeItem(KEY);
    } catch (_error) {
      return '';
    }
    if (!raw) return '';
    try {
      const pending = JSON.parse(raw);
      const storedAt = Number(pending && pending.storedAt);
      if (!Number.isFinite(storedAt)) return '';
      if (new Date().getTime() - storedAt > MAX_AGE_MS) return '';
      return safeTarget(pending && pending.target);
    } catch (_error) {
      return '';
    }
  };

  const start = () => {
    const requested = requestedTarget();
    const authenticating = AUTH_PATH.test(path());

    if (!signedIn()) {
      // Still signing in. A login page that carries a target records it; every
      // other page, including the OTP step, leaves the recorded one alone.
      if (authenticating && requested) store(requested);
      return;
    }

    // Signed in, so the trip is over: the recorded target is consumed here even
    // when it is not used, and the parameter still counts on an account page in
    // case the platform forwarded it or storage was unavailable.
    const target = take() || (authenticating ? requested : '');
    if (!target || target === here()) return;

    // `replace` so Back returns to the product page's history entry rather than
    // bouncing the shopper through the account page again.
    window.location.replace(target);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
