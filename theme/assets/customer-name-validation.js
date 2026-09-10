(function () {
  'use strict';

  var MIN_NAME_LENGTH = 2;
  var MIN_NAME_PATTERN = '[\\s\\S]{2,}';
  var NAME_FIELDS = [
    'customer[first_name]',
    'customer[last_name]',
    'details[first_name]',
    'details[last_name]'
  ];

  function applyNameValidation(field) {
    field.setAttribute('minlength', String(MIN_NAME_LENGTH));
    field.setAttribute('required', 'required');

    // `minlength` covers user-entered values. The pattern also validates values
    // that EasyStore or the browser prefilled before the customer submits.
    if (!field.hasAttribute('pattern')) {
      field.setAttribute('pattern', MIN_NAME_PATTERN);
    }
  }

  function init() {
    NAME_FIELDS.forEach(function (name) {
      var selector = '[name="' + name + '"]';
      var fields = document.querySelectorAll(selector);
      Array.prototype.forEach.call(fields, applyNameValidation);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
