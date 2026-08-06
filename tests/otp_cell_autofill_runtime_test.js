'use strict';

const assert = require('node:assert/strict');
const otp = require('../theme/assets/otp-cell-autofill.js');

class MockEvent {
  constructor(type, options = {}) {
    this.type = type;
    this.bubbles = Boolean(options.bubbles);
    this.defaultPrevented = false;
    this.immediatePropagationStopped = false;
  }

  preventDefault() {
    this.defaultPrevented = true;
  }

  stopImmediatePropagation() {
    this.immediatePropagationStopped = true;
  }
}

class MockStyle {
  constructor() {
    this.values = {};
    this.position = '';
  }

  setProperty(name, value) {
    this.values[name] = String(value);
    if (name === 'position') this.position = String(value);
  }
}

class MockInput {
  constructor(attributes = {}, platformControlled = false) {
    this.attributes = { ...attributes };
    this.type = attributes.type || 'text';
    this.inputMode = attributes.inputmode || '';
    this.maxLength = Number(attributes.maxlength || 524288);
    this._value = '';
    this.platformControlled = platformControlled;
    this.disabled = false;
    this.readOnly = false;
    this.dataset = {};
    this.listeners = new Map();
    this.parentElement = null;
    this.form = null;
    this.focused = false;
    this.style = new MockStyle();
  }

  get value() {
    return this._value;
  }

  set value(value) {
    const stringValue = String(value);
    this._value = this.platformControlled
      ? stringValue.slice(0, Math.max(this.maxLength, 0))
      : stringValue;
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

  emit(type, event = new MockEvent(type)) {
    for (const callback of this.listeners.get(type) || []) {
      callback(event);
      if (event.immediatePropagationStopped) break;
    }
    return event;
  }

  dispatchEvent(event) {
    this.emit(event.type, event);
    return !event.defaultPrevented;
  }

  focus() {
    this.focused = true;
  }

  setSelectionRange() {}
}

const cells = Array.from({ length: 6 }, (_, index) => new MockInput({
  type: 'tel',
  maxlength: '1',
  inputmode: 'numeric',
  ...(index === 0 ? { autocomplete: 'one-time-code' } : {}),
}, true));

const form = {
  id: 'sms-challenge',
  className: 'customer-verification',
  textContent: 'Enter the verification code sent by SMS',
  dataset: {},
  parentElement: null,
  children: [],
  style: new MockStyle(),
  listeners: new Map(),
  getAttribute(name) {
    return name === 'action' ? '/account/request-verify' : null;
  },
  querySelectorAll(selector) {
    return selector === 'input' ? group.children : [];
  },
  appendChild(child) {
    child.parentElement = this;
    child.form = this;
    this.children.push(child);
  },
  addEventListener(type, callback) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(callback);
  },
  emit(type, event = new MockEvent(type)) {
    for (const callback of this.listeners.get(type) || []) {
      callback(event);
      if (event.immediatePropagationStopped) break;
    }
    return event;
  },
};

const group = {
  parentElement: form,
  children: [...cells],
  style: new MockStyle(),
  querySelectorAll(selector) {
    return selector === 'input' ? this.children : [];
  },
  appendChild(child) {
    child.parentElement = this;
    child.form = form;
    this.children.push(child);
  },
};
form.children.push(group);

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
  createElement(tagName) {
    assert.equal(tagName, 'input');
    return new MockInput();
  },
  querySelectorAll(selector) {
    if (selector === 'form') return [form];
    if (selector.startsWith('a, button')) return [fallback];
    return [];
  },
  querySelector() {
    return cells[0];
  },
};

const scheduledTimeouts = [];
const windowObject = {
  location: { pathname: '/account/request-verify' },
  Event: MockEvent,
  requestAnimationFrame(callback) {
    callback();
  },
  setTimeout(callback, delay) {
    scheduledTimeouts.push({ callback, delay });
    return scheduledTimeouts.length;
  },
};

const detected = otp.findOtpCells(form, documentObject, windowObject);
assert.equal(detected.length, 6, 'all six generic sibling cells must be detected');
assert.deepEqual(detected, cells);

const proxy = otp.configureOtpCells(form, detected, windowObject, documentObject);
assert.ok(proxy, 'a dedicated OTP autofill receiver must be created');
assert.equal(proxy.getAttribute('data-otp-autofill-proxy'), 'true');
assert.equal(proxy.getAttribute('autocomplete'), 'one-time-code');
assert.equal(proxy.getAttribute('maxlength'), '6');
assert.equal(group.children.at(-1), proxy, 'proxy must be mounted over the OTP group');

assert.equal(form.dataset.webOtpRequested, 'true', 'legacy WebOTP helper must be disabled');
assert.equal(
  form.dataset.otpEnhancementOwner,
  'otp-cell-autofill',
  'the dedicated OTP implementation must own the form',
);
assert.equal(form.dataset.otpSubmissionGuardBound, 'true');

for (const cell of cells) {
  assert.equal(cell.getAttribute('autocomplete'), 'off');
  assert.equal(cell.getAttribute('maxlength'), '1');
}

// The real platform clips its controlled visible cell to one character. Autofill must
// therefore land in the independent six-character proxy, not in the first cell.
cells[0].value = '123456';
assert.equal(cells[0].value, '1', 'controlled visible cell reproduces the live truncation');
cells.forEach((cell) => { cell.value = ''; });

proxy.value = '123456';
proxy.emit('input');
assert.deepEqual(cells.map((cell) => cell.value), ['1', '2', '3', '4', '5', '6']);

// The first verification submission proceeds. A second overlapping submit is stopped
// before the platform can create the same phone account twice.
const firstSubmit = form.emit('submit');
assert.equal(firstSubmit.defaultPrevented, false);
assert.equal(firstSubmit.immediatePropagationStopped, false);
assert.equal(form.dataset.otpSubmissionInFlight, 'true');
assert.equal(scheduledTimeouts.length, 1);
assert.equal(scheduledTimeouts[0].delay, 10000);

const duplicateSubmit = form.emit('submit');
assert.equal(duplicateSubmit.defaultPrevented, true);
assert.equal(duplicateSubmit.immediatePropagationStopped, true);
assert.equal(scheduledTimeouts.length, 1, 'a blocked duplicate must not create another timer');

scheduledTimeouts[0].callback();
assert.equal(form.dataset.otpSubmissionInFlight, undefined);

const retrySubmit = form.emit('submit');
assert.equal(retrySubmit.defaultPrevented, false, 'a later retry must be allowed');
assert.equal(form.dataset.otpSubmissionInFlight, 'true');
assert.equal(scheduledTimeouts.length, 2);

// Mobile autofill may update the value without firing an input event. The periodic
// scanner must still notice the proxy value and distribute it.
cells.forEach((cell) => { cell.value = ''; });
proxy.value = '654321';
proxy.dataset.lastOtpValue = '';
const groups = otp.scanAndEnhance(documentObject, windowObject);
assert.equal(groups.length, 1);
assert.deepEqual(cells.map((cell) => cell.value), ['6', '5', '4', '3', '2', '1']);
assert.equal(fallback.removed, true, 'email fallback must be removed while OTP is active');
assert.equal(form.listeners.get('submit').length, 2, 'guards must not be rebound during rescans');

console.log('OTP proxy and submission guard runtime regression passed');
