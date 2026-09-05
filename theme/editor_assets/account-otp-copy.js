/*
 * Account OTP step adjustments for the platform-owned EasyStore flow.
 *
 * This store signs customers up by mobile number only, so the copy helper hides
 * the platform's "continue with email instead" link. Android can also place all
 * six SMS digits in one EasyStore OTP cell. The autofill helper below repairs
 * that one browser event without taking ownership of verification: EasyStore
 * receives exactly one completed input event, targeted at the final cell.
 *
 * The autofill boundary is deliberately narrower than the reverted fixes. A
 * full-code browser event is stopped at window capture before EasyStore sees it;
 * only five digits are written while that event exists. The sixth digit is then
 * written and one input event is handed to the final cell. That means neither an
 * old "submit only on cell 6" handler nor a newer "submit whenever all cells are
 * full" handler can see two completed events. Manual typing and native paste are
 * untouched. If the known six-cell plain-DOM shape changes or framework state
 * appears, the helper fails closed and leaves the platform alone.
 */
(() => {
  const CELL_SELECTOR = '#otp-form .otp-input';
  const CELL_COUNT = 6;

  let replayingOtpInput = false;
  let lastOtpCells = null;
  let lastOtpCode = '';

  const frameworkControlled = (node) => {
    if (!node) return false;
    const keys = Object.keys(node);
    return keys.some((key) => key.startsWith('__react') || key.startsWith('__ng'))
      || Boolean(node.__vue__ || node.__vue_app__ || node.__vnode || node.__svelte_meta);
  };

  const sameCells = (left, right) => Boolean(left)
    && left.length === right.length
    && left.every((cell, index) => cell === right[index]);

  const safeOtpCells = (target) => {
    const cells = Array.from(document.querySelectorAll(CELL_SELECTOR));
    if (cells.length !== CELL_COUNT || !cells.includes(target)) return null;

    const container = document.getElementById('otp-form');
    if (!container || frameworkControlled(container)) return null;

    const parent = cells[0].parentElement;
    if (!parent || cells.some((cell) => cell.parentElement !== parent)) return null;

    const unsafe = cells.some((cell) => {
      if (cell.tagName !== 'INPUT' || cell.disabled || cell.readOnly) return true;
      if (cell.getAttribute('maxlength') !== '1') return true;
      const type = (cell.getAttribute('type') || 'text').toLowerCase();
      if (!['number', 'tel', 'text'].includes(type)) return true;
      return frameworkControlled(cell);
    });

    return unsafe ? null : cells;
  };

  const spreadFullOtpAutofill = (event) => {
    if (replayingOtpInput) return;

    const target = event.target;
    if (!target || !target.matches || !target.matches(CELL_SELECTOR)) return;

    const cells = safeOtpCells(target);
    if (!cells) return;

    if (target.value === '') {
      lastOtpCells = null;
      lastOtpCode = '';
      return;
    }

    const digits = String(target.value || '').replace(/\D/g, '');
    if (digits.length !== CELL_COUNT) return;

    // The original multi-digit browser event must never reach EasyStore. If it
    // did, a platform handler that submits whenever all cells are populated
    // could verify once here and again on the final-cell handoff below.
    event.stopImmediatePropagation();

    const repeated = lastOtpCode === digits && sameCells(lastOtpCells, cells);
    const last = cells[cells.length - 1];

    // Keep the DOM incomplete for the full lifetime of the stopped event.
    cells.forEach((cell, index) => {
      cell.value = index === cells.length - 1 ? '' : digits[index];
    });

    // Android may emit the same autofill event more than once for a single tap.
    // Restore the display, but do not hand the same code to EasyStore twice.
    if (repeated) {
      last.value = digits[digits.length - 1];
      return;
    }

    lastOtpCells = cells.slice();
    lastOtpCode = digits;

    replayingOtpInput = true;
    try {
      last.value = digits[digits.length - 1];
      last.dispatchEvent(new Event('input', { bubbles: true }));
    } finally {
      replayingOtpInput = false;
    }
  };

  // Window capture runs before document, container, and cell handlers. That is
  // the boundary needed to sanitize a full-code browser event before EasyStore
  // can observe it. The listener is inert everywhere without the exact widget.
  window.addEventListener('input', spreadFullOtpAutofill, true);

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
