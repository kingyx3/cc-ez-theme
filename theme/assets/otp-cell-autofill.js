(() => {
  const MIN_OTP_CELLS = 4;
  const MAX_OTP_CELLS = 8;
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

  const normaliseText = (value) => String(value || '').replace(/\s+/g, ' ').trim();

  const getAttribute = (element, name) => (
    element && typeof element.getAttribute === 'function' ? element.getAttribute(name) : null
  );

  const setAttribute = (element, name, value) => {
    if (element && typeof element.setAttribute === 'function') element.setAttribute(name, value);
  };

  const inputCanReceiveOtp = (input) => {
    if (!input || input.disabled || input.readOnly) return false;

    const type = normaliseText(getAttribute(input, 'type') || input.type || 'text').toLowerCase();
    if (['hidden', 'password', 'submit', 'button', 'checkbox', 'radio', 'email'].includes(type)) return false;

    const identity = [
      getAttribute(input, 'name'),
      getAttribute(input, 'id'),
      getAttribute(input, 'autocomplete'),
      getAttribute(input, 'aria-label'),
      getAttribute(input, 'placeholder'),
    ].join(' ');

    if (PHONE_FIELD_PATTERN.test(identity) && !VERIFICATION_PATTERN.test(identity)) return false;
    return true;
  };

  const inputHasOtpHint = (input) => {
    if (!input) return false;
    if (typeof input.matches === 'function' && input.matches(OTP_HINT_SELECTOR)) return true;

    const context = [
      getAttribute(input, 'name'),
      getAttribute(input, 'id'),
      getAttribute(input, 'class'),
      getAttribute(input, 'autocomplete'),
      getAttribute(input, 'aria-label'),
      getAttribute(input, 'placeholder'),
      getAttribute(input, 'data-testid'),
    ].join(' ');
    return VERIFICATION_PATTERN.test(context);
  };

  const inputLooksLikeOtpCell = (input) => {
    if (!inputCanReceiveOtp(input)) return false;
    if (inputHasOtpHint(input)) return true;

    const maxLength = Number(input.maxLength || getAttribute(input, 'maxlength') || 0);
    const inputMode = normaliseText(getAttribute(input, 'inputmode') || input.inputMode).toLowerCase();
    const pattern = normaliseText(getAttribute(input, 'pattern'));
    const type = normaliseText(getAttribute(input, 'type') || input.type || 'text').toLowerCase();

    return maxLength === 1
      || inputMode === 'numeric'
      || type === 'number'
      || /(?:\\d|0-9|[0-9])/.test(pattern);
  };

  const queryInputs = (container) => {
    if (!container || typeof container.querySelectorAll !== 'function') return [];
    return Array.from(container.querySelectorAll('input')).filter(inputCanReceiveOtp);
  };

  const isPlausibleOtpGroup = (inputs, anchor = null) => {
    if (inputs.length < MIN_OTP_CELLS || inputs.length > MAX_OTP_CELLS) return false;
    if (anchor && !inputs.includes(anchor)) return false;

    const cellLikeCount = inputs.filter(inputLooksLikeOtpCell).length;
    return cellLikeCount >= Math.max(MIN_OTP_CELLS, inputs.length - 1);
  };

  const findGroupAroundAnchor = (anchor, boundary) => {
    let container = anchor;
    while (container && container !== boundary) {
      const inputs = queryInputs(container);
      if (isPlausibleOtpGroup(inputs, anchor)) return inputs;
      container = container.parentElement;
    }

    if (boundary) {
      const inputs = queryInputs(boundary);
      if (isPlausibleOtpGroup(inputs, anchor)) return inputs;
    }
    return [];
  };

  const formLooksLikeVerification = (form, documentObject, windowObject) => {
    const locationPath = windowObject && windowObject.location ? windowObject.location.pathname : '';
    const action = getAttribute(form, 'action') || '';
    const formContext = [
      locationPath,
      action,
      form && form.id,
      form && form.className,
      getAttribute(form, 'aria-label'),
      form && form.textContent,
    ].join(' ');

    if (VERIFICATION_PATTERN.test(formContext) || VERIFICATION_COPY_PATTERN.test(formContext)) return true;

    const bodyCopy = documentObject && documentObject.body ? documentObject.body.textContent : '';
    return VERIFICATION_COPY_PATTERN.test(normaliseText(bodyCopy));
  };

  const findOtpCells = (form, documentObject, windowObject) => {
    const inputs = queryInputs(form);
    if (!inputs.length) return [];

    const anchors = inputs.filter(inputHasOtpHint);
    for (const anchor of anchors) {
      const group = findGroupAroundAnchor(anchor, form);
      if (group.length) return group;
    }

    const byParent = new Map();
    inputs.filter(inputLooksLikeOtpCell).forEach((input) => {
      const parent = input.parentElement || form;
      if (!byParent.has(parent)) byParent.set(parent, []);
      byParent.get(parent).push(input);
    });
    for (const group of byParent.values()) {
      if (isPlausibleOtpGroup(group)) return group;
    }

    if (formLooksLikeVerification(form, documentObject, windowObject)) {
      const cellLikeInputs = inputs.filter(inputLooksLikeOtpCell);
      if (isPlausibleOtpGroup(cellLikeInputs)) return cellLikeInputs;
      if (isPlausibleOtpGroup(inputs)) return inputs;
    }

    return [];
  };

  const setNativeInputValue = (input, value, windowObject) => {
    const inputPrototype = windowObject && windowObject.HTMLInputElement
      ? windowObject.HTMLInputElement.prototype
      : null;
    const descriptor = inputPrototype
      ? Object.getOwnPropertyDescriptor(inputPrototype, 'value')
      : null;

    if (descriptor && typeof descriptor.set === 'function') descriptor.set.call(input, value);
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
    setNativeInputValue(cell, value, windowObject);
    dispatchValueEvents(cell, windowObject);
  };

  const distributeOtpCode = (cells, code, windowObject, startIndex = 0) => {
    if (!cells.length) return false;

    const digits = String(code || '').replace(/\D/g, '').slice(0, cells.length - startIndex);
    if (!digits) return false;

    const form = cells[0].form;
    if (form && form.dataset) form.dataset.otpCodeDistributing = 'true';

    cells.forEach((cell, index) => {
      if (index < startIndex) return;
      setCellValue(cell, digits[index - startIndex] || '', windowObject);
    });

    if (form && form.dataset) delete form.dataset.otpCodeDistributing;

    const finalIndex = Math.min(startIndex + digits.length, cells.length - 1);
    const focusFinalCell = () => {
      if (cells[finalIndex] && typeof cells[finalIndex].focus === 'function') cells[finalIndex].focus();
    };
    if (windowObject && typeof windowObject.requestAnimationFrame === 'function') {
      windowObject.requestAnimationFrame(focusFinalCell);
    } else {
      focusFinalCell();
    }
    return true;
  };

  const removeEmailFallback = (root) => {
    if (!root || typeof root.querySelectorAll !== 'function') return 0;

    let removed = 0;
    root.querySelectorAll('a, button, [role="button"], input[type="button"], input[type="submit"], [onclick]')
      .forEach((element) => {
        const label = normaliseText(element.textContent || element.value || getAttribute(element, 'aria-label'));
        if (!EMAIL_FALLBACK_PATTERN.test(label)) return;

        if (typeof element.remove === 'function') element.remove();
        else {
          setAttribute(element, 'hidden', 'hidden');
          if (element.style && typeof element.style.setProperty === 'function') {
            element.style.setProperty('display', 'none', 'important');
          }
        }
        removed += 1;
      });
    return removed;
  };

  const configureOtpCells = (form, cells, windowObject) => {
    cells.forEach((cell, index) => {
      setAttribute(cell, 'maxlength', index === 0 ? String(cells.length) : '1');
      setAttribute(cell, 'inputmode', 'numeric');
      setAttribute(cell, 'pattern', '[0-9]*');
      setAttribute(cell, 'autocapitalize', 'off');
      setAttribute(cell, 'spellcheck', 'false');
      setAttribute(cell, 'autocomplete', index === 0 ? 'one-time-code' : 'off');

      if (cell.dataset && cell.dataset.otpCellEnhanced === 'true') return;
      if (cell.dataset) cell.dataset.otpCellEnhanced = 'true';

      const handleInput = () => {
        if (form.dataset && form.dataset.otpCodeDistributing === 'true') return;

        const digits = String(cell.value || '').replace(/\D/g, '');
        if (digits.length > 1) {
          distributeOtpCode(cells, digits, windowObject, index);
          return;
        }

        if (String(cell.value || '') !== digits) setNativeInputValue(cell, digits.slice(0, 1), windowObject);
        if (digits && index < cells.length - 1 && typeof cells[index + 1].focus === 'function') {
          cells[index + 1].focus();
        }
      };

      if (typeof cell.addEventListener === 'function') {
        cell.addEventListener('beforeinput', (event) => {
          const incomingDigits = String(event && event.data || '').replace(/\D/g, '');
          if (incomingDigits.length <= 1) return;
          if (event && typeof event.preventDefault === 'function') event.preventDefault();
          distributeOtpCode(cells, incomingDigits, windowObject, index);
        }, true);
        cell.addEventListener('input', handleInput, true);
        cell.addEventListener('change', handleInput, true);
        cell.addEventListener('compositionend', handleInput, true);
        cell.addEventListener('paste', (event) => {
          const clipboard = event && (event.clipboardData || (windowObject && windowObject.clipboardData));
          if (!clipboard || typeof clipboard.getData !== 'function') return;
          const digits = String(clipboard.getData('text') || '').replace(/\D/g, '');
          if (digits.length <= 1) return;

          if (typeof event.preventDefault === 'function') event.preventDefault();
          distributeOtpCode(cells, digits, windowObject, index);
        }, true);
        cell.addEventListener('keydown', (event) => {
          if (event.key === 'Backspace' && !cell.value && index > 0 && typeof cells[index - 1].focus === 'function') {
            cells[index - 1].focus();
          }
        });
      }
    });
  };

  const scanAndEnhance = (documentObject, windowObject) => {
    if (!documentObject || typeof documentObject.querySelectorAll !== 'function') return [];

    const forms = Array.from(documentObject.querySelectorAll('form'));
    const groups = [];
    forms.forEach((form) => {
      const cells = findOtpCells(form, documentObject, windowObject);
      if (!cells.length) return;
      configureOtpCells(form, cells, windowObject);
      groups.push(cells);
    });

    const hasOtpHint = typeof documentObject.querySelector === 'function'
      && documentObject.querySelector(OTP_HINT_SELECTOR);
    const pageLooksRelevant = groups.length > 0
      || Boolean(hasOtpHint)
      || VERIFICATION_PATTERN.test(windowObject && windowObject.location ? windowObject.location.pathname : '');
    if (pageLooksRelevant) removeEmailFallback(documentObject);

    groups.forEach((cells) => {
      cells.forEach((cell, index) => {
        const digits = String(cell.value || '').replace(/\D/g, '');
        if (digits.length > 1) distributeOtpCode(cells, digits, windowObject, index);
      });
    });
    return groups;
  };

  const boot = (windowObject, documentObject) => {
    const run = () => scanAndEnhance(documentObject, windowObject);

    if (typeof documentObject.addEventListener === 'function') {
      documentObject.addEventListener('beforeinput', (event) => {
        const target = event.target;
        if (!inputCanReceiveOtp(target)) return;
        const digits = String(event.data || '').replace(/\D/g, '');
        if (digits.length <= 1) return;

        const form = target.form || (typeof target.closest === 'function' ? target.closest('form') : null);
        if (!form) return;
        const cells = findOtpCells(form, documentObject, windowObject);
        if (!cells.includes(target)) return;

        if (typeof event.preventDefault === 'function') event.preventDefault();
        distributeOtpCode(cells, digits, windowObject, cells.indexOf(target));
      }, true);
      documentObject.addEventListener('input', (event) => {
        const target = event.target;
        if (!inputCanReceiveOtp(target)) return;
        const digits = String(target.value || '').replace(/\D/g, '');
        if (digits.length <= 1) return;

        const form = target.form || (typeof target.closest === 'function' ? target.closest('form') : null);
        if (!form) return;
        const cells = findOtpCells(form, documentObject, windowObject);
        if (!cells.includes(target)) return;
        distributeOtpCode(cells, digits, windowObject, cells.indexOf(target));
      }, true);
    }

    run();

    if (windowObject && typeof windowObject.MutationObserver === 'function' && documentObject.documentElement) {
      const observer = new windowObject.MutationObserver(run);
      observer.observe(documentObject.documentElement, { childList: true, subtree: true });
    }

    if (windowObject && typeof windowObject.setInterval === 'function') {
      let scans = 0;
      const intervalId = windowObject.setInterval(() => {
        run();
        scans += 1;
        if (scans >= 240 && typeof windowObject.clearInterval === 'function') {
          windowObject.clearInterval(intervalId);
        }
      }, 250);
    }
  };

  const api = {
    boot,
    configureOtpCells,
    distributeOtpCode,
    findOtpCells,
    inputCanReceiveOtp,
    inputHasOtpHint,
    inputLooksLikeOtpCell,
    removeEmailFallback,
    scanAndEnhance,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    window.CardboardOtpAutofill = api;
    api.boot(window, document);
  }
})();