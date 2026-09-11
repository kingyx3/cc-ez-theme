/* Temporary unpublished-preview observer. Remove before merge. */
(() => {
  const PARAM = 'cc_otp_probe';
  const SESSION_KEY = 'ccOtpBeforeinputProbeV2';
  const CELL_SELECTOR = '#otp-form .otp-input';
  const MAX_ROWS = 10;

  let requested = null;
  try {
    requested = new URLSearchParams(window.location.search).get(PARAM);
    if (requested === '1') window.sessionStorage.setItem(SESSION_KEY, '1');
    if (requested === '0') window.sessionStorage.removeItem(SESSION_KEY);
  } catch (_) {}

  let enabled = requested === '1';
  try {
    enabled = enabled || window.sessionStorage.getItem(SESSION_KEY) === '1';
  } catch (_) {}
  if (!enabled || requested === '0') return;

  const rows = [];
  let status = null;
  let output = null;
  const cells = () => Array.from(document.querySelectorAll(CELL_SELECTOR));

  const render = () => {
    if (!status || !output) return;
    const found = cells();
    status.textContent = found.length === 6
      ? '6 code cells detected — use Android autofill once.'
      : `Waiting for 6 code cells (found ${found.length}).`;
    output.textContent = rows.length ? rows.join('\n') : 'No code-cell events observed yet.';
  };

  const record = (event) => {
    const found = cells();
    const index = found.indexOf(event.target);
    if (index < 0) return;

    const dataLength = typeof event.data === 'string' ? event.data.length : '-';
    const targetLength = typeof event.target.value === 'string' ? event.target.value.length : '-';
    const lengths = found.map((cell) => (
      typeof cell.value === 'string' ? cell.value.length : '-'
    ));

    rows.push([
      event.type,
      `cell=${index + 1}`,
      `trusted=${event.isTrusted ? 'yes' : 'no'}`,
      `cancelable=${event.cancelable ? 'yes' : 'no'}`,
      `inputType=${event.inputType || '-'}`,
      `dataLen=${dataLength}`,
      `targetLen=${targetLength}`,
      `cells=[${lengths.join(',')}]`,
    ].join(' '));
    if (rows.length > MAX_ROWS) rows.splice(0, rows.length - MAX_ROWS);
    render();
  };

  window.addEventListener('beforeinput', record, { capture: true, passive: true });
  window.addEventListener('input', record, { capture: true, passive: true });

  const mount = () => {
    if (!document.body || document.querySelector('[data-cc-code-probe]')) return;

    const panel = document.createElement('aside');
    panel.setAttribute('data-cc-code-probe', '');
    panel.style.cssText = [
      'position:fixed', 'left:8px', 'right:8px', 'bottom:8px',
      'z-index:2147483647', 'max-height:42vh', 'overflow:auto',
      'padding:10px', 'border:1px solid #888', 'border-radius:8px',
      'background:#111', 'color:#fff',
      'font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace',
      'white-space:pre-wrap', 'word-break:break-word'
    ].join(';');

    const heading = document.createElement('div');
    heading.textContent = 'Code event probe — observer only';
    heading.style.fontWeight = '700';
    status = document.createElement('div');
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
