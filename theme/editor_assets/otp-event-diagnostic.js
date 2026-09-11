/*
 * Temporary, read-only OTP event diagnostic for unpublished preview testing.
 *
 * This script is loaded only when account-otp-copy.js has enabled the
 * `otpdiag` session flag. It observes EasyStore's OTP events and renders only
 * metadata: event type, trust/cancelability, data length, and per-cell value
 * lengths. It never records the OTP digits themselves and never changes an OTP
 * value, cancels/stops an event, dispatches an event, submits a form, or makes
 * a network request.
 */
(() => {
  const CELL_SELECTOR = '#otp-form .otp-input';
  const RECORDS_KEY = 'ccOtpDiagRecordsV1';
  const MAX_RECORDS = 24;
  const PAIR_WINDOW_MS = 1500;

  const safeSessionGet = (key) => {
    try {
      return window.sessionStorage.getItem(key);
    } catch (_error) {
      return null;
    }
  };

  const safeSessionSet = (key, value) => {
    try {
      window.sessionStorage.setItem(key, value);
    } catch (_error) {
      // The on-screen report still works if storage is unavailable.
    }
  };

  const readRecords = () => {
    try {
      const parsed = JSON.parse(safeSessionGet(RECORDS_KEY) || '[]');
      return Array.isArray(parsed) ? parsed.slice(-MAX_RECORDS) : [];
    } catch (_error) {
      return [];
    }
  };

  let records = readRecords();
  let panel = null;
  let statusNode = null;
  let cellsNode = null;
  let logNode = null;

  const otpCells = () => Array.from(document.querySelectorAll(CELL_SELECTOR));

  const verdict = () => {
    for (let index = records.length - 1; index >= 0; index -= 1) {
      const current = records[index];
      if (current.type !== 'input' || current.cell !== 1 || current.valueLength !== 6) continue;

      for (let priorIndex = index - 1; priorIndex >= 0; priorIndex -= 1) {
        const prior = records[priorIndex];
        if (current.at - prior.at > PAIR_WINDOW_MS) break;
        if (prior.type !== 'beforeinput' || prior.cell !== 1) continue;

        if (prior.cancelable === true && prior.trusted === true) {
          return {
            level: 'PASS',
            text: 'PASS: the six-character first-cell autofill was preceded by a trusted, cancelable beforeinput.'
          };
        }
        return {
          level: 'FAIL',
          text: 'FAIL: six characters reached cell 1, but its preceding beforeinput was not both trusted and cancelable.'
        };
      }

      return {
        level: 'FAIL',
        text: 'FAIL: six characters reached cell 1 without an observable preceding beforeinput.'
      };
    }

    return {
      level: 'WAITING',
      text: 'WAITING: trigger Android SMS autofill once. No OTP digits are recorded.'
    };
  };

  const render = () => {
    if (!panel) return;

    const result = verdict();
    statusNode.textContent = result.text;

    const cells = otpCells();
    cellsNode.textContent = cells.length === 6
      ? 'OTP cells detected: 6'
      : `OTP cells detected: ${cells.length} (waiting for 6)`;

    logNode.textContent = records.length
      ? records.map((record) => {
        const dataLength = record.dataLength === null ? '-' : String(record.dataLength);
        const valueLength = record.valueLength === null ? '-' : String(record.valueLength);
        return `${record.type} c${record.cell} trusted=${record.trusted ? 'yes' : 'no'} cancelable=${record.cancelable ? 'yes' : 'no'} inputType=${record.inputType || '-'} dataLen=${dataLength} valueLen=${valueLength} cells=[${record.cellLengths.join(',')}]`;
      }).join('\n')
      : 'No OTP input events captured yet.';
  };

  const makePanel = () => {
    if (panel || !document.body) return;

    panel = document.createElement('section');
    panel.setAttribute('data-cc-otp-diagnostic', 'true');
    Object.assign(panel.style, {
      position: 'fixed',
      left: '8px',
      right: '8px',
      bottom: '8px',
      zIndex: '2147483647',
      maxHeight: '46vh',
      overflow: 'auto',
      padding: '12px',
      border: '2px solid #ffffff',
      borderRadius: '10px',
      background: 'rgba(0, 0, 0, 0.92)',
      color: '#ffffff',
      font: '12px/1.45 monospace',
      textAlign: 'left',
      boxShadow: '0 3px 18px rgba(0, 0, 0, 0.45)'
    });

    const title = document.createElement('strong');
    title.textContent = 'OTP diagnostic — READ ONLY';
    title.style.display = 'block';
    title.style.marginBottom = '6px';

    statusNode = document.createElement('div');
    statusNode.style.marginBottom = '4px';
    statusNode.style.fontWeight = '700';

    cellsNode = document.createElement('div');
    cellsNode.style.marginBottom = '8px';

    logNode = document.createElement('pre');
    Object.assign(logNode.style, {
      margin: '0',
      whiteSpace: 'pre-wrap',
      overflowWrap: 'anywhere'
    });

    const controls = document.createElement('div');
    controls.style.marginTop = '8px';

    const clear = document.createElement('button');
    clear.type = 'button';
    clear.textContent = 'Clear diagnostic log';
    Object.assign(clear.style, {
      padding: '6px 8px',
      font: 'inherit',
      cursor: 'pointer'
    });
    clear.addEventListener('click', () => {
      records = [];
      safeSessionSet(RECORDS_KEY, '[]');
      render();
    });

    controls.appendChild(clear);
    panel.appendChild(title);
    panel.appendChild(statusNode);
    panel.appendChild(cellsNode);
    panel.appendChild(logNode);
    panel.appendChild(controls);
    document.body.appendChild(panel);
    render();
  };

  const recordEvent = (event) => {
    const target = event.target;
    if (!target || !target.matches || !target.matches(CELL_SELECTOR)) return;

    const cells = otpCells();
    const cellIndex = cells.indexOf(target);
    if (cellIndex < 0) return;

    records.push({
      at: Date.now(),
      type: event.type,
      cell: cellIndex + 1,
      trusted: event.isTrusted === true,
      cancelable: event.cancelable === true,
      inputType: typeof event.inputType === 'string' ? event.inputType : '',
      dataLength: typeof event.data === 'string' ? event.data.length : null,
      valueLength: typeof target.value === 'string' ? target.value.length : null,
      cellLengths: cells.map((cell) => typeof cell.value === 'string' ? cell.value.length : 0)
    });
    records = records.slice(-MAX_RECORDS);
    safeSessionSet(RECORDS_KEY, JSON.stringify(records));
    render();
  };

  window.addEventListener('beforeinput', recordEvent, true);
  window.addEventListener('input', recordEvent, true);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', makePanel, { once: true });
  } else {
    makePanel();
  }
})();
