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
    // Every rule is qualified by element + class. The account templates wrap
    // their controls in `.customer .field`, whose `label` and `input` rules
    // (specificity 0,2,1) would otherwise absolutely position these options on
    // top of each other and set pointer-events: none, leaving the control
    // invisible and untappable. The widget also replaces that wrapper outright
    // (see enhanceGenderSelect), so these two defences are independent.
    style.textContent = `
      fieldset.customer-gender-options {
        border: 0;
        margin: 0 0 1.6rem;
        min-inline-size: 0;
        padding: 0;
        width: 100%;
      }

      fieldset.customer-gender-options > legend.customer-gender-options__legend {
        color: rgba(var(--color-foreground), 0.55);
        display: block;
        float: left;
        font-size: 1.2rem;
        letter-spacing: 0.04rem;
        line-height: 1.5;
        margin: 0 0 0.6rem;
        padding: 0;
        pointer-events: auto;
        position: static;
        width: 100%;
      }

      fieldset.customer-gender-options > div.customer-gender-options__choices {
        clear: both;
        display: grid;
        gap: 0.8rem;
        /* auto-fit keeps every option on one row whenever they fit, and wraps
           to a second row rather than shrinking them into unreadable slivers.
           6rem is the narrowest column that still holds the longest label this
           store uses without breaking it. */
        grid-template-columns: repeat(auto-fit, minmax(6rem, 1fr));
      }

      /* Two options - the case every storefront here actually renders - are
         pinned to one row at any width, so the choice always reads as a single
         control rather than a stack of buttons. Three or more are left to
         auto-fit: forcing them inline on a 320px screen crams the labels.
         Specificity has to clear the rule above, hence the fieldset prefix. */
      fieldset.customer-gender-options > div.customer-gender-options__choices[data-choice-count="2"] {
        grid-template-columns: repeat(2, 1fr);
      }

      div.customer-gender-options__choices > label.customer-gender-options__choice {
        color: inherit;
        container-type: inline-size;
        cursor: pointer;
        display: block;
        font-size: inherit;
        left: auto;
        letter-spacing: inherit;
        margin: 0;
        min-width: 0;
        pointer-events: auto;
        position: relative;
        top: auto;
        width: auto;
      }

      label.customer-gender-options__choice > input {
        height: 1px;
        margin: -1px;
        opacity: 0;
        overflow: hidden;
        padding: 0;
        position: absolute;
        width: 1px;
      }

      /* Radius, ring, height and type are the theme's own text-input tokens, so
         the control lines up with the fields above and below it rather than
         introducing a second look. */
      label.customer-gender-options__choice > span {
        align-items: center;
        background-color: transparent;
        border: 0;
        border-radius: 3.5rem;
        box-shadow: 0 0 0 0.1rem rgba(var(--color-foreground), 1), inset 0 2px 3px rgba(0, 0, 0, 0.05);
        box-sizing: border-box;
        color: rgb(var(--color-foreground));
        display: flex;
        font-size: 1.5rem;
        justify-content: center;
        letter-spacing: 0.04rem;
        line-height: 1.3;
        /* Matches the 4rem text inputs, and clears the 44px touch minimum. */
        min-height: 4rem;
        /* Narrow columns get tighter side padding so the label keeps its room. */
        padding: 0.6rem clamp(0.6rem, 2.5cqi, 1.2rem);
        overflow-wrap: anywhere;
        text-align: center;
        transition: background-color var(--duration-short) ease, color var(--duration-short) ease;
        user-select: none;
      }

      label.customer-gender-options__choice > input:checked + span {
        background-color: rgb(var(--color-foreground));
        color: rgb(var(--color-background));
      }

      label.customer-gender-options__choice > input:focus-visible + span {
        outline: 0.2rem solid rgb(var(--color-foreground));
        outline-offset: 0.2rem;
      }

      label.customer-gender-options__choice > input:disabled + span {
        cursor: not-allowed;
        opacity: 0.5;
      }

      @media (hover: hover) {
        label.customer-gender-options__choice > input:not(:checked):hover + span {
          background-color: rgba(var(--color-foreground), 0.06);
        }
      }

      @media (prefers-reduced-motion: reduce) {
        label.customer-gender-options__choice > span {
          transition: none;
        }
      }
    `;
    document.head.appendChild(style);
  };

  const findAssociatedLabel = (input) => {
    if (!input.id) return null;
    return Array.from(document.querySelectorAll('label[for]'))
      .find((label) => label.htmlFor === input.id) || null;
  };

  // Swap out the whole `.field` wrapper where it is safe to do so. `.customer
  // .field` styles its `label` and `input` children as a floating-label text
  // input - absolutely positioned, pointer-events: none - which is wrong for a
  // group of radio options and outranks anything this module can inject.
  // Only the wrapper for this one control is taken, never one holding other
  // fields.
  const replaceGenderControl = (select, fieldset) => {
    const field = select.closest('.field');
    const ownsNothingElse = field
      && field.querySelectorAll('input, select, textarea').length === 1;

    const target = (ownsNothingElse && field) || select.closest('.select') || select;
    target.replaceWith(fieldset);
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
    // Drives the single-row layout for the two and three option cases.
    choicesWrapper.dataset.choiceCount = String(choices.length);

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

    replaceGenderControl(select, fieldset);

    if (associatedLabel && associatedLabel.isConnected) associatedLabel.remove();
  };

  // On a phone a typeable date field raises the keyboard straight over the
  // calendar, so typing is offered only where there is a real pointer.
  const pointerIsCoarse = () => typeof window.matchMedia === 'function'
    && window.matchMedia('(pointer: coarse)').matches;

  const configureBirthdatePicker = (input) => {
    const picker = input && input._flatpickr;
    if (!picker || picker.__customerBirthdateEnhanced) return false;

    const allowTyping = !pointerIsCoarse();
    picker.config.allowInput = allowTyping;
    // flatpickr only reads allowInput while it builds, and sets readonly from
    // it there, so the attribute has to be corrected by hand afterwards.
    if (allowTyping) input.removeAttribute('readonly');
    else input.setAttribute('readonly', 'readonly');

    // A birthdate is decades back; opening on the current month means a long
    // scroll. Empty fields start at January 2000 instead.
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
