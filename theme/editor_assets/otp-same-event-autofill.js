/*
 * Android one-time-code handoff for EasyStore's six-cell OTP widget.
 *
 * On the tested Android browser, SMS autofill arrives as one trusted,
 * non-cancelable `input` event with all six digits already in the first visual
 * cell and no preceding `beforeinput`. The old theme workaround created a new
 * synthetic input event after spreading the digits, which could make EasyStore
 * verify twice and surface "Customer already exists (phone)" after the first
 * request had already succeeded.
 *
 * This helper does not manufacture a second event. During capture of the one
 * trusted Android event it synchronously changes the six plain-DOM values, then
 * lets that same original event continue to EasyStore. It never cancels or
 * stops the event, submits/clicks anything, retries verification, or intercepts
 * network requests.
 */
(() => {
  'use strict';

  const OTP_STEP = /verification\s+code|one-time\s+password|\botp\b|verify\s+your\s+(?:mobile|phone)|(?:code\s+(?:we\s+)?(?:just\s+)?sent|sent\s+(?:you\s+)?(?:an?|the)\s+code)|resend\s+(?:the\s+)?code/i;
  const AUTH_PATH = /^\/(?:account(?:\/|$)|verify(?:\/|$))/i;

  const onOtpStep = () => {
    if (document.querySelector('#otp-form')) return true;
    if (!AUTH_PATH.test(String(window.location.pathname || ''))) return false;
    const text = (document.body && document.body.textContent) || '';
    return OTP_STEP.test(text);
  };

  const frameworkControlled = (node) => {
    if (!node) return false;
    const keys = Object.keys(node);
    return keys.some((key) => key.startsWith('__react') || key.startsWith('__ng'))
      || Boolean(node.__vue__ || node.__vue_app__ || node.__vnode || node.__svelte_meta);
  };

  const sixCellGroup = (target) => {
    if (!(target instanceof HTMLInputElement)) return null;

    let node = target.parentElement;
    for (let depth = 0; node && depth < 5; depth += 1, node = node.parentElement) {
      const cells = Array.from(node.querySelectorAll('input')).filter((cell) => {
        const type = String(cell.getAttribute('type') || 'text').toLowerCase();
        return type !== 'hidden' && type !== 'submit' && type !== 'button';
      });

      if (cells.length !== 6 || !cells.includes(target)) continue;
      if (frameworkControlled(node) || cells.some(frameworkControlled)) return null;
      return cells;
    }

    return null;
  };

  const spreadDuringOriginalInput = (event) => {
    if (event.isTrusted !== true) return;
    if (!onOtpStep()) return;

    const cells = sixCellGroup(event.target);
    if (!cells) return;
    if (cells[0] !== event.target) return;

    const code = String(event.target.value || '');
    if (!/^\d{6}$/.test(code)) return;
    if (!cells.slice(1).every((cell) => cell.value === '')) return;

    cells.forEach((cell, index) => {
      cell.value = code[index];
    });
  };

  // Passive capture is deliberate: this code cannot cancel Android's original
  // input event. EasyStore receives that same event after the values are split.
  // The listener is installed even before the OTP row exists because EasyStore
  // can render the next account step dynamically in the same document.
  window.addEventListener('input', spreadDuringOriginalInput, {
    capture: true,
    passive: true,
  });
})();
