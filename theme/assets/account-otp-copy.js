/*
 * Hides the platform's "continue with email instead" link.
 *
 * This store signs customers up by mobile number only. Every email path the
 * theme renders is already gone, but /account/auth is EasyStore's own flow, so
 * that link comes from the platform's translation and no theme deploy can take
 * it out of the template.
 *
 * Text in, visibility out. It reads textContent and hides the control holding
 * it: it never touches an input, never sets a value, never dispatches an event,
 * and never removes a node the platform's widget may still hold. That is the
 * line whose crossing broke signup with "Customer already exists (phone)".
 */
(() => {
  // "Continue with email instead", "Sign up using your email address instead".
  const EMAIL_SIGNUP = /\be-?mail\b[^.!?]{0,32}\binstead\b/i;
  // Longer than this is a paragraph, not the link.
  const LINK_LENGTH = 80;

  const hideEmailSignup = () => {
    document.querySelectorAll('a, button').forEach((control) => {
      const text = (control.textContent || '').replace(/\s+/g, ' ').trim();
      if (control.hidden || text.length > LINK_LENGTH) return;
      if (!EMAIL_SIGNUP.test(text)) return;
      control.hidden = true;
      control.style.display = 'none';
    });
  };

  // /account, /account/auth, /en/account/login - an account step under any
  // locale prefix the platform serves the flow under.
  const ACCOUNT_PATH = /(^|\/)account(\/|$)/i;

  const onAccountFlow = () =>
    ACCOUNT_PATH.test(window.location.pathname) ||
    document.querySelector('form[action*="/account"]') !== null;

  const start = () => {
    hideEmailSignup();
    // The platform renders its next step after a submit, so the page is watched
    // - but only on a page that has an account step at all. The form is not
    // that signal: the OTP step renders no form[action*="/account"], so keying
    // the observer off one left that step with the load-time pass alone, and a
    // re-render of the link after load would have gone unhidden. The path is
    // the signal; the form stays as a fallback for a step served off /account.
    if (!onAccountFlow()) return;

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
