/*
 * Progressive enhancement for customer phone inputs.
 *
 * /account/details keeps EasyStore's established national-number + ISO
 * country_code contract. The phone-only authentication screens do not expose a
 * separate country field, so foreign selections are combined into an explicit
 * +<dial code><subscriber> value immediately before submit. Singapore remains
 * the default and keeps its existing local-number submit shape for compatibility
 * with current customer identities.
 *
 * The country list deliberately matches scripts/easystore_hubspot_sync.py. An
 * Other option accepts a numeric calling code so countries outside that shared
 * table still work without asking a numeric-only phone field to accept '+'.
 */
(() => {
  'use strict';

  if (window.__ccAccountPhoneInputLoaded) return;
  window.__ccAccountPhoneInputLoaded = true;

  const COUNTRIES = [
    { iso: 'SG', dial: '65', label: 'SG +65' },
    { iso: 'MY', dial: '60', label: 'MY +60' },
    { iso: 'ID', dial: '62', label: 'ID +62' },
    { iso: 'PH', dial: '63', label: 'PH +63' },
    { iso: 'TH', dial: '66', label: 'TH +66' },
    { iso: 'VN', dial: '84', label: 'VN +84' },
    { iso: 'HK', dial: '852', label: 'HK +852' },
    { iso: 'CN', dial: '86', label: 'CN +86' },
    { iso: 'TW', dial: '886', label: 'TW +886' },
    { iso: 'JP', dial: '81', label: 'JP +81' },
    { iso: 'KR', dial: '82', label: 'KR +82' },
    { iso: 'IN', dial: '91', label: 'IN +91' },
    { iso: 'AU', dial: '61', label: 'AU +61' },
    { iso: 'NZ', dial: '64', label: 'NZ +64' },
    { iso: 'GB', dial: '44', label: 'GB +44' },
    { iso: 'US', dial: '1', label: 'US +1' },
    { iso: 'CA', dial: '1', label: 'CA +1' },
  ];

  const AUTH_PHONE_SELECTORS = [
    '#RegisterForm-EmailOrPhone',
    '#CustomerEmail',
    '#RecoverEmail',
  ];
  const DROP_DOMESTIC_ZERO = new Set([
    'MY', 'ID', 'PH', 'TH', 'VN', 'TW', 'JP', 'KR', 'IN', 'AU', 'NZ', 'GB',
  ]);
  const PHONE_MIN_DIGITS = 7;
  const PHONE_MAX_DIGITS = 15;
  const AUTH_COUNTRY_KEY = 'cc:auth-phone-country';
  const AUTH_DIAL_KEY = 'cc:auth-phone-dial';
  const PHONE_MESSAGE = 'Please enter a valid phone number with 7 to 15 digits.';
  const DIAL_MESSAGE = 'Please enter a valid country calling code.';
  const STYLE_ID = 'AccountPhoneInputStyles';

  const byIso = (iso) => COUNTRIES.find((country) => country.iso === String(iso || '').toUpperCase()) || null;
  const digitsOnly = (value) => String(value || '').replace(/\D/g, '');
  const isInternational = (value) => /^\s*(?:\+|00)/.test(String(value || ''));

  const internationalDigits = (value) => {
    const text = String(value || '').trim();
    if (text.indexOf('+') === 0) return digitsOnly(text.slice(1));
    if (text.indexOf('00') === 0) return digitsOnly(text.slice(2));
    return '';
  };

  const stripDomesticZero = (iso, value) => {
    const digits = digitsOnly(value);
    if (DROP_DOMESTIC_ZERO.has(String(iso || '').toUpperCase()) && digits.charAt(0) === '0') {
      return digits.slice(1);
    }
    return digits;
  };

  const countryMatchesForInternational = (value) => {
    const digits = internationalDigits(value);
    if (!digits) return [];

    let longest = 0;
    COUNTRIES.forEach((country) => {
      if (digits.indexOf(country.dial) === 0) longest = Math.max(longest, country.dial.length);
    });
    if (!longest) return [];
    return COUNTRIES.filter((country) => (
      country.dial.length === longest && digits.indexOf(country.dial) === 0
    ));
  };

  const readPreference = (key) => {
    try {
      return window.sessionStorage.getItem(key) || '';
    } catch (_error) {
      return '';
    }
  };

  const rememberPreference = (iso, dial) => {
    try {
      window.sessionStorage.setItem(AUTH_COUNTRY_KEY, iso || '');
      window.sessionStorage.setItem(AUTH_DIAL_KEY, digitsOnly(dial).slice(0, 3));
    } catch (_error) {
      /* preference is optional */
    }
  };

  const ensureStyles = () => {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = [
      '.account-phone-input {',
      '  display: grid;',
      '  grid-template-columns: minmax(12rem, 14rem) minmax(0, 1fr);',
      '  gap: 1rem;',
      '  align-items: start;',
      '}',
      '.account-phone-input--other {',
      '  grid-template-columns: minmax(12rem, 14rem) minmax(8rem, 10rem) minmax(0, 1fr);',
      '}',
      '.account-phone-input > .field {',
      '  margin-top: 0;',
      '  margin-bottom: 0;',
      '}',
      '.account-phone-input__country select,',
      '.account-phone-input__dial input {',
      '  width: 100%;',
      '}',
      '.account-phone-input__hint {',
      '  grid-column: 1 / -1;',
      '  margin: 0.4rem 0 0;',
      '  font-size: 1.2rem;',
      '  line-height: 1.4;',
      '}',
      '@media screen and (max-width: 560px) {',
      '  .account-phone-input,',
      '  .account-phone-input--other {',
      '    grid-template-columns: minmax(10.5rem, 1fr) minmax(8rem, 1fr);',
      '    gap: 0.8rem;',
      '  }',
      '  .account-phone-input:not(.account-phone-input--other) .account-phone-input__number {',
      '    grid-column: 2;',
      '  }',
      '  .account-phone-input--other .account-phone-input__number {',
      '    grid-column: 1 / -1;',
      '  }',
      '}',
    ].join('\n');
    document.head.appendChild(style);
  };

  const createCountrySelect = (phone) => {
    const countryField = document.createElement('div');
    countryField.className = 'field on_focus account-phone-input__country';

    const selectWrapper = document.createElement('div');
    selectWrapper.className = 'select';

    const select = document.createElement('select');
    select.id = phone.id + 'CountryCode';
    select.setAttribute('data-phone-country-select', '');
    select.setAttribute('aria-label', 'Country code');

    COUNTRIES.forEach((country) => {
      const option = document.createElement('option');
      option.value = country.iso;
      option.textContent = country.label;
      select.appendChild(option);
    });

    const other = document.createElement('option');
    other.value = '';
    other.textContent = 'Other';
    select.appendChild(other);

    const label = document.createElement('label');
    label.setAttribute('for', select.id);
    label.textContent = 'Country code';

    selectWrapper.appendChild(select);
    countryField.appendChild(selectWrapper);
    countryField.appendChild(label);
    return { countryField, select };
  };

  const createDialField = (phone) => {
    const field = document.createElement('div');
    field.className = 'field account-phone-input__dial';
    field.hidden = true;

    const input = document.createElement('input');
    input.type = 'tel';
    input.id = phone.id + 'DialCode';
    input.inputMode = 'numeric';
    input.autocomplete = 'off';
    input.maxLength = 3;
    input.placeholder = '+ code';
    input.setAttribute('aria-label', 'Country calling code');

    const label = document.createElement('label');
    label.setAttribute('for', input.id);
    label.textContent = '+ code';

    field.appendChild(input);
    field.appendChild(label);
    return { dialField: field, dialInput: input };
  };

  const buildComponent = (phone, initialIso, initialDial) => {
    const phoneField = phone.closest && phone.closest('.field');
    if (!phoneField || !phoneField.parentNode) return null;

    const existing = phone.closest('.account-phone-input');
    if (existing) {
      return {
        wrapper: existing,
        select: existing.querySelector('[data-phone-country-select]'),
        dialField: existing.querySelector('.account-phone-input__dial'),
        dialInput: existing.querySelector('.account-phone-input__dial input'),
        hint: existing.querySelector('.account-phone-input__hint'),
      };
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'account-phone-input';
    const country = createCountrySelect(phone);
    const dial = createDialField(phone);

    const hint = document.createElement('small');
    hint.className = 'account-phone-input__hint';
    hint.id = phone.id + 'InternationalHint';
    hint.hidden = true;
    hint.textContent = 'For Other, enter the country calling code and the local number without a domestic leading 0.';

    const parent = phoneField.parentNode;
    parent.insertBefore(wrapper, phoneField);
    wrapper.appendChild(country.countryField);
    wrapper.appendChild(dial.dialField);
    wrapper.appendChild(phoneField);
    wrapper.appendChild(hint);
    phoneField.classList.add('account-phone-input__number');

    country.select.value = byIso(initialIso) ? String(initialIso).toUpperCase() : '';
    dial.dialInput.value = digitsOnly(initialDial).slice(0, 3);

    return {
      wrapper,
      select: country.select,
      dialField: dial.dialField,
      dialInput: dial.dialInput,
      hint,
    };
  };

  const syncOtherUi = (component, phone) => {
    const isOther = !component.select.value;
    component.wrapper.classList.toggle('account-phone-input--other', isOther);
    component.dialField.hidden = !isOther;
    component.hint.hidden = !isOther;
    if (isOther) phone.setAttribute('aria-describedby', component.hint.id);
    else phone.removeAttribute('aria-describedby');
    if (!isOther) component.dialInput.setCustomValidity('');
  };

  const prepareInternationalValue = (country, dial, local) => {
    const national = country ? stripDomesticZero(country.iso, local) : digitsOnly(local);
    return '+' + digitsOnly(dial) + national;
  };

  const validateComponent = (phone, component) => {
    const local = digitsOnly(phone.value);
    if (!local) {
      phone.setCustomValidity('');
      component.dialInput.setCustomValidity('');
      return true;
    }

    const country = byIso(component.select.value);
    const dial = country ? country.dial : digitsOnly(component.dialInput.value);
    if (!country && (dial.length < 1 || dial.length > 3)) {
      component.dialInput.setCustomValidity(DIAL_MESSAGE);
      phone.setCustomValidity('');
      return false;
    }
    component.dialInput.setCustomValidity('');

    const national = country ? stripDomesticZero(country.iso, local) : local;
    const totalDigits = dial.length + national.length;
    if (totalDigits < PHONE_MIN_DIGITS || totalDigits > PHONE_MAX_DIGITS) {
      phone.setCustomValidity(PHONE_MESSAGE);
      return false;
    }

    phone.setCustomValidity('');
    return true;
  };

  const inferFromInternational = (phone, component, hiddenCountry) => {
    if (!isInternational(phone.value)) return false;

    const raw = internationalDigits(phone.value);
    const matches = countryMatchesForInternational(phone.value);
    if (matches.length === 1) {
      const country = matches[0];
      component.select.value = country.iso;
      component.dialInput.value = country.dial;
      phone.value = raw.slice(country.dial.length);
      if (hiddenCountry) hiddenCountry.value = country.iso;
      syncOtherUi(component, phone);
      return true;
    }

    component.select.value = '';
    if (matches.length > 1) {
      // +1 is shared by the US and Canada. Keep the calling code without guessing ISO.
      component.dialInput.value = matches[0].dial;
      phone.value = raw.slice(matches[0].dial.length);
    } else {
      const guessedDialLength = Math.min(3, Math.max(1, raw.length - PHONE_MIN_DIGITS));
      component.dialInput.value = raw.slice(0, guessedDialLength);
      phone.value = raw.slice(guessedDialLength);
    }
    if (hiddenCountry) hiddenCountry.value = '';
    syncOtherUi(component, phone);
    return true;
  };

  const attachCommonListeners = (phone, component, hiddenCountry, isAuth) => {
    const update = () => {
      if (isAuth) {
        const numeric = digitsOnly(phone.value);
        if (phone.value !== numeric) phone.value = numeric;
      }
      const country = byIso(component.select.value);
      if (country) component.dialInput.value = country.dial;
      if (hiddenCountry) hiddenCountry.value = country ? country.iso : '';
      syncOtherUi(component, phone);
      validateComponent(phone, component);
      if (isAuth) rememberPreference(component.select.value, component.dialInput.value);
    };

    component.select.addEventListener('change', update);
    component.dialInput.addEventListener('input', () => {
      const numeric = digitsOnly(component.dialInput.value).slice(0, 3);
      if (component.dialInput.value !== numeric) component.dialInput.value = numeric;
      update();
    });
    phone.addEventListener('input', update);
    phone.addEventListener('change', update);
    phone.addEventListener('blur', update);

    return update;
  };

  const interceptSubmit = (phone, component, hiddenCountry, isAuth) => {
    const form = phone.form;
    if (!form || form.dataset.accountPhoneSubmitEnhanced === 'true') return;
    form.dataset.accountPhoneSubmitEnhanced = 'true';

    document.addEventListener('submit', (event) => {
      if (event.target !== form || event.defaultPrevented) return;
      if (!validateComponent(phone, component)) {
        event.preventDefault();
        event.stopPropagation();
        const target = component.dialInput.validationMessage ? component.dialInput : phone;
        if (target.reportValidity) target.reportValidity();
        if (target.focus) target.focus();
        return;
      }
      if (form.checkValidity && !form.checkValidity()) return;

      const country = byIso(component.select.value);
      const local = digitsOnly(phone.value);
      if (!local) return;

      if (isAuth) {
        if (country && country.iso === 'SG') {
          // Preserve the store's current Singapore login/signup identity shape.
          phone.value = local;
          return;
        }
        const dial = country ? country.dial : component.dialInput.value;
        phone.value = prepareInternationalValue(country, dial, local);
        return;
      }

      if (country) {
        phone.value = stripDomesticZero(country.iso, local);
        hiddenCountry.value = country.iso;
      } else {
        phone.value = prepareInternationalValue(null, component.dialInput.value, local);
        hiddenCountry.value = '';
      }
    }, true);
  };

  const enhanceDetailsPhone = (hiddenCountry) => {
    if (!hiddenCountry || hiddenCountry.dataset.phoneCountryEnhanced === 'true') return;
    const phoneId = hiddenCountry.getAttribute('data-phone-input-id') || 'DetailPhone';
    const phone = document.getElementById(phoneId);
    if (!phone) return;

    hiddenCountry.dataset.phoneCountryEnhanced = 'true';
    phone.setAttribute('type', 'tel');
    phone.setAttribute('inputmode', 'tel');
    phone.setAttribute('autocomplete', 'tel-national');

    const initialCountry = String(hiddenCountry.value || '').trim().toUpperCase();
    const component = buildComponent(phone, byIso(initialCountry) ? initialCountry : 'SG', '');
    if (!component) return;

    inferFromInternational(phone, component, hiddenCountry);
    attachCommonListeners(phone, component, hiddenCountry, false)();
    interceptSubmit(phone, component, hiddenCountry, false);
  };

  const authPhoneInputs = () => {
    const seen = new Set();
    const fields = [];
    AUTH_PHONE_SELECTORS.forEach((selector) => {
      document.querySelectorAll(selector).forEach((field) => {
        if (seen.has(field)) return;
        seen.add(field);
        fields.push(field);
      });
    });
    return fields;
  };

  const enhanceAuthPhone = (phone) => {
    if (!phone || phone.dataset.authPhoneEnhanced === 'true') return;
    const form = phone.form;
    if (!form) return;

    phone.dataset.authPhoneEnhanced = 'true';
    const originalInternational = isInternational(phone.value) ? String(phone.value) : '';
    phone.setAttribute('inputmode', 'numeric');
    phone.setAttribute('autocomplete', 'tel-national');
    phone.setAttribute('aria-label', 'Mobile number');
    phone.placeholder = 'Mobile number';
    if (phone.labels && phone.labels.length) phone.labels[0].textContent = 'Mobile number';

    const preferredIso = readPreference(AUTH_COUNTRY_KEY);
    const preferredDial = readPreference(AUTH_DIAL_KEY);
    const component = buildComponent(phone, byIso(preferredIso) ? preferredIso : 'SG', preferredDial);
    if (!component) return;

    if (originalInternational) inferFromInternational(phone, component, null);
    attachCommonListeners(phone, component, null, true)();
    interceptSubmit(phone, component, null, true);
  };

  const enhanceAll = () => {
    document.querySelectorAll('[data-phone-country-code]').forEach(enhanceDetailsPhone);
    authPhoneInputs().forEach(enhanceAuthPhone);
  };

  const start = () => {
    ensureStyles();
    enhanceAll();

    // Insert Code/app snippets may adjust the auth field after the theme parses.
    // Watch briefly so a replaced phone node still receives the same component.
    if (!window.MutationObserver) return;
    const observer = new MutationObserver(enhanceAll);
    observer.observe(document.documentElement, { childList: true, subtree: true });
    window.setTimeout(() => observer.disconnect(), 5000);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
