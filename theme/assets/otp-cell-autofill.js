(() => {
  const MIN_CELLS = 4;
  const MAX_CELLS = 8;
  const PROXY_ATTR = 'data-otp-autofill-proxy';
  const OTP_HINT_SELECTOR = [
    'input[autocomplete="one-time-code"]',
    'input[name*="otp" i]',
    'input[id*="otp" i]',
    'input[class*="otp" i]',
    'input[name*="verification" i]',
    'input[id*="verification" i]',
    'input[name*="verify" i]',
    'input[id*="verify" i]',
    'input[name*="code" i]',
    'input[id*="code" i]',
    'input[name*="pin" i]',
    'input[id*="pin" i]',
    'input[data-otp-input]',
    'input[data-input-otp]',
  ].join(',');
  const VERIFICATION_PATTERN = /(?:verify|verification|otp|one[-_ ]time|challenge|two[-_ ]factor|2fa|security[-_ ]code)/i;
  const VERIFICATION_COPY_PATTERN = /(?:enter|verification|security|one[- ]time|sms|text message).{0,40}(?:code|passcode|pin)|(?:code|passcode|pin).{0,40}(?:sent|sms|mobile|phone)/i;
  const EMAIL_FALLBACK_PATTERN = /(?:continue|use|verify|sign\s*in|log\s*in)\s+(?:with\s+)?email(?:\s+instead)?/i;
  const PHONE_FIELD_PATTERN = /(?:phone|mobile|telephone|country[-_ ]?code)/i;
  const SUBMISSION_LOCK_MS = 10000;

  const text = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const digits = (value, limit = MAX_CELLS) => String(value || '').replace(/\D/g, '').slice(0, limit);
  const attr = (element, name) => (
    element && typeof element.getAttribute === 'function' ? element.getAttribute(name) : null
  );
  const setAttr = (element, name, value) => {
    if (element && typeof element.setAttribute === 'function') element.setAttribute(name, value);
  };
  const isProxy = (input) => attr(input, PROXY_ATTR) === 'true';

  const inputCanReceiveOtp = (input) => {
    if (!input || input.disabled || input.readOnly || isProxy(input)) return false;
    const type = text(attr(input, 'type') || input.type || 'text').toLowerCase();
    if (['hidden', 'password', 'submit', 'button', 'checkbox', 'radio', 'email'].includes(type)) return false;
    const identity = [
      attr(input, 'name'), attr(input, 'id'), attr(input, 'autocomplete'),
      attr(input, 'aria-label'), attr(input, 'placeholder'),
    ].join(' ');
    return !PHONE_FIELD_PATTERN.test(identity) || VERIFICATION_PATTERN.test(identity);
  };

  const inputHasOtpHint = (input) => {
    if (!input || isProxy(input)) return false;
    if (typeof input.matches === 'function' && input.matches(OTP_HINT_SELECTOR)) return true;
    return VERIFICATION_PATTERN.test([
      attr(input, 'name'), attr(input, 'id'), attr(input, 'class'),
      attr(input, 'autocomplete'), attr(input, 'aria-label'),
      attr(input, 'placeholder'), attr(input, 'data-testid'),
    ].join(' '));
  };

  const inputLooksLikeOtpCell = (input) => {
    if (!inputCanReceiveOtp(input)) return false;
    if (inputHasOtpHint(input)) return true;
    const maxLength = Number(input.maxLength || attr(input, 'maxlength') || 0);
    const inputMode = text(attr(input, 'inputmode') || input.inputMode).toLowerCase();
    const pattern = text(attr(input, 'pattern'));
    const type = text(attr(input, 'type') || input.type || 'text').toLowerCase();
    return maxLength === 1 || inputMode === 'numeric' || type === 'number' || /(?:\\d|0-9|[0-9])/.test(pattern);
  };

  const queryInputs = (container) => {
    if (!container || typeof container.querySelectorAll !== 'function') return [];
    return Array.from(container.querySelectorAll('input')).filter(inputCanReceiveOtp);
  };

  const plausibleGroup = (inputs, anchor = null) => {
    if (inputs.length < MIN_CELLS || inputs.length > MAX_CELLS) return false;
    if (anchor && !inputs.includes(anchor)) return false;
    return inputs.filter(inputLooksLikeOtpCell).length >= Math.max(MIN_CELLS, inputs.length - 1);
  };

  const findGroupAroundAnchor = (anchor, form) => {
    let container = anchor;
    while (container && container !== form) {
      const inputs = queryInputs(container);
      if (plausibleGroup(inputs, anchor)) return inputs;
      container = container.parentElement;
    }
    const formInputs = queryInputs(form);
    return plausibleGroup(formInputs, anchor) ? formInputs : [];
  };

  const formLooksLikeVerification = (form, documentObject, windowObject) => {
    const pathname = windowObject && windowObject.location ? windowObject.location.pathname : '';
    const context = [
      pathname, attr(form, 'action'), form && form.id, form && form.className,
      attr(form, 'aria-label'), form && form.textContent,
    ].join(' ');
    if (VERIFICATION_PATTERN.test(context) || VERIFICATION_COPY_PATTERN.test(context)) return true;
    return VERIFICATION_COPY_PATTERN.test(text(documentObject && documentObject.body && documentObject.body.textContent));
  };

  const findOtpCells = (form, documentObject, windowObject) => {
    const inputs = queryInputs(form);
    for (const anchor of inputs.filter(inputHasOtpHint)) {
      const group = findGroupAroundAnchor(anchor, form);
      if (group.length) return group;
    }

    const byParent = new Map();
    inputs.filter(inputLooksLikeOtpCell).forEach((input) => {
      const parent = input.parentElement || form;
      if (!byParent.has(parent)) byParent.set(parent, []);
      byParent.get(parent).push(input);
    });
    for (const group of byParent.values()) if (plausibleGroup(group)) return group;

    if (formLooksLikeVerification(form, documentObject, windowObject)) {
      const cellLike = inputs.filter(inputLooksLikeOtpCell);
      if (plausibleGroup(cellLike)) return cellLike;
      if (plausibleGroup(inputs)) return inputs;
    }
    return [];
  };

  const setNativeValue = (input, value, windowObject) => {
    const prototype = windowObject && windowObject.HTMLInputElement
      ? windowObject.HTMLInputElement.prototype
      : null;
    const setter = prototype && Object.getOwnPropertyDescriptor(prototype, 'value');
    if (setter && typeof setter.set === 'function') setter.set.call(input, value);
    else input.value = value;
  };

  const dispatchValueEvents = (input, windowObject) => {
    const EventConstructor = windowObject && windowObject.Event
      ? windowObject.Event
      : (typeof Event !== 'undefined' ? Event : null);
    if (!EventConstructor || typeof input.dispatchEvent !== 'function') return;
    input.dispatchEvent(new EventConstructor('input', { bubbles: true }));
    input.dispatchEvent(new EventConstructor('change', { bubbles: true }));
  };

  const setCellValue = (cell, value, windowObject) => {
    if (String(cell.value || '') === value) return;
    setNativeValue(cell, value, windowObject);
    dispatchValueEvents(cell, windowObject);
  };

  const syncCellsFromCode = (cells, code, windowObject) => {
    const codeDigits = digits(code, cells.length);
    const form = cells[0] && cells[0].form;
    if (form && form.dataset) form.dataset.otpCodeDistributing = 'true';
    cells.forEach((cell, index) => setCellValue(cell, codeDigits[index] || '', windowObject));
    if (form && form.dataset) delete form.dataset.otpCodeDistributing;
    return codeDigits;
  };

  const distributeOtpCode = (cells, code, windowObject, startIndex = 0) => {
    const codeDigits = digits(code, cells.length - startIndex);
    if (!cells.length || !codeDigits) return false;
    const form = cells[0].form;
    if (form && form.dataset) form.dataset.otpCodeDistributing = 'true';
    cells.forEach((cell, index) => {
      if (index >= startIndex) setCellValue(cell, codeDigits[index - startIndex] || '', windowObject);
    });
    if (form && form.dataset) delete form.dataset.otpCodeDistributing;
    return true;
  };

  const removeEmailFallback = (root) => {
    if (!root || typeof root.querySelectorAll !== 'function') return 0;
    let removed = 0;
    root.querySelectorAll('a, button, [role="button"], input[type="button"], input[type="submit"], [onclick]')
      .forEach((element) => {
        const label = text(element.textContent || element.value || attr(element, 'aria-label'));
        if (!EMAIL_FALLBACK_PATTERN.test(label)) return;
        if (typeof element.remove === 'function') element.remove();
        else {
          setAttr(element, 'hidden', 'hidden');
          if (element.style && typeof element.style.setProperty === 'function') {
            element.style.setProperty('display', 'none', 'important');
          }
        }
        removed += 1;
      });
    return removed;
  };

  const proxyContainer = (cells, form) => {
    let container = cells[0] && cells[0].parentElement;
    while (container && container !== form) {
      const inputs = queryInputs(container);
      if (inputs.length === cells.length && cells.every((cell) => inputs.includes(cell))) return container;
      container = container.parentElement;
    }
    return (cells[0] && cells[0].parentElement) || form;
  };

  const focusProxy = (proxy) => {
    if (!proxy || typeof proxy.focus !== 'function') return;
    try { proxy.focus({ preventScroll: true }); } catch (error) { proxy.focus(); }
    const end = String(proxy.value || '').length;
    if (typeof proxy.setSelectionRange === 'function') {
      try { proxy.setSelectionRange(end, end); } catch (error) { /* unsupported */ }
    }
  };

  const schedule = (windowObject, callback, delay) => {
    if (windowObject && typeof windowObject.setTimeout === 'function') {
      return windowObject.setTimeout(callback, delay);
    }
    if (typeof setTimeout === 'function') return setTimeout(callback, delay);
    return null;
  };

  const claimOtpOwnership = (form) => {
    if (!form || !form.dataset) return;
    form.dataset.webOtpRequested = 'true';
    form.dataset.otpEnhancementOwner = 'otp-cell-autofill';
  };

  const guardOtpSubmission = (form, windowObject) => {
    if (!form || !form.dataset || typeof form.addEventListener !== 'function') return;
    claimOtpOwnership(form);
    if (form.dataset.otpSubmissionGuardBound === 'true') return;

    form.dataset.otpSubmissionGuardBound = 'true';
    form.addEventListener('submit', (event) => {
      if (form.dataset.otpSubmissionInFlight === 'true') {
        if (event && typeof event.preventDefault === 'function') event.preventDefault();
        if (event && typeof event.stopImmediatePropagation === 'function') {
          event.stopImmediatePropagation();
        }
        return;
      }

      form.dataset.otpSubmissionInFlight = 'true';
      schedule(windowObject, () => {
        delete form.dataset.otpSubmissionInFlight;
      }, SUBMISSION_LOCK_MS);
    }, true);
  };

  const createOtpProxy = (form, cells, documentObject, windowObject) => {
    if (form && form.__cardboardOtpAutofillProxy) {
      form.__cardboardOtpAutofillProxy.__otpCells = cells;
      return form.__cardboardOtpAutofillProxy;
    }
    if (!documentObject || typeof documentObject.createElement !== 'function') return null;

    const proxy = documentObject.createElement('input');
    proxy.type = 'text';
    proxy.__otpCells = cells;
    setAttr(proxy, PROXY_ATTR, 'true');
    setAttr(proxy, 'autocomplete', 'one-time-code');
    setAttr(proxy, 'inputmode', 'numeric');
    setAttr(proxy, 'pattern', '[0-9]*');
    setAttr(proxy, 'maxlength', String(cells.length));
    setAttr(proxy, 'aria-label', 'Verification code');
    setAttr(proxy, 'autocapitalize', 'off');
    setAttr(proxy, 'spellcheck', 'false');
    setAttr(proxy, 'enterkeyhint', 'done');

    const container = proxyContainer(cells, form);
    if (container && container.style && typeof container.style.setProperty === 'function') {
      if (!text(container.style.position) || container.style.position === 'static') {
        container.style.setProperty('position', 'relative');
      }
    }
    if (proxy.style && typeof proxy.style.setProperty === 'function') {
      [
        ['position', 'absolute'], ['inset', '0'], ['width', '100%'], ['height', '100%'],
        ['opacity', '0.01'], ['z-index', '2147483647'], ['border', '0'], ['margin', '0'],
        ['padding', '0'], ['background', 'transparent'], ['color', 'transparent'],
        ['caret-color', 'transparent'], ['font-size', '16px'], ['box-sizing', 'border-box'],
      ].forEach(([name, value]) => proxy.style.setProperty(name, value));
    }
    if (container && typeof container.appendChild === 'function') container.appendChild(proxy);
    else if (form && typeof form.appendChild === 'function') form.appendChild(proxy);
    else return null;

    const sync = () => {
      const codeDigits = syncCellsFromCode(proxy.__otpCells || cells, proxy.value, windowObject);
      if (String(proxy.value || '') !== codeDigits) setNativeValue(proxy, codeDigits, windowObject);
      if (proxy.dataset) proxy.dataset.lastOtpValue = codeDigits;
      focusProxy(proxy);
    };

    if (typeof proxy.addEventListener === 'function') {
      proxy.addEventListener('input', sync, true);
      proxy.addEventListener('change', sync, true);
      proxy.addEventListener('compositionend', sync, true);
      proxy.addEventListener('paste', (event) => {
        const clipboard = event && (event.clipboardData || (windowObject && windowObject.clipboardData));
        if (!clipboard || typeof clipboard.getData !== 'function') return;
        const pasted = digits(clipboard.getData('text'), cells.length);
        if (!pasted) return;
        if (typeof event.preventDefault === 'function') event.preventDefault();
        setNativeValue(proxy, pasted, windowObject);
        sync();
      }, true);
    }
    if (form && typeof form.addEventListener === 'function') form.addEventListener('submit', sync, true);
    if (form) form.__cardboardOtpAutofillProxy = proxy;
    return proxy;
  };

  const configureOtpCells = (form, cells, windowObject, documentObject = null) => {
    guardOtpSubmission(form, windowObject);

    cells.forEach((cell, index) => {
      setAttr(cell, 'maxlength', '1');
      setAttr(cell, 'inputmode', 'numeric');
      setAttr(cell, 'pattern', '[0-9]*');
      setAttr(cell, 'autocapitalize', 'off');
      setAttr(cell, 'spellcheck', 'false');
      setAttr(cell, 'autocomplete', 'off');
      if (cell.dataset && cell.dataset.otpCellEnhanced === 'true') return;
      if (cell.dataset) cell.dataset.otpCellEnhanced = 'true';

      const handleInput = () => {
        if (form.dataset && form.dataset.otpCodeDistributing === 'true') return;
        const valueDigits = digits(cell.value, cells.length - index);
        if (valueDigits.length > 1) distributeOtpCode(cells, valueDigits, windowObject, index);
        else if (String(cell.value || '') !== valueDigits) setNativeValue(cell, valueDigits, windowObject);
      };
      if (typeof cell.addEventListener === 'function') {
        cell.addEventListener('input', handleInput, true);
        cell.addEventListener('change', handleInput, true);
        cell.addEventListener('paste', (event) => {
          const clipboard = event && (event.clipboardData || (windowObject && windowObject.clipboardData));
          if (!clipboard || typeof clipboard.getData !== 'function') return;
          const pasted = digits(clipboard.getData('text'), cells.length - index);
          if (pasted.length <= 1) return;
          if (typeof event.preventDefault === 'function') event.preventDefault();
          distributeOtpCode(cells, pasted, windowObject, index);
        }, true);
      }
    });

    const proxy = createOtpProxy(form, cells, documentObject, windowObject);
    if (proxy) cells.forEach((cell) => {
      if (cell.dataset && cell.dataset.otpProxyFocusBound === 'true') return;
      if (cell.dataset) cell.dataset.otpProxyFocusBound = 'true';
      if (typeof cell.addEventListener === 'function') {
        cell.addEventListener('focus', () => focusProxy(proxy));
        cell.addEventListener('pointerdown', (event) => {
          if (event && typeof event.preventDefault === 'function') event.preventDefault();
          focusProxy(proxy);
        });
      }
    });
    return proxy;
  };

  const scanAndEnhance = (documentObject, windowObject) => {
    if (!documentObject || typeof documentObject.querySelectorAll !== 'function') return [];
    const groups = [];
    Array.from(documentObject.querySelectorAll('form')).forEach((form) => {
      const cells = findOtpCells(form, documentObject, windowObject);
      if (!cells.length) return;
      const proxy = configureOtpCells(form, cells, windowObject, documentObject);
      groups.push(cells);
      if (!proxy) return;
      const current = digits(proxy.value, cells.length);
      const previous = proxy.dataset ? proxy.dataset.lastOtpValue || '' : '';
      if (current !== previous) {
        syncCellsFromCode(cells, current, windowObject);
        if (proxy.dataset) proxy.dataset.lastOtpValue = current;
      }
    });

    const hasHint = typeof documentObject.querySelector === 'function' && documentObject.querySelector(OTP_HINT_SELECTOR);
    const pathname = windowObject && windowObject.location ? windowObject.location.pathname : '';
    if (groups.length || hasHint || VERIFICATION_PATTERN.test(pathname)) removeEmailFallback(documentObject);
    return groups;
  };

  const boot = (windowObject, documentObject) => {
    const run = () => scanAndEnhance(documentObject, windowObject);
    run();
    if (windowObject && typeof windowObject.MutationObserver === 'function' && documentObject.documentElement) {
      const observer = new windowObject.MutationObserver(run);
      observer.observe(documentObject.documentElement, { childList: true, subtree: true });
    }
    if (windowObject && typeof windowObject.setInterval === 'function') {
      let scans = 0;
      const interval = windowObject.setInterval(() => {
        run();
        scans += 1;
        if (scans >= 240 && typeof windowObject.clearInterval === 'function') windowObject.clearInterval(interval);
      }, 250);
    }
  };

  const api = {
    boot,
    claimOtpOwnership,
    configureOtpCells,
    createOtpProxy,
    distributeOtpCode,
    findOtpCells,
    guardOtpSubmission,
    inputCanReceiveOtp,
    inputHasOtpHint,
    inputLooksLikeOtpCell,
    removeEmailFallback,
    scanAndEnhance,
    syncCellsFromCode,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    window.CardboardOtpAutofill = api;
    api.boot(window, document);
  }
})();
