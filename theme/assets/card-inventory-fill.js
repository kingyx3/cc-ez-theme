// Fills in a card's remaining-stock count when EasyStore did not send one.
//
// A collection listing does not carry the same product object a product page
// does, and it is not consistent about it: the same product is serialized with
// its stock in one collection and without it in another. The snippet can only
// print what it was given, so a card for a product that is meant to advertise
// its stock at every quantity can come out empty while its product page prints
// a count.
//
// Only those cards are filled in. They are the ones the theme promises a count
// for, they are rare on a page, and each one costs a request; a card that is
// merely near its threshold is left alone rather than fetching every card on
// the page to find out whether it was close.
//
// snippets/low-inventory-notice.liquid renders the two attributes this reads:
// a threshold of 'all' marks a product that prints at every quantity, and a
// remaining of 0 means the platform sent nothing to print.
(() => {
  const STARVED =
    '[data-low-inventory-notice][data-low-inventory-threshold="all"][data-low-inventory-remaining="0"]';
  // A ceiling on the requests one page may spend on this, in case a collection
  // of these products is ever rendered in full.
  const MOST_REQUESTS = 4;

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

  function print(notice, remaining) {
    const template = window.purchaseStrings && window.purchaseStrings.lowInventory;
    if (!template) return;

    notice.textContent = String(template).replace('__COUNT__', remaining);
    notice.dataset.lowInventoryRemaining = String(remaining);
    // So the probe can say which of the three routes produced this number.
    notice.dataset.lowInventorySource = 'fetch';
    notice.classList.remove('hidden');
    notice.removeAttribute('hidden');
  }

  async function fill() {
    const starved = Array.from(document.querySelectorAll(STARVED)).slice(0, MOST_REQUESTS);

    for (const notice of starved) {
      const handle = handleFor(notice);
      if (!handle) continue;

      try {
        const remaining = await remainingFor(handle);
        // A product whose stock the platform does not track anywhere reports
        // nothing here either, and inventing a count for it is exactly what
        // the snippet refuses to do.
        if (remaining > 0) print(notice, remaining);
      } catch (error) {
        // A card that cannot be filled in stays as the snippet left it, which
        // is empty and hidden. Nothing else on the page depends on this.
      }
    }
  }

  function start() {
    if (window.requestIdleCallback) {
      window.requestIdleCallback(fill, { timeout: 2000 });
      return;
    }
    setTimeout(fill, 0);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
