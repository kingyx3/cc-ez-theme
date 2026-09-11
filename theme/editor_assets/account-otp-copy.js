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
 *
 * Temporary unpublished-preview diagnostic: adding ?otpdiag=1 enables a
 * session-scoped, read-only beforeinput observer. It shows only event metadata;
 * it never records OTP digits or changes EasyStore/browser behaviour. Disable
 * with ?otpdiag=0 or by closing the tab.
 */
(() => {
  // "Continue with email instead", "Sign up using your email address instead".
  const EMAIL_SIGNUP = /\be-?mail\b[^.!?]{0,32}\binstead\b/i;
  // Longer than this is a paragraph, not the link.
  const LINK_LENGTH = 80;
  const DIAGNOSTIC_KEY = 'ccOtpBeforeInputDiagnostic';

  const diagnosticRequested = () => {
    const params = new URLSearchParams(window.location.search);
    try {
      if (params.get('otpdiag') === '1') sessionStorage.setItem(DIAGNOSTIC_KEY, '1');
      if (params.get('otpdiag') === '0') sessionStorage.removeItem(DIAGNOSTIC_KEY);
      return sessionStorage.getItem(DIAGNOSTIC_KEY) === '1';
    } catch (_) {
      return params.get('otpdiag') === '1';
    }
  };

  const startBeforeInputDiagnostic = () => {
    if (!diagnosticRequested()) return;

    const panel = document.createElement('div');
    panel.setAttribute('role', 'status');
    panel.setAttribute('aria-live', 'polite');
    panel.style.cssText = [
      'position:fixed',
      'left:12px',
      'right:12px',
      'bottom:12px',
      'z-index:2147483647',
      'padding:12px 14px',
      'border-radius:10px',
      'background:#111',
      'color:#fff',
      'font:13px/1.4 monospace',
      'white-space:pre-wrap',
      'box-shadow:0 3px 18px rgba(0,0,0,.35)'
    ].join(';');

    const show = (lines) => {
      panel.textContent = lines.join('\n');
    };

    show([
      'OTP DIAG: waiting for Android autofill',
      'Read-only: no digits are recorded or changed.',
      'Need: beforeinput + trusted=true + cancelable=true + dataLength=6'
    ]);

    const mount = () => {
      if (!panel.isConnected && document.body) document.body.appendChild(panel);
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', mount, { once: true });
    } else {
      mount();
    }

    const sixCellGroup = (target) => {
      if (!(target instanceof HTMLInputElement) || target.maxLength !== 1) return null;
      let node = target.parentElement;
      for (let depth = 0; node && depth < 5; depth += 1, node = node.parentElement) {
        const cells = Array.from(node.querySelectorAll('input[maxlength="1"]'));
        if (cells.length === 6 && cells.includes(target)) return cells;
      }
      return null;
    };

    window.addEventListener('beforeinput', (event) => {
      const cells = sixCellGroup(event.target);
      if (!cells) return;

      const dataLength = typeof event.data === 'string' ? event.data.length : null;
      const safeCandidate = dataLength === 6
        && event.cancelable === true
        && event.isTrusted === true;

      show([
        `OTP DIAG: ${safeCandidate ? 'PREREQUISITE MET' : 'OBSERVED'}`,
        'beforeinput: yes',
        `cancelable: ${String(event.cancelable)}`,
        `trusted: ${String(event.isTrusted)}`,
        `inputType: ${event.inputType || '(none)'}`,
        `dataLength: ${dataLength === null ? '(null)' : String(dataLength)}`,
        `targetCell: ${String(cells.indexOf(event.target) + 1)} of 6`,
        safeCandidate
          ? 'Result: guarded interception is technically possible for this event.'
          : 'Result: do NOT intercept unless trusted=true, cancelable=true, dataLength=6.'
      ]);
    }, true);
  };

  startBeforeInputDiagnostic();

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
