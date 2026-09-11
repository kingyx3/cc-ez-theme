/*
 * Unpublished-preview-only Android OTP experiment.
 *
 * Enable with ?otpdiag=2. The flag is remembered only for this browser tab so
 * it survives EasyStore's account-step navigation. Normal storefront browsing
 * is a complete no-op.
 *
 * Android on the tested device reaches the page as one trusted, non-cancelable
 * input event with all six digits already in the first visual cell and no
 * preceding beforeinput. This experiment changes only the six DOM values during
 * capture of that same trusted event, then lets the original event continue.
 * It never dispatches an event, stops propagation, submits, clicks, retries, or
 * intercepts network requests.
 */
(() => {
  'use strict';

  const MODE_KEY = 'ccOtpSameEventPreview';

  const enabled = () => {
    const params = new URLSearchParams(window.location.search);
    try {
      if (params.get('otpdiag') === '2') sessionStorage.setItem(MODE_KEY, '2');
      if (params.get('otpdiag') === '0') sessionStorage.removeItem(MODE_KEY);
      return sessionStorage.getItem(MODE_KEY) === '2';
    } catch (_) {
      return params.get('otpdiag') === '2';
    }
  };

  if (!enabled()) return;

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
    'SAME-EVENT OTP EXPERIMENT: armed',
    'Waiting for one trusted Android 6-digit input.',
    'No synthetic events, submit, retry, or network interception.'
  ]);

  const mount = () => {
    if (!panel.isConnected && document.body) document.body.appendChild(panel);
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount, { once: true });
  } else {
    mount();
  }

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

  let trustedInputs = 0;
  let distributions = 0;

  const spreadDuringOriginalInput = (event) => {
    const cells = sixCellGroup(event.target);
    if (!cells) return;
    if (event.isTrusted !== true) return;

    trustedInputs += 1;
    const targetIndex = cells.indexOf(event.target);
    const raw = String(event.target.value || '');
    const digits = /^\d{6}$/.test(raw) ? raw : '';

    if (targetIndex !== 0 || !digits || !cells.slice(1).every((cell) => cell.value === '')) {
      show([
        'SAME-EVENT OTP EXPERIMENT: observed but left unchanged',
        `trustedInputEvents: ${trustedInputs}`,
        `targetCell: ${targetIndex + 1} of 6`,
        `targetLength: ${raw.length}`,
        'Reason: not an exact first-cell 6-digit autofill into five empty siblings.'
      ]);
      return;
    }

    cells.forEach((cell, index) => {
      cell.value = digits[index];
    });
    distributions += 1;

    show([
      'SAME-EVENT OTP EXPERIMENT: DISTRIBUTED',
      `trustedInputEvents: ${trustedInputs}`,
      `distributions: ${distributions}`,
      `cellLengths: ${cells.map((cell) => cell.value.length).join(',')}`,
      'syntheticEventsCreatedByTheme: 0',
      'Original trusted input is continuing to EasyStore now.'
    ]);
  };

  // Passive capture means this experiment cannot cancel the Android event.
  window.addEventListener('input', spreadDuringOriginalInput, { capture: true, passive: true });
})();
