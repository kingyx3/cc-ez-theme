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

/*
 * TEMPORARY UNPUBLISHED-PREVIEW DIAGNOSTIC.
 *
 * Arm with ?cc_otp_probe=1. The flag is stored for this tab so it survives the
 * account-flow redirect; use ?cc_otp_probe=0 or close the tab to disable it.
 *
 * Observer only: passive capture listeners, no OTP writes, no preventDefault,
 * no propagation changes, no synthetic events, and no verification requests.
 * Only metadata and string lengths are shown; OTP digits are never displayed.
 * Remove this block before merging the diagnostic branch.
 */
(() => {
  const PARAM = 'cc_otp_probe';
  const SESSION_KEY = 'ccOtpBeforeinputProbeV1';
  const CELL_SELECTOR = '#otp-form .otp-input';
  const MAX_ROWS = 12;

  let requested = null;
  try {
    requested = new URLSearchParams(window.location.search).get(PARAM);
    if (requested === '1') window.sessionStorage.setItem(SESSION_KEY, '1');
    if (requested === '0') window.sessionStorage.removeItem(SESSION_KEY);
  } catch (_) {
    // Storage failures must not affect the account flow.
  }

  let enabled = requested === '1';
  try {
    enabled = enabled || window.sessionStorage.getItem(SESSION_KEY) === '1';
  } catch (_) {
    // Keep the current-page decision only.
  }
  if (!enabled || requested === '0') return;

  const rows = [];
  let output = null;
  let status = null;

  const cells = () => Array.from(document.querySelectorAll(CELL_SELECTOR));
  const stringLength = (value) => (typeof value === 'string' ? value.length : null);

  const transferLength = (event) => {
    if (!event.dataTransfer || typeof event.dataTransfer.getData !== 'function') return null;
    try {
      return stringLength(event.dataTransfer.getData('text/plain'));
    } catch (_) {
      return null;
    }
  };

  const render = () => {
    if (!output || !status) return;
    const found = cells();
    status.textContent = found.length === 6
      ? '6 code cells detected — trigger Android autofill once.'
      : `Waiting for 6 code cells (found ${found.length}).`;
    output.textContent = rows.length ? rows.join('\n') : 'No code-cell events observed yet.';
  };

  const record = (event) => {
    const found = cells();
    const index = found.indexOf(event.target);
    if (index === -1) return;

    const targetLength = event.target && typeof event.target.value === 'string'
      ? event.target.value.length
      : null;
    const cellLengths = found.map((cell) => (
      typeof cell.value === 'string' ? cell.value.length : null
    ));
    const dataLength = stringLength(event.data);
    const pastedLength = transferLength(event);

    rows.push([
      event.type,
      `cell=${index + 1}`,
      `trusted=${event.isTrusted ? 'yes' : 'no'}`,
      `cancelable=${event.cancelable ? 'yes' : 'no'}`,
      `inputType=${event.inputType || '-'}`,
      `dataLen=${dataLength === null ? '-' : dataLength}`,
      `transferLen=${pastedLength === null ? '-' : pastedLength}`,
      `targetLen=${targetLength === null ? '-' : targetLength}`,
      `cells=[${cellLengths.join(',')}]`,
    ].join(' '));
    if (rows.length > MAX_ROWS) rows.splice(0, rows.length - MAX_ROWS);
    render();
  };

  window.addEventListener('beforeinput', record, { capture: true, passive: true });
  window.addEventListener('input', record, { capture: true, passive: true });

  const mount = () => {
    if (!document.body || document.querySelector('[data-cc-code-event-probe]')) return;

    const panel = document.createElement('aside');
    panel.setAttribute('data-cc-code-event-probe', '');
    panel.style.cssText = [
      'position:fixed',
      'left:8px',
      'right:8px',
      'bottom:8px',
      'z-index:2147483647',
      'max-height:42vh',
      'overflow:auto',
      'padding:10px',
      'border:1px solid #8a8a8a',
      'border-radius:8px',
      'background:#111',
      'color:#fff',
      'font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace',
      'white-space:pre-wrap',
      'word-break:break-word',
      'box-shadow:0 2px 12px rgba(0,0,0,.35)',
    ].join(';');

    const heading = document.createElement('div');
    heading.textContent = 'Code event probe — observer only';
    heading.style.cssText = 'font-weight:700;margin-bottom:4px';

    status = document.createElement('div');
    status.style.cssText = 'margin-bottom:6px';

    output = document.createElement('div');
    output.setAttribute('aria-live', 'polite');

    panel.appendChild(heading);
    panel.appendChild(status);
    panel.appendChild(output);
    document.body.appendChild(panel);
    render();

    new MutationObserver(render).observe(document.body, { childList: true, subtree: true });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount, { once: true });
  } else {
    mount();
  }
})();
