// Fills in a card's remaining-stock count when EasyStore did not send one.
//
// A collection listing does not carry the same product object a product page
// does, and it is not consistent about it: the same product is serialized with
// its stock in one collection and without it in another. The snippet can only
// print what it was given, so a card for a product that is meant to advertise
// its stock at every quantity can come out empty while its product page prints
// a count.
//
// The snippet looks a starved product up first, which costs no request, so this
// only runs for the cards that lookup could not answer either. It runs once the
// page is idle rather than when a card is scrolled to: a card that fills only
// on scroll cannot be told apart from a card that never filled at all, and that
// difference has cost several rounds of guessing here.
//
// window.cardInventoryFill reports what it did, so the difference between "did
// not run", "ran and found nothing" and "ran and filled" is readable from the
// console rather than inferred.
//
// snippets/low-inventory-notice.liquid renders the attributes this reads: a
// remaining of 0 means nothing was found to print, and the threshold is the
// count to print below - or 'all' for a product that prints at every quantity.
(() => {
  const STARVED = '[data-low-inventory-notice][data-low-inventory-remaining="0"]';
  // A ceiling on the requests one page may spend on this, in case a collection
  // of starved products is ever rendered in full.
  const MOST_REQUESTS = 8;
  // The same product is often carded more than once on a page.
  const asked = new Map();
  let spent = 0;
  const state = { ran: false, starved: 0, fetched: 0, filled: 0, errors: [] };
  window.cardInventoryFill = state;

  function handleFor(notice) {
    const card = notice.closest('.product-card-wrapper');
    const link = card && card.querySelector('a[href*="/products/"]');
    const href = link ? link.getAttribute('href') || '' : '';
    return (href.match(/\/products\/([^/?#]+)/) || [])[1] || '';
  }

  function total(quantities) {
    return quantities
      .filter(quantity => Number.isFinite(quantity) && quantity > 0)
      .reduce((sum, quantity) => sum + quantity, 0);
  }

  // A variant is dropped only for a flag that reads false, which is the rule
  // snippets/low-inventory-notice.liquid follows for the same reason: the three
  // spellings are not synonyms and a missing one is not a no.
  function unbuyable(variant) {
    for (const flag of [variant.available, variant.is_available, variant.is_enabled]) {
      if (flag === undefined || flag === null || flag === '') continue;
      return flag === false || flag === 0 || String(flag).toLowerCase() === 'false';
    }
    return false;
  }

  // The quickview payload is the cheapest place the count is available: 14 KB
  // against 226 KB for the same product's JSON, both measured on the store.
  //
  // It answers with JSON - { product: {...}, html: "<markup>" } - which is what
  // assets/product-quickview.js reads. Parsing the body as HTML finds nothing,
  // because the markup is a string inside it.
  async function remainingFor(handle) {
    const response = await fetch(`/products/${handle}/product_quickview_html`, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) return 0;

    const body = await response.text();
    let payload = null;
    try {
      payload = JSON.parse(body);
    } catch (error) {
      payload = null;
    }

    const product = (payload && payload.product) || {};
    if (Array.isArray(product.variants)) {
      const counted = total(
        product.variants
          .filter(variant => !unbuyable(variant))
          .map(variant => Number(variant.inventory_quantity))
      );
      if (counted > 0) return counted;
    }
    if (Number(product.inventory_quantity) > 0) return Number(product.inventory_quantity);

    // The rendered markup, either from the payload or from a body that was not
    // JSON at all. Quick view renders one option per variant a shopper can buy.
    const markup = payload && typeof payload.html === 'string' ? payload.html : body;
    const parsed = new DOMParser().parseFromString(markup, 'text/html');
    return total(
      Array.from(parsed.querySelectorAll('[data-inventory-quantity]'))
        .map(option => Number(option.dataset.inventoryQuantity))
    );
  }

  // A card prints below its own threshold, or at any quantity when the snippet
  // marked it as a product that always prints. The count is recorded either way,
  // so a card that stays quiet still says what it was told.
  function print(notice, remaining) {
    // So the probe can say which of the three routes produced this number.
    notice.dataset.lowInventoryRemaining = String(remaining);
    notice.dataset.lowInventorySource = 'fetch';

    const threshold = notice.dataset.lowInventoryThreshold;
    const limit = Number(threshold);
    const withinThreshold = String(threshold).trim().toLowerCase() === 'all'
      || (Number.isFinite(limit) && limit > 0 && remaining <= limit);
    const template = window.purchaseStrings && window.purchaseStrings.lowInventory;
    if (!withinThreshold || !template) return;

    notice.textContent = String(template).replace('__COUNT__', remaining);
    notice.classList.remove('hidden');
    notice.removeAttribute('hidden');
  }

  async function fill(notice) {
    const handle = handleFor(notice);
    if (!handle) {
      state.errors.push('a starved card carries no product link');
      return;
    }
    if (spent >= MOST_REQUESTS) return;

    if (!asked.has(handle)) {
      spent += 1;
      state.fetched += 1;
      asked.set(handle, remainingFor(handle).catch((error) => {
        state.errors.push(`${handle}: ${error.message}`);
        return 0;
      }));
    }

    const remaining = await asked.get(handle);
    // A product whose stock the platform does not track anywhere reports
    // nothing here either, and inventing a count for it is exactly what the
    // snippet refuses to do.
    if (remaining > 0) {
      print(notice, remaining);
      state.filled += 1;
    }
  }

  async function watch() {
    const starved = Array.from(document.querySelectorAll(STARVED));
    state.ran = true;
    state.starved = starved.length;
    if (!starved.length) return;

    await Promise.all(starved.map(fill));
  }

  function start() {
    if (window.requestIdleCallback) {
      window.requestIdleCallback(watch, { timeout: 2000 });
      return;
    }
    setTimeout(watch, 0);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
