/*
 * Temporary, opt-in Android OTP event diagnostic for unpublished previews.
 *
 * Enable once in a tab with ?cc_otp_diag=1. The flag is kept in sessionStorage
 * across the account flow. Disable with ?cc_otp_diag=0.
 *
 * Read-only by design: this file never prevents an event, writes an OTP value,
 * dispatches an event, submits a form, clicks a control, or makes a request.
 * It records only event metadata and string lengths; the OTP digits are never
 * rendered or logged.
 */
(() => {
  const FLAG = 'ccOtpBeforeInputDiagnostic';
  const CELL_SELECTOR = '#otp-form .otp-input';

  let enabled = false;
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get('cc_otp_diag') === '0') {
      window.sessionStorage.removeItem(FLAG);
    } else if (params.get('cc_otp_diag') === '1') {
      window.sessionStorage.setItem(FLAG, '1');
    }
    enabled = window.sessionStorage.getItem(FLAG) === '1';
  } catch (_error) {
    enabled = false;
  }

  if (!enabled) return;

  const records = [];
  let panel = null;
  let verdict = 'WAITING: trigger Android SMS autofill once.';
  let lastBeforeInput = null;

  const cells = () => Array.from(document.querySelectorAll(CELL_SELECTOR));

  const ensurePanel = () => {
    if (panel || !document.body) return panel;

    panel = document.createElement('pre');
    panel.id = 'cc-otp-beforeinput-diagnostic';
    panel.setAttribute('role', 'status');
    panel.setAttribute('aria-live', 'polite');
    Object.assign(panel.style, {
      position: 'fixed',
      left: '8px',
      right: '8px',
      bottom: '8px',
      zIndex: '2147483647',
      margin: '0',
      padding: '10px 12px',
      borderRadius: '8px',
      background: 'rgba(0, 0, 0, 0.92)',
      color: '#fff',
      font: '12px/1.4 monospace',
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
      pointerEvents: 'none',
      maxHeight: '44vh',
      overflow: 'hidden',
    });
    document.body.appendChild(panel);
    return panel;
  };

  const render = () => {
    const node = ensurePanel();
    if (!node) return;

    const recent = records.slice(-6).map((record) => (
      `${record.type} c${record.cell} cancel=${record.cancelable ? 'yes' : 'no'}`
      + ` trusted=${record.trusted ? 'yes' : 'no'}`
      + ` inputType=${record.inputType || '-'} dataLen=${record.dataLength == null ? '-' : record.dataLength}`
      + ` valueLen=${record.valueLength} cells=[${record.cellLengths.join(',')}]`
    ));

    node.textContent = [
      'OTP DIAGNOSTIC — READ ONLY',
      verdict,
      ...recent,
      '',
      'No OTP digits are shown. Screenshot this panel after autofill.',
    ].join('\n');
  };

  const observe = (event) => {
    const target = event.target;
    if (!(target instanceof Element) || !target.matches(CELL_SELECTOR)) return;

    const allCells = cells();
    const cellIndex = allCells.indexOf(target);
    const dataLength = typeof event.data === 'string' ? event.data.length : null;
    const valueLength = typeof target.value === 'string' ? target.value.length : 0;
    const cellLengths = allCells.map((input) => (
      typeof input.value === 'string' ? input.value.length : 0
    ));

    const record = {
      type: event.type,
      cell: cellIndex >= 0 ? cellIndex + 1 : '?',
      cancelable: Boolean(event.cancelable),
      trusted: Boolean(event.isTrusted),
      inputType: typeof event.inputType === 'string' ? event.inputType : '',
      dataLength,
      valueLength,
      cellLengths,
      target,
      at: performance.now(),
    };

    if (event.type === 'beforeinput') {
      lastBeforeInput = record;
      if (dataLength === 6) {
        verdict = event.cancelable
          ? 'VIABLE CANDIDATE: cancelable 6-character beforeinput observed.'
          : 'NOT VIABLE: 6-character beforeinput was not cancelable.';
      }
    }

    if (event.type === 'input') {
      if (cellLengths.length === 6 && cellLengths.every((length) => length === 1)) {
        verdict = 'NATIVE DISTRIBUTION: all six cells are already filled separately.';
      } else if (valueLength === 6 && cellIndex === 0) {
        const paired = lastBeforeInput
          && lastBeforeInput.target === target
          && record.at - lastBeforeInput.at < 1500;

        if (!paired) {
          verdict = 'NOT VIABLE: full code reached cell 1 with no preceding beforeinput.';
        } else if (!lastBeforeInput.cancelable) {
          verdict = 'NOT VIABLE: preceding beforeinput was not cancelable.';
        } else if (lastBeforeInput.dataLength === 6) {
          verdict = 'VIABLE: full-code input followed a cancelable 6-character beforeinput.';
        } else {
          verdict = 'INCONCLUSIVE: beforeinput was cancelable but did not expose six characters.';
        }
      }
    }

    records.push(record);
    if (records.length > 20) records.shift();
    render();
  };

  window.addEventListener('beforeinput', observe, true);
  window.addEventListener('input', observe, true);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', render, { once: true });
  } else {
    render();
  }
})();
