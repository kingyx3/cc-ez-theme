/*
 * Temporary read-only Android input-event probe for the unpublished theme.
 *
 * Opt in by opening the preview with ?cc_input_probe=1. The opt-in is kept in
 * sessionStorage so it survives EasyStore navigating to the account code step.
 * Use ?cc_input_probe=0 to clear it.
 *
 * Safety boundary: this script never prevents/stops an event, never writes an
 * input value, never dispatches an event, and never makes a network request.
 * It records metadata only; the code itself is never read or displayed.
 */
(() => {
  const PARAM = 'cc_input_probe';
  const STORAGE_KEY = 'ccInputProbeEnabled';
  const CELL_SELECTOR = '#otp-form .otp-input';
  const params = new URLSearchParams(window.location.search);
  const requested = params.get(PARAM);

  let enabled = requested === '1';
  try {
    if (requested === '0') {
      window.sessionStorage.removeItem(STORAGE_KEY);
      return;
    }
    if (requested === '1') {
      window.sessionStorage.setItem(STORAGE_KEY, '1');
    } else {
      enabled = window.sessionStorage.getItem(STORAGE_KEY) === '1';
    }
  } catch (_) {
    // Some privacy modes can deny storage. The explicit query parameter still
    // works for the current page; no fallback storage is created.
  }

  if (!enabled) return;

  const events = [];
  let lastBeforeInput = null;
  let result = 'Waiting for a full-code autofill into the first cell.';

  const cells = () => Array.from(document.querySelectorAll(CELL_SELECTOR));
  const lengths = (items) => items.map((cell) => String(cell.value || '').length);

  const ensurePanel = () => {
    let panel = document.getElementById('cc-input-event-probe');
    if (panel || !document.body) return panel;

    panel = document.createElement('pre');
    panel.id = 'cc-input-event-probe';
    panel.setAttribute('aria-live', 'polite');
    Object.assign(panel.style, {
      position: 'fixed',
      left: '8px',
      right: '8px',
      bottom: '8px',
      zIndex: '2147483647',
      maxHeight: '46vh',
      overflow: 'auto',
      margin: '0',
      padding: '10px',
      border: '2px solid currentColor',
      borderRadius: '8px',
      background: '#fff',
      color: '#111',
      font: '12px/1.35 monospace',
      whiteSpace: 'pre-wrap',
      boxShadow: '0 2px 12px rgba(0,0,0,.25)',
    });
    document.body.appendChild(panel);
    return panel;
  };

  const render = () => {
    const panel = ensurePanel();
    if (!panel) return;

    const rows = events.map((entry) => {
      const before = entry.type === 'beforeinput'
        ? ` cancelable=${entry.cancelable}`
        : '';
      return `${entry.type} cell=${entry.cell + 1}${before}`
        + ` trusted=${entry.trusted}`
        + ` inputType=${entry.inputType || '-'}`
        + ` dataLen=${entry.dataLength === null ? '-' : entry.dataLength}`
        + ` valueLen=${entry.valueLength}`
        + ` cells=[${entry.cellLengths.join(',')}]`;
    });

    panel.textContent = [
      'Input event probe — READ ONLY',
      `Cells currently found: ${cells().length}`,
      `Result: ${result}`,
      '',
      ...(rows.length ? rows : ['No matching events yet.']),
      '',
      'Take a screenshot after tapping the Android autofill suggestion.',
      'No code digits are recorded or shown.',
    ].join('\n');
  };

  const record = (event) => {
    const currentCells = cells();
    const index = currentCells.indexOf(event.target);
    if (index < 0) return;

    const entry = {
      type: event.type,
      cell: index,
      cancelable: event.cancelable === true,
      trusted: event.isTrusted === true,
      inputType: typeof event.inputType === 'string' ? event.inputType : '',
      dataLength: typeof event.data === 'string' ? event.data.length : null,
      valueLength: String(event.target.value || '').length,
      cellLengths: lengths(currentCells),
      at: performance.now(),
    };

    events.push(entry);
    if (events.length > 10) events.shift();

    if (event.type === 'beforeinput') {
      lastBeforeInput = entry;
    } else if (event.type === 'input' && index === 0 && entry.valueLength === 6) {
      const paired = lastBeforeInput
        && lastBeforeInput.cell === 0
        && entry.at - lastBeforeInput.at >= 0
        && entry.at - lastBeforeInput.at < 1500;

      if (!paired) {
        result = 'NOT SAFE: six-digit first-cell input arrived without a matching beforeinput.';
      } else if (!lastBeforeInput.cancelable) {
        result = 'NOT SAFE: matching beforeinput exists but is not cancelable.';
      } else if (!lastBeforeInput.trusted || !entry.trusted) {
        result = 'INCONCLUSIVE: matching events were not browser-trusted.';
      } else {
        result = 'PROMISING: trusted, cancelable beforeinput occurred before the six-digit input.';
      }
    }

    render();
  };

  window.addEventListener('beforeinput', record, true);
  window.addEventListener('input', record, true);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', render, { once: true });
  } else {
    render();
  }
})();
