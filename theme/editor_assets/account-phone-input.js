/*
 * Progressive enhancement for /account/details phone inputs only.
 *
 * Authentication is intentionally out of scope. EasyStore owns the
 * login/register/recovery/activation identity field, and this repository has
 * previously seen duplicate-account failures when theme code wrote into that
 * field. The Insert Code mobile-only helper remains the sole auth-field owner.
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

  const PHONE_MIN_DIGITS = 7;
  const PHONE_MAX_DIGITS = 15;
  const PHONE_MESSAGE = 'Please enter a valid phone number with 7 to 15 digits.';
  const DIAL_MESSAGE = 'Please enter a valid country calling code.';
  const STYLE_ID = 'AccountPhoneInputStyles';
  let generatedId = 0;

  const byIso = (iso) => COUNTRIES.find(
    (country) => country.iso === String(iso || '').toUpperCase()
  ) || null;
  const digitsOnly = (value) => String(value || '').replace(/\D/g, '');
  const isInternational = (value) => /^\s*(?:\+|00)/.test(String(value || ''));

  const internationalDigits = (value) => {
    const text = String(value || '').trim();
    if (text.indexOf('+') === 0) return digitsOnly(text.slice(1));
    if (text.indexOf('00') === 0) return digitsOnly(text.slice(2));
    return '';
  };

  const validInternational = (value) => {
    const digits = internationalDigits(value);
    return digits.length >= PHONE_MIN_DIGITS &&
      digits.length <= PHONE_MAX_DIGITS &&
      digits.charAt(0) !== '0';
  };

  const countryMatchesForInternational = (value) => {
    const digits = internationalDigits(value);
    if (!digits) return [];
    let longest = 0;
    COUNTRIES.forEach((country) => {
      if (digits.indexOf(country.dial) === 0) longest = Math.max(longest, country.dial.length);
    });
    if (!longest) return [];
    return COUNTRIES.filter(
      (country) => country.dial.length === longest && digits.indexOf(country.dial) === 0
    );
  };

  const ensureStyles = () => {
    if (!document.head || document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = [
      '.account-phone-input { display:grid; grid-template-columns:minmax(11rem,14rem) minmax(0,1fr); gap:1rem; align-items:center; width:100%; }',
      '.account-phone-input--other { grid-template-columns:minmax(11rem,14rem) minmax(8rem,10rem) minmax(0,1fr); }',
      '.account-phone-input > .field { margin:0!important; padding:0!important; align-self:center; }',
      '.account-phone-input__country .select { display:block; height:4rem!important; min-height:4rem!important; margin:0!important; }',
      '.account-phone-input__country select, .account-phone-input__dial input, .account-phone-input__number input { width:100%; box-sizing:border-box; }',
      '.account-phone-input__country select, .account-phone-input__number input { display:block!important; height:4rem!important; min-height:4rem!important; margin:0!important; border:0!important; border-radius:3.5rem!important; box-shadow:0 0 0 .1rem rgba(var(--color-foreground),1), inset 0 2px 3px rgba(0,0,0,.05)!important; position:relative!important; top:0!important; transform:none!important; }',
      '.account-phone-input__country select { background:transparent; color:inherit; font:inherit; padding:1.4rem 4rem 0 2rem!important; }',
      '.account-phone-input__number { height:4rem!important; min-height:4rem!important; }',
      '.account-phone-input__dial input { height:4rem!important; min-height:4rem!important; margin:0!important; }',
      '.account-phone-input--locked .account-phone-input__country select, .account-phone-input--locked .account-phone-input__number input { background:rgba(0,0,0,.045)!important; cursor:not-allowed; }',
      '.account-phone-input__hint { grid-column:1 / -1; margin:.4rem 0 0; font-size:1.2rem; line-height:1.4; }',
      '@media screen and (max-width:560px) {',
      '  .account-phone-input, .account-phone-input--other { grid-template-columns:minmax(9.5rem,11rem) minmax(0,1fr); gap:.8rem; }',
      '  .account-phone-input--other .account-phone-input__number { grid-column:1 / -1; }',
      '}',
    ].join('\n');
    document.head.appendChild(style);
  };

  const ensurePhoneId = (phone) => {
    if (phone.id) return phone.id;
    generatedId += 1;
    phone.id = 'AccountPhoneInput' + generatedId;
    return phone.id;
  };

  const createCountrySelect = (phone) => {
    const countryField = document.createElement('div');
    countryField.className = 'field on_focus account-phone-input__country';
    const selectWrapper = document.createElement('div');
    selectWrapper.className = 'select';
    const select = document.createElement('select');
    select.id = ensurePhoneId(phone) + 'CountryCode';
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
    input.id = ensurePhoneId(phone) + 'DialCode';
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

  const buildComponent = (phone, initialIso) => {
    const phoneContainer = phone.closest && phone.closest('.field');
    if (!phoneContainer || !phoneContainer.parentNode) return null;
    phoneContainer.classList.add('account-phone-input__number');

    ensureStyles();
    const wrapper = document.createElement('div');
    wrapper.className = 'account-phone-input';
    const country = createCountrySelect(phone);
    const dial = createDialField(phone);
    const hint = document.createElement('small');
    hint.className = 'account-phone-input__hint';
    hint.id = ensurePhoneId(phone) + 'InternationalHint';
    hint.hidden = true;
    hint.textContent = 'For Other, enter a full international number or a country calling code plus the local number.';

    phoneContainer.parentNode.insertBefore(wrapper, phoneContainer);
    wrapper.appendChild(country.countryField);
    wrapper.appendChild(dial.dialField);
    wrapper.appendChild(phoneContainer);
    wrapper.appendChild(hint);
    country.select.value = byIso(initialIso) ? String(initialIso).toUpperCase() : '';
    return { wrapper, select: country.select, dialField: dial.dialField, dialInput: dial.dialInput, hint };
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

  const useCountry = (phone, component, hiddenCountry, country, raw) => {
    component.select.value = country.iso;
    component.dialInput.value = country.dial;
    phone.value = raw.slice(country.dial.length);
    hiddenCountry.value = country.iso;
    syncOtherUi(component, phone);
  };

  const inferFromInternational = (phone, component, hiddenCountry) => {
    if (!isInternational(phone.value)) return false;
    const raw = internationalDigits(phone.value);
    if (!raw) return false;

    const storedCountry = byIso(hiddenCountry.value);
    if (storedCountry && raw.indexOf(storedCountry.dial) === 0) {
      useCountry(phone, component, hiddenCountry, storedCountry, raw);
      return true;
    }

    const matches = countryMatchesForInternational(phone.value);
    if (matches.length === 1) {
      useCountry(phone, component, hiddenCountry, matches[0], raw);
      return true;
    }

    component.select.value = '';
    hiddenCountry.value = '';
    if (matches.length > 1) {
      component.dialInput.value = matches[0].dial;
      phone.value = raw.slice(matches[0].dial.length);
    } else {
      component.dialInput.value = '';
      phone.value = '+' + raw;
    }
    syncOtherUi(component, phone);
    return true;
  };

  const validateComponent = (phone, component) => {
    const country = byIso(component.select.value);
    if (!country && isInternational(phone.value)) {
      const valid = validInternational(phone.value);
      phone.setCustomValidity(valid ? '' : PHONE_MESSAGE);
      component.dialInput.setCustomValidity('');
      return valid;
    }

    const local = digitsOnly(phone.value);
    if (!local) {
      phone.setCustomValidity('');
      component.dialInput.setCustomValidity('');
      return true;
    }

    const dial = country ? country.dial : digitsOnly(component.dialInput.value);
    if (!country && (dial.length < 1 || dial.length > 3 || dial.charAt(0) === '0')) {
      component.dialInput.setCustomValidity(DIAL_MESSAGE);
      phone.setCustomValidity('');
      return false;
    }
    component.dialInput.setCustomValidity('');

    const totalDigits = dial.length + local.length;
    if (totalDigits < PHONE_MIN_DIGITS || totalDigits > PHONE_MAX_DIGITS) {
      phone.setCustomValidity(PHONE_MESSAGE);
      return false;
    }
    phone.setCustomValidity('');
    return true;
  };

  const attachListeners = (phone, component, hiddenCountry, state) => {
    const update = () => {
      const country = byIso(component.select.value);
      if (country) component.dialInput.value = country.dial;
      hiddenCountry.value = country ? country.iso : '';
      syncOtherUi(component, phone);
      validateComponent(phone, component);
    };

    component.select.addEventListener('change', () => {
      state.dirty = true;
      update();
    });
    component.dialInput.addEventListener('input', () => {
      state.dirty = true;
      const numeric = digitsOnly(component.dialInput.value).slice(0, 3);
      if (component.dialInput.value !== numeric) component.dialInput.value = numeric;
      update();
    });
    phone.addEventListener('input', () => {
      state.dirty = true;
      if (isInternational(phone.value)) inferFromInternational(phone, component, hiddenCountry);
      update();
    });
    phone.addEventListener('change', update);
    phone.addEventListener('blur', update);
    update();
  };

  const interceptDetailsSubmit = (phone, component, hiddenCountry, state) => {
    const form = phone.form || (phone.closest && phone.closest('form'));
    if (!form || form.dataset.accountPhoneSubmitEnhanced === 'true') return;
    form.dataset.accountPhoneSubmitEnhanced = 'true';

    form.addEventListener('submit', (event) => {
      if (!state.dirty) return;
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
      if (country) {
        phone.value = digitsOnly(phone.value);
        hiddenCountry.value = country.iso;
        return;
      }

      if (isInternational(phone.value)) {
        phone.value = '+' + internationalDigits(phone.value);
        hiddenCountry.value = '';
        return;
      }

      const local = digitsOnly(phone.value);
      const dial = digitsOnly(component.dialInput.value);
      if (!local) return;
      phone.value = '+' + dial + local;
      hiddenCountry.value = '';
    }, true);
  };

  const lockVerifiedPhone = (phone, component, hiddenCountry, initialPhone, initialCountry) => {
    if (hiddenCountry.getAttribute('data-phone-verified') !== 'true' || !String(initialPhone || '').trim()) return false;
    const form = phone.form || (phone.closest && phone.closest('form'));

    phone.readOnly = true;
    phone.setAttribute('aria-readonly', 'true');
    phone.setAttribute('data-verified-phone-locked', 'true');
    if (component) {
      component.wrapper.classList.add('account-phone-input--locked');
      component.select.disabled = true;
      component.select.setAttribute('aria-disabled', 'true');
      component.dialInput.disabled = true;
    }

    if (form) {
      form.addEventListener('submit', () => {
        phone.value = initialPhone;
        hiddenCountry.value = initialCountry;
      }, true);
    }
    return true;
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

    const initialPhone = String(phone.value || '');
    const initialCountry = String(hiddenCountry.value || '').trim().toUpperCase();
    const supportedInitialCountry = byIso(initialCountry);

    // Do not reinterpret existing customer data for a country outside the
    // storefront/CRM table. Keeping the native field is safer than silently
    // defaulting an established DE/FR/etc. customer to Singapore.
    if (initialCountry && !supportedInitialCountry) {
      lockVerifiedPhone(phone, null, hiddenCountry, initialPhone, initialCountry);
      return;
    }

    const initialIso = supportedInitialCountry
      ? initialCountry
      : (isInternational(initialPhone) ? '' : 'SG');
    const component = buildComponent(phone, initialIso);
    if (!component) return;
    component.wrapper.classList.add('account-phone-input--details');

    if (isInternational(initialPhone)) inferFromInternational(phone, component, hiddenCountry);

    const state = { dirty: false };
    attachListeners(phone, component, hiddenCountry, state);
    const locked = lockVerifiedPhone(phone, component, hiddenCountry, initialPhone, initialCountry);
    if (!locked) interceptDetailsSubmit(phone, component, hiddenCountry, state);
  };

  const start = () => {
    document.querySelectorAll('[data-phone-country-code]').forEach(enhanceDetailsPhone);
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
