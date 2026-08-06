(() => {
  const OTP_INPUT_SELECTOR = [
    'input[autocomplete="one-time-code"]',
    'input[name*="otp" i]',
    'input[id*="otp" i]',
    'input[name*="verification" i]',
    'input[id*="verification" i]',
    'input[name*="verify" i]',
    'input[id*="verify" i]',
    'input[name*="code" i]',
    'input[id*="code" i]',
    'input[name*="pin" i]',
    'input[id*="pin" i]',
  ].join(',');
  const VERIFICATION_PATTERN = /(?:verify|verification|otp|one[-_ ]time|challenge|two[-_ ]factor|2fa)/i;
  const EMAIL_FALLBACK_PATTERN = /continue\s+with\s+email\s+instead/i;
  const SUBMISSION_LOCK_MS = 10000;

  const inputCanReceiveOtp = (input) => {
    const type = (input.getAttribute('type') || 'text').toLowerCase();
    return !input.disabled
      && !input.readOnly
      && !['hidden', 'password', 'submit', 'button', 'checkbox', 'radio'].includes(type);
  };

  const formLooksLikeVerification = (form) => {
    const action = form.getAttribute('action') || '';
    const context = [window.location.pathname, action, form.id, form.className].join(' ');
    return VERIFICATION_PATTERN.test(context);
  };

  const getOtpCells = (form) => {
    const candidates = Array.from(form.querySelectorAll(OTP_INPUT_SELECTOR))
      .filter(inputCanReceiveOtp)
      .filter((input) => !['email', 'tel'].includes((input.type || '').toLowerCase()));

    if (candidates.length < 4 || candidates.length > 8) return [];

    return candidates;
  };

  const setCellValue = (cell, value) => {
    if (cell.value === value) return;
    cell.value = value;
    cell.dispatchEvent(new Event('input', { bubbles: true }));
    cell.dispatchEvent(new Event('change', { bubbles: true }));
  };

  const distributeOtpCode = (cells, code) => {
    if (!cells.length) return;

    const digits = String(code || '').replace(/\D/g, '').slice(0, cells.length);
    if (!digits) return;

    const form = cells[0].form;
    if (form) form.dataset.otpCodeDistributing = 'true';

    cells.forEach((cell, index) => setCellValue(cell, digits[index] || ''));

    if (form) delete form.dataset.otpCodeDistributing;

    const focusIndex = Math.min(digits.length, cells.length - 1);
    window.requestAnimationFrame(() => cells[focusIndex].focus());
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

  const guardOtpSubmission = (form) => {
    if (form.dataset.otpSubmissionGuardBound === 'true') return;

    form.dataset.otpSubmissionGuardBound = 'true';
    form.addEventListener('submit', (event) => {
      if (form.dataset.otpSubmissionInFlight === 'true') {
        event.preventDefault();
        event.stopImmediatePropagation();
        return;
      }

      form.dataset.otpSubmissionInFlight = 'true';
      window.setTimeout(() => {
        delete form.dataset.otpSubmissionInFlight;
      }, SUBMISSION_LOCK_MS);
    }, true);
  };

  const enhanceOtpCells = (form, cells) => {
    cells.forEach((cell, index) => {
      cell.setAttribute('maxlength', index === 0 ? String(cells.length) : '1');
      cell.setAttribute('inputmode', 'numeric');
      cell.setAttribute('pattern', '[0-9]*');
      cell.setAttribute('autocapitalize', 'off');
      cell.setAttribute('spellcheck', 'false');
      cell.setAttribute('autocomplete', index === 0 ? 'one-time-code' : 'off');

      if (cell.dataset.otpCellEnhanced === 'true') return;
      cell.dataset.otpCellEnhanced = 'true';

      cell.addEventListener('input', () => {
        if (form.dataset.otpCodeDistributing === 'true') return;

        const digits = cell.value.replace(/\D/g, '');
        if (digits.length > 1) {
          distributeOtpCode(cells, digits);
          return;
        }

        if (cell.value !== digits) cell.value = digits.slice(0, 1);
        if (digits && index < cells.length - 1) cells[index + 1].focus();
      }, true);

      cell.addEventListener('paste', (event) => {
        const clipboard = event.clipboardData || window.clipboardData;
        if (!clipboard) return;
        const pastedCode = clipboard.getData('text');
        const digits = pastedCode.replace(/\D/g, '');
        if (digits.length <= 1) return;

        event.preventDefault();
        distributeOtpCode(cells, digits);
      }, true);

      cell.addEventListener('keydown', (event) => {
        if (event.key === 'Backspace' && !cell.value && index > 0) {
          cells[index - 1].focus();
        }
      });
    });

    hideEmailFallback();
  };

  const enhanceVerificationForm = (form) => {
    if (!formLooksLikeVerification(form)) return;

    const cells = getOtpCells(form);
    if (!cells.length) return;

    // search-history.js contains the retired WebOTP helper. Claim ownership before
    // its deferred callback runs so only this script can populate the OTP form.
    form.dataset.webOtpRequested = 'true';
    form.dataset.otpEnhancementOwner = 'otp-cell-autofill';
    guardOtpSubmission(form);
    enhanceOtpCells(form, cells);
  };

  const enhanceWithin = (root) => {
    if (!root || !root.querySelectorAll) return;

    if (root.matches && root.matches('form')) enhanceVerificationForm(root);
    root.querySelectorAll('form').forEach(enhanceVerificationForm);
  };

  enhanceWithin(document);

  const observer = new MutationObserver(() => enhanceWithin(document));
  observer.observe(document.documentElement, { childList: true, subtree: true });
})();
