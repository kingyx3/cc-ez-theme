/*
 * Progressive enhancement for the customer-details phone field.
 *
 * EasyStore already accepts an ISO country_code beside details[phone]. Keep
 * that contract for the countries the store's CRM normalizer also knows how to
 * interpret. For every other country, the shopper can choose Other and enter a
 * full +E.164-style number; the stale/default country_code is then cleared so
 * neither EasyStore nor the CRM can reinterpret it as Singapore.
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
  const OTHER_MESSAGE = 'For Other, enter the full international phone number starting with +.';
  const PHONE_MESSAGE = 'Please enter a valid phone number with 7 to 15 digits.';
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
      '.account-phone-input > .field {',
      '  margin-top: 0;',
      '  margin-bottom: 0;',
      '}',
      '.account-phone-input__country select {',
      '  width: 100%;',
      '}',
      '.account-phone-input__hint {',
      '  grid-column: 1 / -1;',
      '  margin: 0.4rem 0 0;',
      '  font-size: 1.2rem;',
      '  line-height: 1.4;',
      '}',
      '@media screen and (max-width: 480px) {',
      '  .account-phone-input {',
      '    grid-template-columns: minmax(10.5rem, 12rem) minmax(0, 1fr);',
      '    gap: 0.8rem;',
      '  }',
      '}',
    ].join('\n');
    document.head.appendChild(style);
  };

  const buildCountryField = (phone, hiddenCountry) => {
    const phoneField = phone.closest('.field');
    if (!phoneField || !phoneField.parentNode) return null;
    if (phoneField.parentNode.classList && phoneField.parentNode.classList.contains('account-phone-input')) {
      return phoneField.parentNode.querySelector('[data-phone-country-select]');
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'account-phone-input';

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
    other.textContent = 'Other (+ full number)';
    select.appendChild(other);

    const label = document.createElement('label');
    label.setAttribute('for', select.id);
    label.textContent = 'Country code';

    selectWrapper.appendChild(select);
    countryField.appendChild(selectWrapper);
    countryField.appendChild(label);

    const hint = document.createElement('small');
    hint.className = 'account-phone-input__hint';
    hint.id = phone.id + 'InternationalHint';
    hint.hidden = true;
    hint.textContent = 'For Other, enter the full number including + country code.';

    const parent = phoneField.parentNode;
    parent.insertBefore(wrapper, phoneField);
    wrapper.appendChild(countryField);
    wrapper.appendChild(phoneField);
    wrapper.appendChild(hint);
    phoneField.classList.add('account-phone-input__number');

    const initialCountry = String(hiddenCountry.value || '').trim().toUpperCase();
    select.value = byIso(initialCountry) ? initialCountry : (initialCountry ? '' : 'SG');
    hiddenCountry.value = select.value;

    return select;
  };

  const enhance = (hiddenCountry) => {
    if (!hiddenCountry || hiddenCountry.dataset.phoneCountryEnhanced === 'true') return;

    const phoneId = hiddenCountry.getAttribute('data-phone-input-id') || 'DetailPhone';
    const phone = document.getElementById(phoneId);
    if (!phone) return;

    hiddenCountry.dataset.phoneCountryEnhanced = 'true';
    phone.setAttribute('type', 'tel');
    phone.setAttribute('inputmode', 'tel');
    phone.setAttribute('autocomplete', 'tel-national');

    ensureStyles();
    const select = buildCountryField(phone, hiddenCountry);
    if (!select) return;

    const wrapper = phone.closest('.account-phone-input');
    const hint = wrapper ? wrapper.querySelector('.account-phone-input__hint') : null;

    const syncHint = () => {
      if (!hint) return;
      hint.hidden = Boolean(select.value);
      if (select.value) phone.removeAttribute('aria-describedby');
      else phone.setAttribute('aria-describedby', hint.id);
    };

    const syncCountryFromPhone = () => {
      if (!isInternational(phone.value)) return;

      const matches = countryMatchesForInternational(phone.value);
      if (!matches.length) {
        select.value = '';
        hiddenCountry.value = '';
        syncHint();
        return;
      }

      const current = matches.find((country) => country.iso === select.value);
      if (current) {
        hiddenCountry.value = current.iso;
        syncHint();
        return;
      }

      if (matches.length === 1) {
        select.value = matches[0].iso;
        hiddenCountry.value = matches[0].iso;
      } else {
        // +1 is shared by the US and Canada. Do not guess between them.
        select.value = '';
        hiddenCountry.value = '';
      }
      syncHint();
    };

    const validate = () => {
      const value = String(phone.value || '').trim();
      if (!value) {
        phone.setCustomValidity('');
        return true;
      }

      const international = isInternational(value);
      const count = international ? internationalDigits(value).length : digitsOnly(value).length;

      if (!select.value && !international) {
        phone.setCustomValidity(OTHER_MESSAGE);
        return false;
      }
      if (count < PHONE_MIN_DIGITS || count > PHONE_MAX_DIGITS) {
        phone.setCustomValidity(PHONE_MESSAGE);
        return false;
      }

      phone.setCustomValidity('');
      return true;
    };

    const update = () => {
      syncCountryFromPhone();
      hiddenCountry.value = select.value;
      syncHint();
      validate();
    };

    select.addEventListener('change', update);
    phone.addEventListener('input', update);
    phone.addEventListener('change', update);
    phone.addEventListener('blur', update);

    syncCountryFromPhone();
    syncHint();
    validate();

    const form = phone.form;
    if (!form) return;

    // Run at document-capture time so the account-details draft saver sees the
    // exact values that will be posted. The earlier profile validator may have
    // already cancelled the event; in that case leave the shopper's text alone.
    document.addEventListener('submit', (event) => {
      if (event.target !== form || event.defaultPrevented) return;

      update();
      if (!validate()) {
        event.preventDefault();
        event.stopPropagation();
        if (phone.focus) phone.focus();
        return;
      }

      const value = String(phone.value || '').trim();
      if (!value || !isInternational(value)) return;

      const international = internationalDigits(value);
      const country = byIso(select.value);
      if (country && international.indexOf(country.dial) === 0) {
        // EasyStore's established contract is national number + ISO country.
        phone.value = international.slice(country.dial.length);
        hiddenCountry.value = country.iso;
      } else {
        // Unknown/ambiguous countries stay explicit and must not inherit SG.
        phone.value = '+' + international;
        hiddenCountry.value = '';
      }
    }, true);
  };

  const start = () => {
    document.querySelectorAll('[data-phone-country-code]').forEach(enhance);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
