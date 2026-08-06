'use strict';

const assert = require('node:assert/strict');
const coordinator = require('../theme/assets/otp-verification-coordinator.js');

const makeEvent = (form) => ({
  target: form,
  defaultPrevented: false,
  immediatePropagationStopped: false,
  preventDefault() { this.defaultPrevented = true; },
  stopImmediatePropagation() { this.immediatePropagationStopped = true; },
});

const makeFixture = ({ cellValues, proxyValue }) => {
  const form = {
    dataset: { otpSubmissionInFlight: 'true' },
    __cardboardOtpAutofillProxy: null,
    querySelector() { return this.__cardboardOtpAutofillProxy; },
  };
  const cells = cellValues.map((value) => ({ value, form }));
  const proxy = {
    value: proxyValue,
    form,
    dataset: {},
    __otpCells: cells,
  };
  form.__cardboardOtpAutofillProxy = proxy;
  return { form, cells, proxy };
};

const queuedMicrotasks = [];
const windowObject = {
  queueMicrotask(callback) { queuedMicrotasks.push(callback); },
};

{
  const { form, cells, proxy } = makeFixture({
    cellValues: ['1', '2', '3', '4', '5', '6'],
    proxyValue: '',
  });
  const result = coordinator.reconcileOtpState(form, {}, windowObject);
  assert.deepEqual(result, { complete: true, source: 'cells', code: '123456' });
  assert.equal(proxy.value, '123456', 'desktop/manual cell state must win over an empty proxy');
  assert.deepEqual(cells.map((cell) => cell.value), ['1', '2', '3', '4', '5', '6']);
}

{
  const { form, cells, proxy } = makeFixture({
    cellValues: ['', '', '', '', '', ''],
    proxyValue: '654321',
  });
  const result = coordinator.reconcileOtpState(form, {}, windowObject);
  assert.deepEqual(result, { complete: true, source: 'proxy', code: '654321' });
  assert.deepEqual(cells.map((cell) => cell.value), ['6', '5', '4', '3', '2', '1']);
  assert.equal(proxy.value, '654321');
}

{
  const { form, cells, proxy } = makeFixture({
    cellValues: ['1', '2', '', '', '', ''],
    proxyValue: '',
  });
  const result = coordinator.reconcileOtpState(form, {}, windowObject);
  assert.deepEqual(result, { complete: false, source: 'partial', code: '' });
  assert.equal(proxy.value, '', 'partial input must not be replaced or treated as complete');
  assert.deepEqual(cells.map((cell) => cell.value), ['1', '2', '', '', '', '']);
}

{
  const { form } = makeFixture({
    cellValues: ['1', '2', '3', '4', '5', '6'],
    proxyValue: '123456',
  });

  const first = makeEvent(form);
  assert.equal(coordinator.coordinateSubmit(first, {}, windowObject), true);
  assert.equal(first.defaultPrevented, false);
  assert.equal(form.dataset.otpSubmissionInFlight, undefined, 'stale ten-second lock must be cleared');
  assert.equal(form.dataset.otpSubmissionCoordinator, 'true');
  assert.equal(queuedMicrotasks.length, 1);

  form.dataset.otpSubmissionInFlight = 'true';
  const reentrant = makeEvent(form);
  assert.equal(coordinator.coordinateSubmit(reentrant, {}, windowObject), false);
  assert.equal(reentrant.defaultPrevented, true, 'same-task duplicate must be blocked');
  assert.equal(reentrant.immediatePropagationStopped, true);

  queuedMicrotasks.shift()();
  const followUp = makeEvent(form);
  assert.equal(coordinator.coordinateSubmit(followUp, {}, windowObject), true);
  assert.equal(followUp.defaultPrevented, false, 'later EasyStore completion submit must be allowed');
  assert.equal(form.dataset.otpSubmissionInFlight, undefined);
}

{
  const listeners = [];
  const documentObject = {
    addEventListener(type, callback, capture) { listeners.push({ type, callback, capture }); },
  };
  coordinator.bind(documentObject, windowObject);
  coordinator.bind(documentObject, windowObject);
  assert.equal(listeners.length, 1, 'binding must be idempotent');
  assert.deepEqual(
    { type: listeners[0].type, capture: listeners[0].capture },
    { type: 'submit', capture: true },
  );
}

console.log('OTP verification coordinator runtime regression passed');
