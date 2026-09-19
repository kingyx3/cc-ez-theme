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

  const DROP_DOMESTIC_ZERO = new Set([
    'MY', 'ID', 'PH', 'TH', 'VN', 'TW', 'JP', 'KR', 'IN', 'AU', 'NZ', 'GB',
  ]);
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
    return COUNTRIES.filter(
      (country) => country.dial.length === longest && digits.indexOf(country.dial) === 0
    );
  };

  const rootFor = (node) => (node && node.getRootNode ? node.getRootNode() : document);

  const ensureStyles = (root) => {
    const styleRoot = root && root.nodeType === 11 ? root : document.head;
    if (!styleRoot || !styleRoot.querySelector || styleRoot.querySelector('#' + STYLE_ID)) return;
    const doc = styleRoot.ownerDocument || document;
    const style = doc.createElement('style');
    style.id = STYLE_ID;
    style.textContent = [
      '.account-phone-input { display:grid; grid-template-columns:minmax(11rem,14rem) minmax(0,1fr); gap:1rem; align-items:center; width:100%; }',
      '.account-phone-input--other { grid-template-columns:minmax(11rem,14rem) minmax(8rem,10rem) minmax(0,1fr); }',
      '.account-phone-input > .field, .account-phone-input > .account-phone-input__number-shell { margin:0!important; padding:0!important; align-self:center; }',
      '.account-phone-input__number-shell { min-width:0; }',
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
    styleRoot.appendChild(style);
  };

  const ensurePhoneId = (phone) => {
    if (phone.id) return phone.id;
    generatedId += 1;
    phone.id = 'AccountPhoneInput' + generatedId;
    return phone.id;
  };

  const createCountrySelect = (phone) => {
    const doc = phone.ownerDocument || document;
    const countryField = doc.createElement('div');
    countryField.className = 'field on_focus account-phone-input__country';
    const selectWrapper = doc.createElement('div');
    selectWrapper.className = 'select';
    const select = doc.createElement('select');
    select.id = ensurePhoneId(phone) + 'CountryCode';
    select.setAttribute('data-phone-country-select', '');
    select.setAttribute('aria-label', 'Country code');

    COUNTRIES.forEach((country) => {
      const option = doc.createElement('option');
      option.value = country.iso;
      option.textContent = country.label;
      select.appendChild(option);
    });
    const other = doc.createElement('option');
    other.value = '';
    other.textContent = 'Other';
    select.appendChild(other);

    const label = doc.createElement('label');
    label.setAttribute('for', select.id);
    label.textContent = 'Country code';
    selectWrapper.appendChild(select);
    countryField.appendChild(selectWrapper);
    countryField.appendChild(label);
    return { countryField, select };
  };

  const createDialField = (phone) => {
    const doc = phone.ownerDocument || document;
    const field = doc.createElement('div');
    field.className = 'field account-phone-input__dial';
    field.hidden = true;
    const input = doc.createElement('input');
    input.type = 'tel';
    input.id = ensurePhoneId(phone) + 'DialCode';
    input.inputMode = 'numeric';
    input.autocomplete = 'off';
    input.maxLength = 3;
    input.placeholder = '+ code';
    input.setAttribute('aria-label', 'Country calling code');
    const label = doc.createElement('label');
    label.setAttribute('for', input.id);
    label.textContent = '+ code';
    field.appendChild(input);
    field.appendChild(label);
    return { dialField: field, dialInput: input };
  };

  const buildComponent = (phone, initialIso, initialDial) => {
    const existing = phone.closest && phone.closest('.account-phone-input');
    if (existing) {
      return {
        wrapper: existing,
        select: existing.querySelector('[data-phone-country-select]'),
        dialField: existing.querySelector('.account-phone-input__dial'),
        dialInput: existing.querySelector('.account-phone-input__dial input'),
        hint: existing.querySelector('.account-phone-input__hint'),
      };
    }

    const doc = phone.ownerDocument || document;
    let phoneContainer = phone.closest && phone.closest('.field');
    if (!phoneContainer) {
      if (!phone.parentNode) return null;
      phoneContainer = doc.createElement('div');
      phoneContainer.className = 'account-phone-input__number account-phone-input__number-shell';
      phone.parentNode.insertBefore(phoneContainer, phone);
      phoneContainer.appendChild(phone);
    } else {
      phoneContainer.classList.add('account-phone-input__number');
    }
    if (!phoneContainer.parentNode) return null;

    ensureStyles(rootFor(phone));
    const wrapper = doc.createElement('div');
    wrapper.className = 'account-phone-input';
    const country = createCountrySelect(phone);
    const dial = createDialField(phone);
    const hint = doc.createElement('small');
    hint.className = 'account-phone-input__hint';
    hint.id = ensurePhoneId(phone) + 'InternationalHint';
    hint.hidden = true;
    hint.textContent = 'For Other, enter the country calling code and the local number without a domestic leading 0.';

    const parent = phoneContainer.parentNode;
    parent.insertBefore(wrapper, phoneContainer);
    wrapper.appendChild(country.countryField);
    wrapper.appendChild(dial.dialField);
    wrapper.appendChild(phoneContainer);
    wrapper.appendChild(hint);
    country.select.value = byIso(initialIso) ? String(initialIso).toUpperCase() : '';
    dial.dialInput.value = digitsOnly(initialDial).slice(0, 3);
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
      hiddenCountry.value = country.iso;
      syncOtherUi(component, phone);
      return true;
    }

    component.select.value = '';
    if (matches.length > 1) {
      component.dialInput.value = matches[0].dial;
      phone.value = raw.slice(matches[0].dial.length);
    } else {
      const guessedDialLength = Math.min(3, Math.max(1, raw.length - PHONE_MIN_DIGITS));
      component.dialInput.value = raw.slice(0, guessedDialLength);
      phone.value = raw.slice(guessedDialLength);
    }
    hiddenCountry.value = '';
    syncOtherUi(component, phone);
    return true;
  };

  const attachListeners = (phone, component, hiddenCountry) => {
    const update = () => {
      const country = byIso(component.select.value);
      if (country) component.dialInput.value = country.dial;
      hiddenCountry.value = country ? country.iso : '';
      syncOtherUi(component, phone);
      validateComponent(phone, component);
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

  const interceptDetailsSubmit = (phone, component, hiddenCountry) => {
    const form = phone.form || (phone.closest && phone.closest('form'));
    if (!form || form.dataset.accountPhoneSubmitEnhanced === 'true') return;
    form.dataset.accountPhoneSubmitEnhanced = 'true';

    form.addEventListener('submit', (event) => {
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
      if (country) {
        phone.value = stripDomesticZero(country.iso, local);
        hiddenCountry.value = country.iso;
      } else {
        phone.value = prepareInternationalValue(null, component.dialInput.value, local);
        hiddenCountry.value = '';
      }
    }, true);
  };

  const lockExistingDetailsPhone = (phone, component, hiddenCountry, initialPhone, initialCountry) => {
    if (hiddenCountry.getAttribute('data-phone-verified') !== 'true' || !String(initialPhone || '').trim()) return false;
    const form = phone.form || (phone.closest && phone.closest('form'));

    component.wrapper.classList.add('account-phone-input--locked');
    phone.readOnly = true;
    phone.setAttribute('aria-readonly', 'true');
    phone.setAttribute('data-verified-phone-locked', 'true');
    component.select.disabled = true;
    component.select.setAttribute('aria-disabled', 'true');
    component.dialInput.disabled = true;

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
    const doc = hiddenCountry.ownerDocument || document;
    const phone = doc.getElementById(phoneId);
    if (!phone) return;
    hiddenCountry.dataset.phoneCountryEnhanced = 'true';
    phone.setAttribute('type', 'tel');
    phone.setAttribute('inputmode', 'tel');
    phone.setAttribute('autocomplete', 'tel-national');
    const initialPhone = String(phone.value || '');
    const initialCountry = String(hiddenCountry.value || '').trim().toUpperCase();
    const component = buildComponent(phone, byIso(initialCountry) ? initialCountry : 'SG', '');
    if (!component) return;
    component.wrapper.classList.add('account-phone-input--details');
    inferFromInternational(phone, component, hiddenCountry);
    attachListeners(phone, component, hiddenCountry)();
    const locked = lockExistingDetailsPhone(phone, component, hiddenCountry, initialPhone, initialCountry);
    if (!locked) interceptDetailsSubmit(phone, component, hiddenCountry);
  };

  const start = () => {
    ensureStyles(document);
    document.querySelectorAll('[data-phone-country-code]').forEach(enhanceDetailsPhone);
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
