(() => {
  const storageKey = 'searchHistory';

  const readHistory = () => {
    try {
      const storedHistory = JSON.parse(localStorage.getItem(storageKey) || '[]');
      return Array.isArray(storedHistory) ? storedHistory : [];
    } catch (error) {
      try {
        localStorage.removeItem(storageKey);
      } catch (storageError) {
        // Storage can be disabled by the browser; search must still work.
      }
      return [];
    }
  };

  const normaliseHistory = (history) => history
    .map((item) => typeof item === 'string' ? { term: item } : item)
    .filter((item) => item && typeof item.term === 'string' && item.term.trim());

  const seedHistory = () => {
    if (!Array.isArray(window.CardboardSearchHistorySeed)) return;
    try {
      const seededHistory = normaliseHistory(window.CardboardSearchHistorySeed);
      if (seededHistory.length || localStorage.getItem(storageKey) === null) {
        localStorage.setItem(storageKey, JSON.stringify(seededHistory));
      }
    } catch (error) {
      // Search history is an enhancement, not a requirement for submitting.
    }
  };

  const clearHistory = async () => {
    try {
      localStorage.removeItem(storageKey);
    } catch (error) {
      // Continue with the optional account sync when storage is unavailable.
    }
    const config = window.searchHistoryConfig || {};
    if (!config.customer) return;

    try {
      await fetch('/account/search_histories', {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({ _token: config.csrfToken }),
      });
    } catch (error) {
      // Local history has still been cleared when the optional account sync fails.
    }
  };

  const initialiseForm = (form) => {
    const input = form.querySelector('[data-search-history-input]');
    const panel = form.querySelector('[data-search-history-panel]');
    const list = form.querySelector('[data-search-history-list]');
    const clearButton = form.querySelector('[data-search-history-clear]');
    const hiddenInput = form.querySelector('.hidden_search_history');
    if (!input || !panel || !list || !clearButton || !hiddenInput) return;

    let activeIndex = -1;
    let options = [];

    const closePanel = () => {
      panel.hidden = true;
      input.classList.remove('is-focus');
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
      document.body.classList.remove('search-input-focus');
      activeIndex = -1;
    };

    const setActiveOption = (index) => {
      if (!options.length) return;
      activeIndex = (index + options.length) % options.length;
      options.forEach((option, optionIndex) => {
        const isActive = optionIndex === activeIndex;
        option.classList.toggle('is-active', isActive);
        option.setAttribute('aria-selected', String(isActive));
      });
      input.setAttribute('aria-activedescendant', options[activeIndex].id);
      options[activeIndex].scrollIntoView({ block: 'nearest' });
    };

    const submitTerm = (term) => {
      input.value = term;
      closePanel();
      if (typeof form.requestSubmit === 'function') form.requestSubmit();
      else form.submit();
    };

    const renderPanel = () => {
      const history = normaliseHistory(readHistory());
      hiddenInput.value = JSON.stringify(history);
      list.replaceChildren();

      history.forEach((item, index) => {
        const option = document.createElement('button');
        option.type = 'button';
        option.className = 'search-history__option';
        option.id = `${list.id}-option-${index}`;
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', 'false');
        option.textContent = item.term;
        option.addEventListener('click', () => submitTerm(item.term));
        list.appendChild(option);
      });

      options = Array.from(list.querySelectorAll('[role="option"]'));
      clearButton.hidden = options.length === 0;
      if (!options.length) {
        closePanel();
        return;
      }

      panel.hidden = false;
      input.classList.add('is-focus');
      input.setAttribute('aria-expanded', 'true');
      document.body.classList.add('search-input-focus');
    };

    input.addEventListener('focus', renderPanel);
    input.addEventListener('input', closePanel);
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        closePanel();
        return;
      }
      if (panel.hidden || !options.length) return;
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setActiveOption(activeIndex + 1);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        setActiveOption(activeIndex - 1);
      } else if (event.key === 'Enter' && activeIndex >= 0) {
        event.preventDefault();
        options[activeIndex].click();
      }
    });

    clearButton.addEventListener('click', async () => {
      await clearHistory();
      hiddenInput.value = '[]';
      closePanel();
      input.focus();
    });

    document.addEventListener('pointerdown', (event) => {
      if (!form.contains(event.target)) closePanel();
    });
  };

  seedHistory();
  document.querySelectorAll('[data-search-history-form]').forEach(initialiseForm);
})();

