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
 * A shopper who simply opens the login page themselves carries no target at
 * all, and the platform's landing page is the same order history. The page they
 * came from is where they were, so that is remembered instead - and where even
 * that is unknown, the shop's own front page is, which is somewhere to shop
 * from rather than a list of past orders. Neither displaces a target already
 * recorded, so a purchase on its way to sign-in is never diverted by the page
 * the shopper happened to arrive from.
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
 *
 * Being signed in is not the same as having finished signing in. EasyStore
 * treats a shopper who has passed the mobile-number step as a customer while
 * the one-time code is still outstanding, so the layout renders
 * `body.customer-logged-in` and the header renders its signed-in marker on the
 * OTP step itself. The first deployed version read those markers there and
 * threw the shopper to the product page after they had typed nothing but their
 * mobile number, unauthenticated and with the code unconfirmed. A page that is
 * still asking for a step is therefore never a page to leave, whatever the
 * markers say, and that is decided from the markup as well as the path: the OTP
 * step renders no form of its own, and its URL is the platform's to change.
 */
(() => {
  'use strict';

  const KEY = 'cc:pending-login-redirect';
  // Where a sign-in with nothing else to say ends. It is also the least
  // specific target there is, so a page the shopper actually came from may
  // still replace it while they are signing in.
  const HOME = '/';
  // Long enough for an OTP that arrives slowly, short enough that a target can
  // never outlive the purchase the shopper was making.
  const MAX_AGE_MS = 30 * 60 * 1000;

  // The same markers `customer-order-limits.js` treats as proof of sign-in:
  // the layout class rendered by `{% if customer %}`, the header's account
  // marker, and any sign-out link. Missing markup proves nothing either way,
  // and is read here as "not signed in yet", which only defers the redirect.
  const SIGNED_IN_MARKUP = 'body.customer-logged-in, [data-customer-authenticated="true"], a[href^="/account/logout"]';
  // The header's guest marker, and the only proof of being signed out this
  // theme renders. Recording where a shopper came from is for a shopper who is
  // about to sign in; a customer who opens the login page for some other reason
  // must not be bounced back out of it.
  const SIGNED_OUT_MARKUP = '[data-customer-authenticated="false"]';

  // Pages where a shopper is in the middle of authenticating: the theme's own
  // login and register templates, and the platform-rendered steps they hand off
  // to - `/account/auth` and `/account/auth/send` carry the one-time code.
  const AUTH_PATH = /^\/account\/(login|register|recover|auth|activate|reset)/i;

  // The same step read from the markup, because the path alone cannot be
  // trusted to name it: EasyStore owns those URLs and has moved this step
  // before. `#otp-form .otp-input` is the live widget's own markup, captured by
  // scripts/otp-widget-capture.console.js; the rest are the fields the theme's
  // own login and register templates render.
  const AUTHENTICATING_MARKUP = [
    '#otp-form',
    '.otp-input',
    'input[name="customer[password]"]',
    'input[name="customer[email_or_phone]"]',
    'form[action^="/account/login"]',
    'form[action^="/account/auth"]',
  ].join(', ');

  const path = () => String(window.location.pathname || '');

  const here = () => `${path()}${String(window.location.search || '')}`;

  const signedIn = () => Boolean(document.querySelector(SIGNED_IN_MARKUP));

  // Read before the sign-in markers and allowed to overrule them: a half
  // authenticated shopper carries every marker a finished one does.
  const stillAuthenticating = () => (
    AUTH_PATH.test(path()) || Boolean(document.querySelector(AUTHENTICATING_MARKUP))
  );

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

  // The recorded target, left where it is. An entry that is stale, damaged, or
  // no longer safe reads as nothing recorded, so it neither travels nor blocks
  // a fresher one from being written over it.
  const readPending = () => {
    let raw = null;
    try {
      raw = window.sessionStorage.getItem(KEY);
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

  const take = () => {
    const target = readPending();
    // Cleared whether or not it was usable, so a target can never divert a
    // second sign-in.
    try {
      window.sessionStorage.removeItem(KEY);
    } catch (_error) {
      /* nothing was recorded to clear */
    }
    return target;
  };

  // Where the shopper was before they came to sign in. `document.referrer` is
  // the previous page of this navigation, so it is read only on the page they
  // arrived at - by the time the platform's own steps have posted, it names one
  // of those steps and is refused like any other account path.
  const referrerTarget = () => {
    const referrer = String(document.referrer || '');
    if (!referrer) return '';
    let previous = null;
    try {
      previous = new URL(referrer, window.location.href);
    } catch (_error) {
      return '';
    }
    if (previous.origin !== window.location.origin) return '';
    const target = safeTarget(`${previous.pathname}${previous.search}`);
    return target === here() ? '' : target;
  };

  const start = () => {
    const requested = requestedTarget();

    // A step is still outstanding, so this is not a page to leave and not a
    // moment to trust the signed-in markers. A page carrying a target records
    // it; every other step, the OTP included, leaves the recorded one alone.
    if (stillAuthenticating()) {
      if (requested) {
        store(requested);
        return;
      }

      // Nothing sent this shopper here, so where they came from is where they
      // were, and the front page if even that is unknown. Neither displaces a
      // target a purchase surface recorded, and neither is written unless the
      // page proves the shopper is signed out - a customer who opens the login
      // page for some other reason is not bounced back out of it.
      const pending = readPending();
      if ((pending && pending !== HOME) || !document.querySelector(SIGNED_OUT_MARKUP)) return;
      store(referrerTarget() || HOME);
      return;
    }

    if (!signedIn()) return;

    // Signed in on a page that is asking for nothing further, so the trip is
    // over: the recorded target is consumed here even when it is not used.
    const target = take();
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
