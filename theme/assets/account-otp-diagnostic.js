/*
 * Temporary, opt-in Android OTP event diagnostic for unpublished previews.
 *
 * Enable for the current tab by adding `?cc_otp_probe=1` to any storefront URL.
 * The flag is kept in sessionStorage so it survives navigation into EasyStore's
 * /account/auth flow even if EasyStore drops the query parameter. Disable with
 * `?cc_otp_probe=0` or by closing the tab.
 *
 * This probe is intentionally read-only with respect to EasyStore's OTP widget:
 * listeners are passive, it never prevents/stops an event, writes an input
 * value, dispatches an event, submits a form, clicks a control, or makes a
 * network request. It records only event metadata and input lengths; OTP digits
 * are never displayed or stored.
 */
(() => {
  const PARAM = 'cc_otp_probe';
  const STORAGE_KEY = 'ccOtpProbeEnabled';
  const CELL_SELECTOR = '#otp-form .otp-input';
  const params = new URLSearchParams(window.location.search);
  const requested = params.get(PARAM);

  let enabled = requested === '1';
  try {
    if (requested === '1') sessionStorage.setItem(STORAGE_KEY, '1');
    if (requested === '0') sessionStorage.removeItem(STORAGE_KEY);
    enabled = requested !== '0' && sessionStorage.getItem(STORAGE_KEY) === '1';
  } catch (_) {
    // Some preview/privacy contexts may block sessionStorage. The explicit
    // query parameter still enables the probe for the current page.
  }

  if (!enabled) return;

  const MAX_ROWS = 12;
  const rows = [];
  let panel = null;
  let status = null;
  let log = null;
  let lastBeforeInput = null;

  const cells = () => Array.from(document.querySelectorAll(CELL_SELECTOR));
  const valueLengths = () => cells().map((cell) => String(cell.value || '').length);

  const setStatus = (message) => {
    if (!status) return;
    status.textContent = message;
  };

  const renderRows = () => {
    if (!log) return;
    log.textContent = rows.length ? rows.join('\n') : 'No OTP input events observed yet.';
  };

  const addRow = (message) => {
    rows.push(message);
    while (rows.length > MAX_ROWS) rows.shift();
    renderRows();
  };

  const ensurePanel = () => {
    if (panel || !document.body) return;

    panel = document.createElement('aside');
    panel.id = 'cc-otp-probe';
    panel.setAttribute('role', 'status');
    panel.style.cssText = [
      'position:fixed',
      'left:8px',
      'right:8px',
      'bottom:8px',
      'z-index:2147483647',
      'max-height:42vh',
      'overflow:auto',
      'padding:10px 12px',
      'border:2px solid #111',
      'border-radius:8px',
      'background:#fff',
      'color:#111',
      'font:12px/1.35 monospace',
      'box-shadow:0 2px 12px rgba(0,0,0,.25)'
    ].join(';');

    const title = document.createElement('strong');
    title.textContent = 'OTP probe active (read-only)';
    title.style.display = 'block';

    status = document.createElement('div');
    status.style.cssText = 'margin:4px 0 6px;font-weight:700;';

    log = document.createElement('pre');
    log.style.cssText = 'margin:0;white-space:pre-wrap;word-break:break-word;';

    panel.appendChild(title);
    panel.appendChild(status);
    panel.appendChild(log);
    document.body.appendChild(panel);

    renderRows();
    const count = cells().length;
    setStatus(count === 6
      ? 'Six OTP cells found. Trigger Android SMS autofill once.'
      : `Waiting for six OTP cells (found ${count}).`);
  };

  const eventTargetCell = (event) => {
    const target = event.target;
    if (!target || !target.matches || !target.matches(CELL_SELECTOR)) return null;
    const all = cells();
    const index = all.indexOf(target);
    return index < 0 ? null : { target, index };
  };

  const describe = (event) => {
    const match = eventTargetCell(event);
    if (!match) return;

    const dataLength = typeof event.data === 'string' ? event.data.length : null;
    const inputType = event.inputType || 'n/a';
    const lengths = valueLengths();
    const targetLength = String(match.target.value || '').length;

    addRow(
      `${event.type} cell=${match.index + 1} trusted=${event.isTrusted ? 'yes' : 'no'} `
      + `cancelable=${event.cancelable ? 'yes' : 'no'} inputType=${inputType} `
      + `dataLength=${dataLength === null ? 'null' : dataLength} `
      + `targetLength=${targetLength} cells=[${lengths.join(',')}]`
    );

    if (event.type === 'beforeinput') {
      lastBeforeInput = {
        target: match.target,
        cancelable: event.cancelable,
        trusted: event.isTrusted,
        at: performance.now()
      };
      return;
    }

    if (event.type !== 'input') return;

    const completeAcrossCells = lengths.length === 6 && lengths.every((length) => length === 1);
    if (completeAcrossCells) {
      setStatus('NATIVE DISTRIBUTION: all six cells are already filled separately.');
      return;
    }

    if (match.index !== 0 || targetLength !== 6) return;

    const precursor = lastBeforeInput
      && lastBeforeInput.target === match.target
      && performance.now() - lastBeforeInput.at < 1500
      ? lastBeforeInput
      : null;

    if (!precursor) {
      setStatus('NOT SAFE: six-digit first-cell input had no observed beforeinput.');
    } else if (!precursor.cancelable) {
      setStatus('NOT SAFE: the preceding beforeinput was not cancelable.');
    } else if (!precursor.trusted || !event.isTrusted) {
      setStatus('INCONCLUSIVE: event pair was not browser-trusted. Retest with real SMS autofill.');
    } else {
      setStatus('PREREQUISITE MET: six-digit autofill followed a trusted, cancelable beforeinput.');
    }
  };

  const listenerOptions = { capture: true, passive: true };
  window.addEventListener('beforeinput', describe, listenerOptions);
  window.addEventListener('input', describe, listenerOptions);

  const refresh = () => {
    ensurePanel();
    if (!status || rows.length) return;
    const count = cells().length;
    setStatus(count === 6
      ? 'Six OTP cells found. Trigger Android SMS autofill once.'
      : `Waiting for six OTP cells (found ${count}).`);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', refresh, { once: true });
  } else {
    refresh();
  }

  const observer = new MutationObserver(refresh);
  observer.observe(document.documentElement, { childList: true, subtree: true });
})();
