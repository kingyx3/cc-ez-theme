/*
 * Temporary observer-only diagnostic for the unpublished Android OTP preview.
 *
 * Enable with ?cc_otp_probe=1. The flag is kept in sessionStorage so it survives
 * the account-flow redirect in the same tab. Disable with ?cc_otp_probe=0 or by
 * closing the tab.
 *
 * This script never writes OTP values, cancels/stops events, dispatches events,
 * submits/clicks anything, or performs network requests. Its listeners are
 * passive capture listeners. It records only event metadata and string lengths;
 * the OTP digits themselves are never rendered or logged.
 *
 * REMOVE THIS ASSET AND ITS LAYOUT INCLUDE BEFORE MERGING THE DIAGNOSTIC BRANCH.
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
    // A storage failure must not affect account behavior. The current-page URL
    // flag still enables the observer below when requested === '1'.
  }

  let enabled = requested === '1';
  try {
    enabled = enabled || window.sessionStorage.getItem(SESSION_KEY) === '1';
  } catch (_) {
    // Keep the current-page decision only.
  }
  if (!enabled || requested === '0') return;

  const rows = [];
  let panel = null;
  let output = null;
  let status = null;

  const cells = () => Array.from(document.querySelectorAll(CELL_SELECTOR));

  const safeLength = (value) => (typeof value === 'string' ? value.length : null);

  const transferLength = (event) => {
    if (!event.dataTransfer || typeof event.dataTransfer.getData !== 'function') return null;
    try {
      return safeLength(event.dataTransfer.getData('text/plain'));
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
    output.textContent = rows.length
      ? rows.join('\n')
      : 'No code-cell events observed yet.';
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
    const dataLength = safeLength(event.data);
    const pastedLength = transferLength(event);
    const line = [
      event.type,
      `cell=${index + 1}`,
      `trusted=${event.isTrusted ? 'yes' : 'no'}`,
      `cancelable=${event.cancelable ? 'yes' : 'no'}`,
      `inputType=${event.inputType || '-'}`,
      `dataLen=${dataLength === null ? '-' : dataLength}`,
      `transferLen=${pastedLength === null ? '-' : pastedLength}`,
      `targetLen=${targetLength === null ? '-' : targetLength}`,
      `cells=[${cellLengths.join(',')}]`,
    ].join(' ');

    rows.push(line);
    if (rows.length > MAX_ROWS) rows.splice(0, rows.length - MAX_ROWS);
    render();
  };

  // Passive capture listeners can observe the browser/platform event before
  // EasyStore's bubbling handlers without being able to cancel that event.
  window.addEventListener('beforeinput', record, { capture: true, passive: true });
  window.addEventListener('input', record, { capture: true, passive: true });

  const mount = () => {
    if (!document.body || panel) return;

    panel = document.createElement('aside');
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

    // Only refresh the readout when EasyStore swaps account-step markup.
    new MutationObserver(render).observe(document.body, { childList: true, subtree: true });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount, { once: true });
  } else {
    mount();
  }
})();
