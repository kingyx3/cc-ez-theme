/*
 * Replaces one sentence: the promise of a password reset email.
 *
 * This store recovers an account by confirming a one-time password sent to the
 * shopper's mobile number, and the recovery form asks for that number. Where
 * this theme renders the copy, the template says so directly. Where EasyStore
 * renders the page - /account/auth is the platform's own flow - the sentence
 * comes from the platform's translation, and no theme deploy can change it, so
 * a shopper is told to wait for an email the store never sends.
 *
 * Text only, deliberately. It reads and writes textContent on leaf elements: it
 * never touches an input, never sets a value, and never dispatches an event.
 * That is the line whose crossing broke signup with "Customer already exists
 * (phone)" - theme scripts writing into the platform's verification cells - and
 * nothing here goes near it.
 *
 * Setting `customer.recover_password.subtext` in the store's translations makes
 * this a no-op, and it can be deleted at that point.
 */
(() => {
  const EMAIL_PROMISE = /send\s+you\s+an\s+e-?mail\s+to\s+reset\s+your\s+password/i;
  const OTP_COPY = 'Confirm your mobile OTP to proceed';
  // Markers of a page that has a recovery step, so the rest of the storefront
  // neither scans nor observes anything.
  const RECOVERY_MARKERS = [
    'form[action="/account/recover"]',
    '#recover',
    '[href="#recover"]',
    '[href*="/account/recover"]',
  ].join(',');

  // A leaf element holds its own text, so replacing it cannot discard markup.
  const isLeaf = (element) => element.children.length === 0;

  const rewriteWithin = (root) => {
    if (!root || !root.querySelectorAll) return 0;
    let rewritten = 0;
    const candidates = Array.from(root.querySelectorAll('p, span, small, div, li'));
    if (root.matches && root.matches('p, span, small, div, li')) candidates.unshift(root);
    candidates.forEach((element) => {
      if (!isLeaf(element)) return;
      if (!EMAIL_PROMISE.test(element.textContent || '')) return;
      element.textContent = OTP_COPY;
      rewritten += 1;
    });
    return rewritten;
  };

  const hasRecoveryStep = () => Boolean(document.querySelector(RECOVERY_MARKERS))
    || EMAIL_PROMISE.test(document.body ? document.body.textContent || '' : '');

  const start = () => {
    rewriteWithin(document.body);
    // The platform flow can render its recovery step after a click, so the page
    // is watched - but only on a page that has such a step at all.
    if (!hasRecoveryStep()) return;

    // One rescan per frame at most, and a timer where frames are unavailable.
    const soon = typeof window.requestAnimationFrame === 'function'
      ? (callback) => window.requestAnimationFrame(callback)
      : (callback) => window.setTimeout(callback, 0);
    let queued = false;
    const observer = new MutationObserver(() => {
      if (queued) return;
      queued = true;
      soon(() => {
        queued = false;
        rewriteWithin(document.body);
      });
    });
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
