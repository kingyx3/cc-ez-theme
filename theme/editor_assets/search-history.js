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
