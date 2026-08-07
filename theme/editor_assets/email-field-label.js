(() => {
  const CHECKOUT_PATH = /\/checkouts?(?:\/|$)/i;
  const ACCOUNT_DETAILS_PATH = /\/account\/details(?:\/|$)/i;
  const FALLBACK_LABEL = 'Email';
  let generatedId = 0;

  const isCheckout = () => CHECKOUT_PATH.test(window.location.pathname);
  const isAccountDetails = () => ACCOUNT_DETAILS_PATH.test(window.location.pathname);
  const isTargetPage = () => isCheckout() || isAccountDetails();

  const isEmailInput = (input) => {
    const type = (input.getAttribute('type') || '').toLowerCase();
    const autocomplete = (input.getAttribute('autocomplete') || '').toLowerCase();
    const name = (input.getAttribute('name') || '').toLowerCase();
    const id = (input.id || '').toLowerCase();

    return type === 'email' || autocomplete === 'email' || name.includes('email') || id.includes('email');
  };

  const isUsableInput = (input) => {
    if (input.disabled || (input.getAttribute('type') || '').toLowerCase() === 'hidden') return false;
    if (input.closest('[hidden], .hidden, .hide')) return false;
    return true;
  };

  const findAssociatedLabel = (input) => {
    if (input.labels && input.labels.length > 0) return input.labels[0];
    if (!input.id) return null;

    return Array.from(document.querySelectorAll('label[for]')).find(
      (label) => label.getAttribute('for') === input.id,
    ) || null;
  };

  const labelTextFor = (input, label) => {
    const existingText = label && label.textContent ? label.textContent.trim() : '';
    const placeholder = (input.getAttribute('placeholder') || '').trim();
    const ariaLabel = (input.getAttribute('aria-label') || '').trim();

    return existingText || placeholder || ariaLabel || FALLBACK_LABEL;
  };

  const ensureEmailLabel = (input, createLabel) => {
    if (!input || !isUsableInput(input)) return;

    if (!input.id) {
      generatedId += 1;
      input.id = `EmailField-${generatedId}`;
    }

    let label = findAssociatedLabel(input);
    const text = labelTextFor(input, label);

    if (!label && createLabel) {
      label = document.createElement('label');
      label.className = 'field__label';
      label.htmlFor = input.id;
      input.insertAdjacentElement('afterend', label);
    }

    if (label) {
      label.classList.remove('label--hidden', 'visually-hidden', 'hidden', 'hide');
      if (!label.textContent.trim()) label.textContent = text;

      const field = input.closest('.field');
      if (field) field.classList.add('on_focus');
    }

    if (!input.getAttribute('aria-label')) input.setAttribute('aria-label', text);

    if (label) {
      input.classList.remove('no-float-label');
      if (!(input.getAttribute('placeholder') || '').trim()) input.setAttribute('placeholder', text);
    }
  };

  const repairEmailFields = () => {
    ensureEmailLabel(document.getElementById('DetailEmail'), true);

    if (!isCheckout()) return;

    document.querySelectorAll('input').forEach((input) => {
      if (isEmailInput(input)) ensureEmailLabel(input, true);
    });
  };

  const start = () => {
    if (!isTargetPage()) return;

    repairEmailFields();

    const observer = new MutationObserver(() => {
      window.requestAnimationFrame(repairEmailFields);
    });
    observer.observe(document.body, { childList: true, subtree: true });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
