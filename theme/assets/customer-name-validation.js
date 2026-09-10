(function () {
  'use strict';

  var MIN_NAME_LENGTH = 2;
  var NAME_FIELDS = [
    'customer[first_name]',
    'customer[last_name]',
    'details[first_name]',
    'details[last_name]'
  ];

  function applyNameValidation(field) {
    field.setAttribute('minlength', String(MIN_NAME_LENGTH));
    field.setAttribute('required', 'required');

    function syncValidity() {
      var value = String(field.value || '').trim();
      field.setCustomValidity(
        value.length < MIN_NAME_LENGTH ? 'Please enter at least 2 characters.' : ''
      );
    }

    field.addEventListener('input', syncValidity);
    syncValidity();
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
