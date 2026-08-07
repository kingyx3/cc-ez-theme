(() => {
  const CHECKOUT_PATH = /\/checkouts?(?:\/|$)/i;
  const FALLBACK_LABEL = 'Email';
  let generatedId = 0;
  let repairQueued = false;

  const isCheckout = () => CHECKOUT_PATH.test(window.location.pathname);

  const isEmailInput = (input) => {
    const type = (input.getAttribute('type') || '').toLowerCase();
    const autocomplete = (input.getAttribute('autocomplete') || '').toLowerCase();
    const name = (input.getAttribute('name') || '').toLowerCase();
    const id = (input.id || '').toLowerCase();

    return type === 'email' || autocomplete === 'email' || name.includes('email') || id.includes('email');
  };

  const isUsableInput = (input) => {
    if (!input || input.disabled || (input.getAttribute('type') || '').toLowerCase() === 'hidden') return false;
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

  const keepLabelVisible = (label) => {
    if (!label) return;

    label.hidden = false;
    label.removeAttribute('hidden');
    label.removeAttribute('aria-hidden');
    label.classList.remove('label--hidden', 'visually-hidden', 'hidden', 'hide');

    label.style.removeProperty('display');
    label.style.removeProperty('visibility');
    label.style.removeProperty('opacity');

    const style = window.getComputedStyle(label);
    if (style.display === 'none') label.style.setProperty('display', 'block', 'important');
    if (style.visibility === 'hidden') label.style.setProperty('visibility', 'visible', 'important');
    if (style.opacity === '0') label.style.setProperty('opacity', '1', 'important');
  };

  const ensureEmailLabel = (input) => {
    if (!isUsableInput(input)) return;

    if (!input.id) {
      generatedId += 1;
      input.id = `EmailField-${generatedId}`;
    }

    let label = findAssociatedLabel(input);
    const text = labelTextFor(input, label);

    if (!label) {
      label = document.createElement('label');
      label.className = 'field__label';
      label.htmlFor = input.id;
      input.insertAdjacentElement('afterend', label);
    }

    if (!label.textContent.trim()) label.textContent = text;
    keepLabelVisible(label);

    const field = input.closest('.field');
    if (field) field.classList.add('on_focus');

    if (!input.getAttribute('aria-label')) input.setAttribute('aria-label', text);
    input.classList.remove('no-float-label');
    if (!(input.getAttribute('placeholder') || '').trim()) input.setAttribute('placeholder', text);
  };

  const repairAccountEmailField = () => {
    const input = document.getElementById('DetailEmail');
    if (input) ensureEmailLabel(input);
  };

  const repairCheckoutEmailFields = () => {
    if (!isCheckout()) return;

    document.querySelectorAll('input').forEach((input) => {
      if (isEmailInput(input)) ensureEmailLabel(input);
    });
  };

  const repairEmailFields = () => {
    repairAccountEmailField();
    repairCheckoutEmailFields();
  };

  const queueRepair = () => {
    if (repairQueued) return;
    repairQueued = true;
    window.requestAnimationFrame(() => {
      repairQueued = false;
      repairEmailFields();
    });
  };

  const start = () => {
    repairEmailFields();

    if (!document.body) return;

    const observer = new MutationObserver(queueRepair);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      characterData: true,
      attributeFilter: ['class', 'style', 'hidden', 'aria-hidden'],
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
