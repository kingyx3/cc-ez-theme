const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const code = fs.readFileSync(process.env.LIMIT_MODULE || path.join(__dirname, '../theme/assets/customer-order-limits.js'), 'utf8');
const handle = 'limited-product';

function page(store, storage = new Map(), options = {}) {
  const listeners = {};
  const requests = [];
  const fetchHistory = async (url, requestOptions) => {
    requests.push({ url, options: requestOptions });
    return { ok: true, text: async () => JSON.stringify({
      customer: '900', lines: store.units ? [[handle, '', 1, store.units, 'order-1', '', '']] : [],
    }) };
  };
  const window = {
    customerOrderLimitsV2: {
      customerAuthenticated: true, customerId: '900', diagnostics: { lineItemsSeen: 0 },
      rules: { [handle]: { maximum: 2, purchased: 0, cartQuantity: 0, allowedCartQuantity: 2, remaining: 2 } },
    },
    location: { pathname: options.pathname || '/products/limited-product', search: '' },
    fetch: fetchHistory,
    sessionStorage: {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    },
    addEventListener: (type, callback) => { listeners[type] = callback; },
  };
  if (options.profileRequired) window.ccProfileCompletionRequired = true;
  const document = {
    querySelector: selector => (
      options.authMarkup && selector.includes('#otp-form') ? {} : null
    ),
    querySelectorAll: () => [], getElementById: () => null,
    addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
  };
  vm.runInNewContext(code, {
    window, document,
    CustomEvent: class { constructor(type) { this.type = type; } },
    DOMParser: class {
      parseFromString(text) { return { getElementById: () => ({ textContent: text }) }; }
    },
    fetch: fetchHistory,
  });
  return { api: window.CustomerOrderLimits, requests, listeners, window, fetchHistory };
}

function detailFallbackPage() {
  const requests = [];
  const orderLink = { getAttribute: () => '/account/orders/order-1' };
  const productLink = { getAttribute: () => '/products/limited-product' };
  const detailRow = { querySelector: () => productLink };
  const badge = {
    textContent: '2',
    closest: selector => (
      selector === '.flex-table-tr' ? detailRow : productLink
    ),
  };
  const listDocument = {
    getElementById: () => ({
      textContent: JSON.stringify({
        customer: '900',
        renderedAt: 1,
        diagnostics: { ordersSeen: 1, lineItemsSeen: 0 },
        tabs: [],
        nextUrl: '',
        lines: [],
      }),
    }),
    querySelectorAll: selector => (
      selector === 'article.flex-table-tr'
        ? [{
          querySelector: childSelector => (
            childSelector === '.order-status .label-tag-alert' ? null : orderLink
          ),
        }]
        : []
    ),
  };
  const detailDocument = {
    querySelector: selector => (
      selector === '.order-date' ? { textContent: '2026-09-10T00:00:00Z' } : null
    ),
    querySelectorAll: selector => (selector === '.product-qty-badge' ? [badge] : []),
  };
  const fetchHistory = async (url, options) => {
    requests.push({ url, options });
    return {
      ok: true,
      status: 200,
      text: async () => (url === '/account/orders' ? 'list' : 'detail'),
    };
  };
  const window = {
    customerOrderLimitsV2: {
      customerAuthenticated: true, customerId: '900', diagnostics: { lineItemsSeen: 0 },
      rules: { [handle]: { maximum: 2, purchased: 0, cartQuantity: 0, allowedCartQuantity: 2, remaining: 2 } },
    },
    location: {
      href: 'https://shop.example/products/limited-product',
      origin: 'https://shop.example',
      pathname: '/products/limited-product',
      search: '',
    },
    fetch: fetchHistory,
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    addEventListener() {},
  };
  const document = {
    querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
    addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
  };
  vm.runInNewContext(code, {
    window, document, URL,
    CustomEvent: class { constructor(type) { this.type = type; } },
    DOMParser: class {
      parseFromString(text) { return text === 'list' ? listDocument : detailDocument; }
    },
    fetch: fetchHistory,
  });
  return { api: window.CustomerOrderLimits, fetchHistory, requests, window };
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

test('account setup never loads history or replaces the browser fetch API', async () => {
  const cases = [
    { pathname: '/account/auth' },
    { authMarkup: true },
    { profileRequired: true },
  ];
  for (const options of cases) {
    const current = page({ units: 1 }, new Map(), options);
    await current.api.loadHistory();
    assert.equal(current.api.historyState(), 'unavailable');
    assert.equal(current.requests.length, 0);
    assert.equal(current.window.fetch, current.fetchHistory);
  }
});

test('the scoped loader hydrates an empty list payload from order details', async () => {
  const current = detailFallbackPage();
  await current.api.loadHistory();
  assert.deepEqual(current.requests.map(request => request.url), [
    '/account/orders',
    '/account/orders/order-1',
  ]);
  assert.equal(current.api.historyState(), 'loaded');
  assert.equal(current.api.ruleFor(handle).purchased, 2);
  assert.ok(current.api.additionViolation(handle, 1));
  assert.equal(current.api.historyLines()[0][0], handle);
  assert.equal(current.api.historyLines()[0][3], 2);
  assert.equal(current.api.historyLines()[0][4], 'order-1');
  assert.equal(current.api.historyLines()[0][6], 'detail:order-1:0');
  assert.equal(current.window.fetch, current.fetchHistory);
});
