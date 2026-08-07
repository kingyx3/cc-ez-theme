/*
 * Drives the real customer-order-limits.js against a minimal DOM and reports
 * every URL it fetched, as JSON on stdout.
 *
 * The bug this exists for is behavioural, not textual: the script crawled
 * /account/orders from /account/login and /account/auth, so a string assertion
 * over the source would not have caught it and would not catch its return.
 *
 * argv[2] is the asset path, argv[3] the pathname to simulate, argv[4] the
 * sign-in markup the header would render ('in', 'out' or 'none').
 */
'use strict';

const fs = require('fs');
const vm = require('vm');

const [assetPath, pathname, signedInMarkup] = process.argv.slice(2);

const requested = [];

// Matches only what the script actually queries. Anything it asks for that is
// not modelled here returns null, which is the honest answer for a page that
// does not render it.
const markup = {
  in: ['body.customer-logged-in', '[data-customer-authenticated="true"]', 'a[href^="/account/logout"]'],
  out: ['[data-customer-authenticated="false"]'],
  none: [],
}[signedInMarkup || 'none'];

const matchesAny = (selector) => String(selector)
  .split(',')
  .map((part) => part.trim())
  .some((part) => markup.includes(part));

const noopElement = {
  children: [],
  dataset: {},
  classList: { add() {}, remove() {}, contains: () => false },
  addEventListener() {},
  removeEventListener() {},
  setAttribute() {},
  removeAttribute() {},
  getAttribute: () => null,
  closest: () => null,
  matches: () => false,
  querySelector: () => null,
  querySelectorAll: () => [],
  appendChild(node) { return node; },
  insertBefore(node) { return node; },
  remove() {},
  textContent: '',
};

const documentStub = {
  readyState: 'complete',
  documentElement: noopElement,
  body: noopElement,
  head: noopElement,
  addEventListener() {},
  removeEventListener() {},
  dispatchEvent: () => true,
  createElement: () => ({ ...noopElement, style: {} }),
  getElementById: () => null,
  querySelector: (selector) => (matchesAny(selector) ? noopElement : null),
  querySelectorAll: (selector) => (matchesAny(selector) ? [noopElement] : []),
};

const store = new Map();
const storage = {
  getItem: (key) => (store.has(key) ? store.get(key) : null),
  setItem: (key, value) => { store.set(key, String(value)); },
  removeItem: (key) => { store.delete(key); },
};

const windowStub = {
  location: { pathname, search: '', href: `https://example.test${pathname}`, assign() {} },
  sessionStorage: storage,
  localStorage: storage,
  setTimeout,
  clearTimeout,
  requestAnimationFrame: (callback) => setTimeout(callback, 0),
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  // Fourteen rules ship on this store, so the script's empty-rules early return
  // never fires on a real page. One rule reproduces that.
  customerOrderLimitsV2: {
    rules: {
      'test-product': { limit: 2, cartQuantity: 0, purchased: 0 },
    },
    // Zero line items read inline is exactly what a signed-out page reports,
    // and it is what puts history into the 'unknown' state that triggers a load.
    diagnostics: { lineItemsSeen: 0 },
    customerAuthenticated: false,
    customerId: '',
  },
};

const context = {
  window: windowStub,
  document: documentStub,
  location: windowStub.location,
  console,
  setTimeout,
  clearTimeout,
  Promise,
  JSON,
  Math,
  Date,
  Number,
  String,
  Array,
  Object,
  Set,
  Map,
  Error,
  CustomEvent: class CustomEvent { constructor(type, init) { this.type = type; Object.assign(this, init); } },
  DOMParser: class DOMParser { parseFromString() { return { getElementById: () => null }; } },
  fetch: (url) => {
    requested.push(String(url));
    return Promise.resolve({
      ok: true,
      status: 200,
      text: () => Promise.resolve('<html></html>'),
    });
  },
};
context.globalThis = context;
context.self = context;

vm.createContext(context);
vm.runInContext(fs.readFileSync(assetPath, 'utf8'), context, { filename: assetPath });

// Let any promise chain the script started settle before reporting.
setTimeout(() => {
  process.stdout.write(JSON.stringify({
    requested,
    authEntryPage: Boolean(
      context.window.CustomerOrderLimits
      && context.window.CustomerOrderLimits.onAuthEntryPage
      && context.window.CustomerOrderLimits.onAuthEntryPage()
    ),
    ran: Boolean(context.window.CustomerOrderLimits),
  }));
}, 50);
