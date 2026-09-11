/*
 * Hides the platform's "continue with email instead" link and loads the
 * narrowly-scoped same-event Android OTP autofill helper.
 *
 * The copy helper itself remains visibility-only: it never touches an OTP
 * input, sets a value, dispatches an event, submits, clicks, or intercepts a
 * request. The separate autofill helper is responsible only for splitting one
 * trusted six-digit Android input across EasyStore's six plain-DOM cells while
 * allowing that same original event to continue.
 */
(() => {
  // "Continue with email instead", "Sign up using your email address instead".
  const EMAIL_SIGNUP = /\be-?mail\b[^.!?]{0,32}\binstead\b/i;
  // Longer than this is a paragraph, not the link.
  const LINK_LENGTH = 80;

  const loadOtpAutofill = () => {
    const current = document.currentScript
      || document.querySelector('script[src*="account-otp-copy.js"]');
    const source = current && String(current.src || '');
    if (!/account-otp-copy\.js(?:[?#]|$)/.test(source)) return;
    if (document.querySelector('script[data-cc-otp-autofill="same-event"]')) return;

    const script = document.createElement('script');
    script.src = source.replace(
      /account-otp-copy\.js(?=([?#]|$))/,
      'otp-same-event-autofill.js'
    );
    script.defer = true;
    script.dataset.ccOtpAutofill = 'same-event';
    document.head.appendChild(script);
  };

  loadOtpAutofill();

  const hideEmailSignup = () => {
    document.querySelectorAll('a, button').forEach((control) => {
      const text = (control.textContent || '').replace(/\s+/g, ' ').trim();
      if (control.hidden || text.length > LINK_LENGTH) return;
      if (!EMAIL_SIGNUP.test(text)) return;
      control.hidden = true;
      control.style.display = 'none';
    });
  };

  // Wording the platform shows on a step that is waiting on a code.
  const OTP_STEP = /verification\s+code|one-time\s+password|\botp\b|verify\s+your\s+(?:mobile|phone)|(?:code\s+(?:we\s+)?(?:just\s+)?sent|sent\s+(?:you\s+)?(?:an?|the)\s+code)|resend\s+(?:the\s+)?code/i;

  const pageText = () => (document.body && document.body.textContent) || '';

  // What the page shows, never where the URL says it is: a page-path heuristic
  // is the trap that once turned the header search box into an OTP field. A
  // form alone is not the signal either - the OTP step renders none, which is
  // what left that step watched by nothing. Any of the three is an account
  // step: the platform's own form, the wording it shows while a code is
  // outstanding, or the link itself.
  const hasAccountStep = () => document.querySelector('form[action*="/account"]') !== null
    || OTP_STEP.test(pageText())
    || EMAIL_SIGNUP.test(pageText());

  const start = () => {
    // Detect the account step before walking every link/button. Ordinary
    // storefront pages only pay for the existing marker/text probe and skip the
    // broad control scan completely. Repeat the original guard after hiding so
    // observation behavior stays tied to the same post-rewrite page state.
    if (!hasAccountStep()) return;
    hideEmailSignup();
    if (!hasAccountStep()) return;

    // The platform renders its next step after a submit, so the page is watched
    // - but only on a page that has an account step at all.
    let queued = false;
    new MutationObserver(() => {
      if (queued) return;
      queued = true;
      window.requestAnimationFrame(() => {
        queued = false;
        hideEmailSignup();
      });
    }).observe(document.documentElement, { childList: true, subtree: true });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