(() => {
  const DEFAULT_BIRTHDATE = new Date(2000, 0, 1);
  const GENDER_SELECTOR = [
    'select[name="customer[gender]"]',
    'select[name="details[gender]"]',
  ].join(',');
  const BIRTHDATE_SELECTOR = [
    'input[name="customer[birthdate]"]',
    'input[name="details[birthdate]"]',
  ].join(',');
  // Deliberately no verification-code handling here. The one-time-code step at
  // /account/auth is EasyStore's, and the widget posts its own request; theme
  // scripts that wrote into those cells made it post twice, which broke signup
  // with "Customer already exists (phone)". This module stays on gender and
  // birthdate. See tests/test_otp_cell_autofill.py.

  const injectStyles = () => {
    if (document.getElementById('customer-form-enhancements-styles')) return;

    const style = document.createElement('style');
    style.id = 'customer-form-enhancements-styles';
    style.textContent = `
      .customer-gender-options {
        border: 0;
        margin: 0 0 2rem;
        min-inline-size: 0;
        padding: 0;
        width: 100%;
      }

      .customer-gender-options__legend {
        display: block;
        margin-bottom: 0.8rem;
        padding: 0;
        width: 100%;
      }

      .customer-gender-options__choices {
        display: flex;
        flex-wrap: wrap;
        gap: 0.8rem;
      }

      .customer-gender-options__choice {
        cursor: pointer;
        flex: 1 1 12rem;
        margin: 0;
        min-width: 0;
        position: relative;
      }

      .customer-gender-options__choice input {
        height: 1px;
        margin: -1px;
        opacity: 0;
        overflow: hidden;
        position: absolute;
        width: 1px;
      }

      .customer-gender-options__choice span {
        align-items: center;
        border: 0.1rem solid rgba(var(--color-base-text), 0.35);
        border-radius: 0.4rem;
        display: flex;
        justify-content: center;
        min-height: 4.6rem;
        padding: 0.8rem 1.2rem;
        text-align: center;
        transition: border-color 120ms ease, box-shadow 120ms ease;
      }

      .customer-gender-options__choice input:checked + span {
        border-color: rgb(var(--color-base-text));
        box-shadow: inset 0 0 0 0.1rem rgb(var(--color-base-text));
        font-weight: 600;
      }

      .customer-gender-options__choice input:focus-visible + span {
        outline: 0.2rem solid currentColor;
        outline-offset: 0.2rem;
      }
    `;
    document.head.appendChild(style);
  };

  const findAssociatedLabel = (input) => {
    if (!input.id) return null;
    return Array.from(document.querySelectorAll('label[for]'))
      .find((label) => label.htmlFor === input.id) || null;
  };

  const enhanceGenderSelect = (select) => {
    if (!select || select.dataset.customerGenderEnhanced === 'true') return;

    const choices = Array.from(select.options)
      .filter((option) => option.value && !option.disabled);
    if (!choices.length) return;

    injectStyles();

    const associatedLabel = findAssociatedLabel(select);
    const placeholder = Array.from(select.options)
      .find((option) => !option.value);
    const legendText = (associatedLabel && associatedLabel.textContent.trim())
      || (placeholder && placeholder.textContent.trim())
      || 'Gender';
    const baseId = select.id || `CustomerGender-${Math.random().toString(36).slice(2)}`;
    const fieldset = document.createElement('fieldset');
    const legend = document.createElement('legend');
    const choicesWrapper = document.createElement('div');

    fieldset.className = 'customer-gender-options';
    fieldset.dataset.customerGenderEnhanced = 'true';
    legend.className = 'customer-gender-options__legend';
    legend.textContent = legendText;
    choicesWrapper.className = 'customer-gender-options__choices';

    choices.forEach((option, index) => {
      const label = document.createElement('label');
      const radio = document.createElement('input');
      const text = document.createElement('span');

      label.className = 'customer-gender-options__choice';
      radio.type = 'radio';
      radio.name = select.name;
      radio.id = `${baseId}-${index + 1}`;
      radio.value = option.value;
      radio.checked = option.selected;
      radio.required = select.required;
      radio.disabled = select.disabled || option.disabled;
      if (select.form && select.getAttribute('form')) {
        radio.setAttribute('form', select.getAttribute('form'));
      }
      text.textContent = option.textContent;

      label.append(radio, text);
      choicesWrapper.appendChild(label);
    });

    fieldset.append(legend, choicesWrapper);

    const selectContainer = select.closest('.select');
    if (selectContainer) selectContainer.replaceWith(fieldset);
    else select.replaceWith(fieldset);

    if (associatedLabel && !fieldset.contains(associatedLabel)) associatedLabel.remove();
  };

  const configureBirthdatePicker = (input) => {
    const picker = input && input._flatpickr;
    if (!picker || picker.__customerBirthdateEnhanced) return false;

    picker.config.allowInput = true;
    picker.config.onOpen = [(_selectedDates, dateStr, instance) => {
      if (!dateStr && !instance.selectedDates.length) {
        instance.jumpToDate(DEFAULT_BIRTHDATE, false);
      }
    }];
    picker.__customerBirthdateEnhanced = true;
    return true;
  };

  const enhanceBirthdateInput = (input) => {
    if (!input || input.dataset.customerBirthdateEnhanced === 'true') return;

    input.dataset.customerBirthdateEnhanced = 'true';
    input.setAttribute('autocomplete', 'bday');

    if (configureBirthdatePicker(input)) return;

    requestAnimationFrame(() => configureBirthdatePicker(input));
    window.setTimeout(() => configureBirthdatePicker(input), 250);
  };

  const enhanceWithin = (root) => {
    if (!root || !root.querySelectorAll) return;

    if (root.matches && root.matches(GENDER_SELECTOR)) enhanceGenderSelect(root);
    root.querySelectorAll(GENDER_SELECTOR).forEach(enhanceGenderSelect);

    if (root.matches && root.matches(BIRTHDATE_SELECTOR)) enhanceBirthdateInput(root);
    root.querySelectorAll(BIRTHDATE_SELECTOR).forEach(enhanceBirthdateInput);
  };

  enhanceWithin(document);

  const observer = new MutationObserver((records) => {
    records.forEach((record) => {
      record.addedNodes.forEach((node) => {
        if (node.nodeType === Node.ELEMENT_NODE) enhanceWithin(node);
      });
    });
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
})();
