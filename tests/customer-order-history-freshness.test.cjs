const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const code = fs.readFileSync(process.env.LIMIT_MODULE || path.join(__dirname, '../theme/assets/customer-order-limits.js'), 'utf8');
const handle = 'limited-product';

function page(store, storage = new Map()) {
  const listeners = {};
  const requests = [];
  const window = {
    customerOrderLimitsV2: {
      customerAuthenticated: true, customerId: '900', diagnostics: { lineItemsSeen: 0 },
      rules: { [handle]: { maximum: 2, purchased: 0, cartQuantity: 0, allowedCartQuantity: 2, remaining: 2 } },
    },
    location: { pathname: '/products/limited-product', search: '' },
    sessionStorage: {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    },
    addEventListener: (type, callback) => { listeners[type] = callback; },
  };
  const document = {
    querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
    addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
  };
  vm.runInNewContext(code, {
    window, document,
    CustomEvent: class { constructor(type) { this.type = type; } },
    DOMParser: class {
      parseFromString(text) { return { getElementById: () => ({ textContent: text }) }; }
    },
    fetch: async (url, options) => {
      requests.push({ url, options });
      return { ok: true, text: async () => JSON.stringify({
        customer: '900', lines: store.units ? [[handle, '', 1, store.units, 'order-1', '', '']] : [],
      }) };
    },
  });
  return { api: window.CustomerOrderLimits, requests, listeners };
}

test('a return visit counts purchases made after the previous page loaded', async () => {
  const store = { units: 0 };
  const storage = new Map();
  const before = page(store, storage);
  await before.api.loadHistory();
  assert.equal(before.api.additionViolation(handle, 1), null);
  store.units = 2;
  const after = page(store, storage);
  await after.api.loadHistory();
  assert.equal(after.api.ruleFor(handle).purchased, 2);
  assert.ok(after.api.additionViolation(handle, 1));
  assert.ok(after.api.cartViolation({ [handle]: 1 }));
  assert.equal(after.requests.length, 1);
  assert.equal(after.requests[0].options.cache, 'no-store');
});

test('a restored page reloads history instead of keeping its pre-checkout allowance', async () => {
  const store = { units: 0 };
  const restored = page(store);
  await restored.api.loadHistory();
  store.units = 2;
  restored.listeners.pageshow({ persisted: true });
  assert.equal(restored.api.historyState(), 'pending');
  await restored.api.loadHistory();
  assert.equal(restored.api.ruleFor(handle).purchased, 2);
  assert.ok(restored.api.additionViolation(handle, 1));
  assert.equal(restored.requests.length, 2);
});

test('callers on the same page share the history request', async () => {
  const current = page({ units: 1 });
  await Promise.all([current.api.loadHistory(), current.api.loadHistory()]);
  assert.equal(current.requests.length, 1);
  assert.equal(current.api.ruleFor(handle).purchased, 1);
  assert.equal(current.api.additionViolation(handle, 1), null);
  assert.ok(current.api.additionViolation(handle, 2));
});
