'use strict';

const assert = require('node:assert/strict');
const otp = require('../theme/assets/otp-cell-autofill.js');

class MockEvent {
  constructor(type, options = {}) {
    this.type = type;
    this.bubbles = Boolean(options.bubbles);
  }
}

class MockInput {
  constructor(attributes = {}) {
    this.attributes = { ...attributes };
    this.type = attributes.type || 'text';
    this.inputMode = attributes.inputmode || '';
    this.maxLength = Number(attributes.maxlength || 1);
    this.value = '';
    this.disabled = false;
    this.readOnly = false;
    this.dataset = {};
    this.listeners = new Map();
    this.parentElement = null;
    this.form = null;
    this.focused = false;
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name)
      ? this.attributes[name]
      : null;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === 'maxlength') this.maxLength = Number(value);
    if (name === 'inputmode') this.inputMode = String(value);
  }

  matches(selector) {
    return selector.includes('autocomplete="one-time-code"')
      && this.getAttribute('autocomplete') === 'one-time-code';
  }

  querySelectorAll() {
    return [];
  }

  addEventListener(type, callback) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(callback);
  }

  emit(type, event = {}) {
    for (const callback of this.listeners.get(type) || []) callback(event);
  }

  dispatchEvent(event) {
    this.emit(event.type, event);
    return true;
  }

  focus() {
    this.focused = true;
  }
}

const cells = Array.from({ length: 6 }, (_, index) => new MockInput({
  type: 'tel',
  maxlength: '1',
  inputmode: 'numeric',
  ...(index === 0 ? { autocomplete: 'one-time-code' } : {}),
}));

const form = {
  id: 'sms-challenge',
  className: 'customer-verification',
  textContent: 'Enter the verification code sent by SMS',
  dataset: {},
  parentElement: null,
  getAttribute(name) {
    return name === 'action' ? '/account/request-verify' : null;
  },
  querySelectorAll(selector) {
    return selector === 'input' ? cells : [];
  },
};

const group = {
  parentElement: form,
  querySelectorAll(selector) {
    return selector === 'input' ? cells : [];
  },
};

cells.forEach((cell) => {
  cell.parentElement = group;
  cell.form = form;
});

const fallback = {
  textContent: 'Continue with email instead',
  removed: false,
  remove() {
    this.removed = true;
  },
};

const documentObject = {
  body: { textContent: 'Enter the verification code sent by SMS' },
  querySelectorAll(selector) {
    if (selector === 'form') return [form];
    if (selector.startsWith('a, button')) return [fallback];
    return [];
  },
  querySelector() {
    return cells[0];
  },
};

const windowObject = {
  location: { pathname: '/account/request-verify' },
  Event: MockEvent,
  requestAnimationFrame(callback) {
    callback();
  },
};

const detected = otp.findOtpCells(form, documentObject, windowObject);
assert.equal(detected.length, 6, 'all six generic sibling cells must be detected');
assert.deepEqual(detected, cells);

otp.configureOtpCells(form, detected, windowObject);
assert.equal(cells[0].getAttribute('autocomplete'), 'one-time-code');
assert.equal(cells[0].getAttribute('maxlength'), '6');
for (const cell of cells.slice(1)) {
  assert.equal(cell.getAttribute('autocomplete'), 'off');
  assert.equal(cell.getAttribute('maxlength'), '1');
}

cells[0].value = '123456';
cells[0].emit('input');
assert.deepEqual(cells.map((cell) => cell.value), ['1', '2', '3', '4', '5', '6']);
assert.equal(cells[5].focused, true);

cells.forEach((cell) => {
  cell.value = '';
  cell.focused = false;
});
let pastePrevented = false;
cells[0].emit('paste', {
  clipboardData: { getData: () => '654321' },
  preventDefault() { pastePrevented = true; },
});
assert.equal(pastePrevented, true);
assert.deepEqual(cells.map((cell) => cell.value), ['6', '5', '4', '3', '2', '1']);

const groups = otp.scanAndEnhance(documentObject, windowObject);
assert.equal(groups.length, 1);
assert.equal(fallback.removed, true, 'email fallback must be removed while OTP is active');

console.log('OTP runtime regression passed');
