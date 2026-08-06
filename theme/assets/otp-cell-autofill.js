(() => {
  'use strict';

  const MIN_CELLS = 4;
  const MAX_CELLS = 8;
  // How far up the tree we look for the element that wraps a whole OTP widget.
  // Cells are often wrapped one-per-<div>, so the group container is rarely the
  // direct parent.
  const MAX_CONTAINER_DEPTH = 5;
  // Long enough to swallow a double tap or a widget that submits on both
  // "input" and "change"; short enough that retyping a wrong code is not
  // blocked (typing six digits takes longer than this).
  const DUPLICATE_SUBMIT_LOCK_MS = 2500;
  const WEB_OTP_TIMEOUT_MS = 120000;

  const OTP_NAME_PATTERN = /(?:otp|passcode|one[-_ ]?time|verification|verify|token|challenge|two[-_ ]?factor|2fa|pin|digit|code)/i;
  // Fields that merely contain "code"/"pin" but are never one-time codes. Kept
  // separate from the positive pattern so "country_code" and friends can never
  // be turned into OTP cells.
  const NON_OTP_NAME_PATTERN = /(?:country|dial|calling|postal|postcode|zip|area|state|province|city|address|currency|language|locale|discount|promo|coupon|voucher|referral|invite|product|variant|sku|barcode|colou?r|search|query)/i;
  const SEARCH_FORM_SELECTOR = '[data-search-history-form],[role="search"],form[action*="search" i]';
  const VERIFICATION_FORM_PATTERN = /(?:verify|verification|otp|one[-_ ]time|challenge|two[-_ ]factor|2fa)/i;
  const EMAIL_FALLBACK_PATTERN = /continue\s+with\s+email\s+instead/i;
  const FILLABLE_TYPES = ['text', 'tel', 'number', 'search', ''];

  const enhancedCells = new WeakSet();
  const enhancedSingleInputs = new WeakSet();
  const webOtpRequested = new WeakSet();
  const submitGuardedForms = new WeakSet();

  // Set while we write values into the cells ourselves, so the "input" handlers
  // we install do not treat our own synthetic events as fresh user input.
  let distributing = false;

  const describe = (input) => [
    input.getAttribute('name') || '',
    input.id || '',
    input.className || '',
    input.getAttribute('aria-label') || '',
  ].join(' ');

  const isFillable = (input) => {
    const type = (input.getAttribute('type') || 'text').toLowerCase();
    return !input.disabled
      && !input.readOnly
      && FILLABLE_TYPES.includes(type);
  };

  // A cell is recognised structurally (single character wide) or by name, never
  // by the page URL - the platform renders the verification step under URLs and
  // form actions the theme cannot predict.
  const looksLikeOtpCell = (input) => {
    if (!isFillable(input)) return false;
    if (input.dataset.otpCell === 'true') return true;

    const context = describe(input);
    if (NON_OTP_NAME_PATTERN.test(context)) return false;

    return input.maxLength === 1
      || input.getAttribute('size') === '1'
      || (input.getAttribute('autocomplete') || '').toLowerCase() === 'one-time-code'
      || OTP_NAME_PATTERN.test(context);
  };

  const groupContainer = (cell, cells) => {
    let node = cell.parentElement;
    let depth = 0;

    // Never widen the search as far as <body>: cells scattered across a page
    // are unrelated fields, not one widget.
    while (node && node !== document.body && depth < MAX_CONTAINER_DEPTH) {
      const contained = cells.filter((candidate) => node.contains(candidate));
      if (contained.length >= MIN_CELLS) return node;
      node = node.parentElement;
      depth += 1;
    }

    return null;
  };

  const findOtpGroups = () => {
    const cells = Array.from(document.querySelectorAll('input')).filter(looksLikeOtpCell);
    if (cells.length < MIN_CELLS) return [];

    const groups = new Map();
    cells.forEach((cell) => {
      const container = groupContainer(cell, cells);
      if (!container) return;
      if (!groups.has(container)) groups.set(container, []);
      groups.get(container).push(cell);
    });

    return Array.from(groups.values())
      .filter((group) => group.length >= MIN_CELLS && group.length <= MAX_CELLS);
  };

  const singleDigit = (value) => String(value || '').replace(/\D/g, '').slice(0, 1);

  // Spreads an autofilled or pasted code across every cell. Browsers hand the
  // whole code to one field (the focused one), which is why an untouched widget
  // only ever shows the first digit on mobile.
  const distributeOtpCode = (cells, code, startIndex) => {
    if (distributing) return false;

    const digits = String(code || '').replace(/\D/g, '');
    if (!digits) return false;

    const requestedStart = Number.isInteger(startIndex) ? startIndex : 0;
    // A full-length code always belongs at the start, wherever it was typed.
    const begin = digits.length >= cells.length
      ? 0
      : Math.min(Math.max(requestedStart, 0), cells.length - 1);

    const values = cells.map((cell, index) => (
      index < begin ? singleDigit(cell.value) : (digits[index - begin] || '')
    ));

    distributing = true;
    try {
      cells.forEach((cell, index) => {
        if (cell.value === values[index]) return;
        cell.value = values[index];
        cell.dispatchEvent(new Event('input', { bubbles: true }));
      });
    } finally {
      distributing = false;
    }

    const lastFilled = Math.min(begin + digits.length, cells.length) - 1;
    const focusIndex = Math.min(Math.max(lastFilled, 0), cells.length - 1);

    // Exactly one "change" event, fired once every cell already holds its final
    // value. Firing it per cell makes widgets that submit on "change" post the
    // verification twice, which registers the customer twice and surfaces
    // "Customer already exists (phone)" on the second response.
    cells[focusIndex].dispatchEvent(new Event('change', { bubbles: true }));

    window.requestAnimationFrame(() => cells[focusIndex].focus());
    return true;
  };

  const requestWebOtp = (cells) => {
    const anchor = cells[0];
    if (webOtpRequested.has(anchor)) return;
    if (!('OTPCredential' in window) || !navigator.credentials) return;
    if (!window.isSecureContext) return;

    webOtpRequested.add(anchor);

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), WEB_OTP_TIMEOUT_MS);
    const form = anchor.form;
    if (form) form.addEventListener('submit', () => controller.abort(), { once: true });

    navigator.credentials.get({
      otp: { transport: ['sms'] },
      signal: controller.signal,
    }).then((credential) => {
      if (!credential || !credential.code) return;
      distributeOtpCode(cells, credential.code, 0);
    }).catch(() => {
      // Unsupported, timed-out, or cancelled WebOTP requests fall back to
      // the browser's own autofill, which the input handlers below spread.
    }).finally(() => {
      window.clearTimeout(timeoutId);
    });
  };

  // The verification step is not idempotent on the platform: a second POST for
  // a brand new account fails with "Customer already exists (phone)". Capture
  // phase so the repeat submit is stopped before any other handler re-posts it.
  const guardDuplicateSubmit = (form) => {
    if (!form || submitGuardedForms.has(form)) return;
    submitGuardedForms.add(form);

    form.addEventListener('submit', (event) => {
      if (form.dataset.otpSubmitInFlight === 'true') {
        event.preventDefault();
        event.stopImmediatePropagation();
        return;
      }

      form.dataset.otpSubmitInFlight = 'true';
      window.setTimeout(() => {
        delete form.dataset.otpSubmitInFlight;
      }, DUPLICATE_SUBMIT_LOCK_MS);
    }, true);
  };

  const applyCellAttributes = (cell, cells) => {
    cell.dataset.otpCell = 'true';
    // Every cell advertises one-time-code so the SMS suggestion appears no
    // matter which cell has focus when the message lands.
    cell.setAttribute('autocomplete', 'one-time-code');
    // maxlength must span the whole code: browsers truncate autofill to
    // maxlength, so "1" leaves five empty cells and one filled digit.
    cell.setAttribute('maxlength', String(cells.length));
    cell.setAttribute('inputmode', 'numeric');
    cell.setAttribute('pattern', '[0-9]*');
    cell.setAttribute('autocapitalize', 'off');
    cell.setAttribute('autocorrect', 'off');
    cell.setAttribute('spellcheck', 'false');
    if (!cell.hasAttribute('enterkeyhint')) cell.setAttribute('enterkeyhint', 'done');
  };

  const bindCell = (cell, index, cells) => {
    if (enhancedCells.has(cell)) return;
    enhancedCells.add(cell);

    cell.addEventListener('input', () => {
      if (distributing) return;

      const digits = cell.value.replace(/\D/g, '');
      if (digits.length > 1) {
        distributeOtpCode(cells, digits, index);
        return;
      }

      if (cell.value !== digits) cell.value = digits;
      if (digits && index < cells.length - 1) cells[index + 1].focus();
    });

    // Some autofill paths only report a "change" - without this the code lands
    // in one cell and stays there.
    cell.addEventListener('change', () => {
      if (distributing) return;
      const digits = cell.value.replace(/\D/g, '');
      if (digits.length > 1) distributeOtpCode(cells, digits, index);
    });

    cell.addEventListener('paste', (event) => {
      const clipboard = event.clipboardData || window.clipboardData;
      if (!clipboard) return;

      const digits = String(clipboard.getData('text') || '').replace(/\D/g, '');
      if (digits.length <= 1) return;

      event.preventDefault();
      distributeOtpCode(cells, digits, index);
    });

    cell.addEventListener('keydown', (event) => {
      if (event.key === 'Backspace' && !cell.value && index > 0) {
        event.preventDefault();
        cells[index - 1].value = '';
        cells[index - 1].focus();
      } else if (event.key === 'ArrowLeft' && index > 0) {
        event.preventDefault();
        cells[index - 1].focus();
      } else if (event.key === 'ArrowRight' && index < cells.length - 1) {
        event.preventDefault();
        cells[index + 1].focus();
      }
    });

    cell.addEventListener('focus', () => {
      if (typeof cell.select === 'function') cell.select();
    });
  };

  const hideEmailFallback = () => {
    document.querySelectorAll('a, button, [role="button"], input[type="button"], input[type="submit"]')
      .forEach((element) => {
        const label = element.textContent || element.value || '';
        if (!EMAIL_FALLBACK_PATTERN.test(label.trim())) return;

        element.hidden = true;
        element.setAttribute('aria-hidden', 'true');
        element.setAttribute('tabindex', '-1');
        element.dataset.mobileOtpFallbackHidden = 'true';
      });
  };

  const enhanceGroup = (cells) => {
    cells.forEach((cell, index) => {
      applyCellAttributes(cell, cells);
      bindCell(cell, index, cells);
    });

    guardDuplicateSubmit(cells[0].form);
    requestWebOtp(cells);
    hideEmailFallback();
  };

  // Stores that render the code as a single field still need the SMS hints and
  // the duplicate-submit guard. Gated on the field itself looking like a
  // verification code so unrelated inputs (the header search box) are untouched.
  const enhanceSingleInputForm = (form) => {
    if (form.matches(SEARCH_FORM_SELECTOR)) return;

    const context = [form.getAttribute('action') || '', form.id, form.className].join(' ');
    if (!VERIFICATION_FORM_PATTERN.test(context)) return;

    const candidates = Array.from(form.querySelectorAll('input'))
      .filter(looksLikeOtpCell)
      .filter((input) => !enhancedSingleInputs.has(input));
    if (candidates.length !== 1) return;

    const input = candidates[0];
    enhancedSingleInputs.add(input);
    input.dataset.otpCell = 'true';
    input.setAttribute('autocomplete', 'one-time-code');
    input.setAttribute('autocapitalize', 'off');
    input.setAttribute('autocorrect', 'off');
    input.setAttribute('spellcheck', 'false');
    if (!input.hasAttribute('inputmode')) input.setAttribute('inputmode', 'numeric');
    if (!input.hasAttribute('enterkeyhint')) input.setAttribute('enterkeyhint', 'done');

    guardDuplicateSubmit(form);
    requestWebOtp([input]);
  };

  const enhanceDocument = () => {
    const groups = findOtpGroups();
    groups.forEach(enhanceGroup);

    const grouped = new Set(groups.flat());
    document.querySelectorAll('form').forEach((form) => {
      if (Array.from(form.querySelectorAll('input')).some((input) => grouped.has(input))) return;
      enhanceSingleInputForm(form);
    });
  };

  let scheduled = false;
  const scheduleEnhance = () => {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(() => {
      scheduled = false;
      enhanceDocument();
    });
  };

  enhanceDocument();

  // The verification step is injected client-side on some storefronts, so the
  // markup is frequently absent on first paint.
  const observer = new MutationObserver(scheduleEnhance);
  observer.observe(document.documentElement, { childList: true, subtree: true });
})();
