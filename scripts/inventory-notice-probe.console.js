// Paste into the browser console on the landing page, a collection page, or any
// page that renders product cards.
//
// It answers the one question the theme cannot answer from a card alone: for
// each product shown here, does EasyStore report a remaining quantity, and did
// the card print it the way that product's own page does?
//
// A card only renders the notice element when it has a count to print, so an
// absent element means the snippet found no stock to claim - not that CSS hid
// it. The product page always renders the element, so its threshold attribute
// and quantity are read from there and compared.
(async () => {
  const out = (label, value) => console.log(String(label).padEnd(34), value);
  const cards = Array.from(document.querySelectorAll('.product-card-wrapper'));

  if (!cards.length) return console.log('NOTICE PROBE: no product cards on this page.');

  const seen = new Map();
  for (const card of cards) {
    const link = card.querySelector('a.full-unstyled-link, a[href*="/products/"]');
    const href = link ? link.getAttribute('href') || '' : '';
    const handle = (href.match(/\/products\/([^/?#]+)/) || [])[1] || '';
    const notice = card.querySelector('[data-low-inventory-notice]');
    const title = (card.querySelector('.card-information__text') || {}).textContent || '';

    if (!seen.has(handle)) seen.set(handle, []);
    seen.get(handle).push({
      title: title.trim(),
      cardNotice: notice ? notice.textContent.trim() || '(empty)' : '(no element)',
      cardThreshold: notice ? notice.dataset.lowInventoryThreshold : '-',
    });
  }

  console.log(`--- ${cards.length} cards, ${seen.size} products ---`);

  for (const [handle, entries] of seen) {
    console.log(`\n=== ${handle || '(no handle in the card link)'} ===`);
    out('title on the card', entries[0].title);
    out('cards on this page', entries.length);
    entries.forEach((entry, index) => {
      out(`  card ${index + 1} printed`, entry.cardNotice);
      out(`  card ${index + 1} threshold attribute`, entry.cardThreshold);
    });

    if (!handle) {
      console.log('  -> the card link carries no handle, so the product page cannot be compared.');
      continue;
    }

    let page;
    try {
      const response = await fetch(`/products/${handle}`, { credentials: 'same-origin' });
      if (!response.ok) {
        out('product page', `HTTP ${response.status}`);
        continue;
      }
      page = new DOMParser().parseFromString(await response.text(), 'text/html');
    } catch (error) {
      out('product page', `could not be read: ${error.message}`);
      continue;
    }

    const pageNotice = page.querySelector('[data-low-inventory-notice]');
    const quantities = Array.from(page.querySelectorAll('[data-inventory-quantity]'))
      .map(option => option.dataset.inventoryQuantity)
      .filter(value => value !== '');

    out('product page printed', pageNotice ? pageNotice.textContent.trim() || '(hidden, empty)' : '(no element)');
    out('product page threshold attribute', pageNotice ? pageNotice.dataset.lowInventoryThreshold : '-');
    out('quantities EasyStore reports', quantities.length ? quantities.join(', ') : '(none reported)');

    // The reading, so the numbers above do not have to be interpreted by hand.
    const cardPrinted = entries.some(entry => entry.cardNotice !== '(no element)' && entry.cardNotice !== '(empty)');
    const pagePrinted = Boolean(pageNotice && pageNotice.textContent.trim());
    if (!quantities.length && !pagePrinted) {
      console.log('  -> EasyStore reports no quantity for this product, so no surface can print one.');
    } else if (pagePrinted && !cardPrinted) {
      console.log('  -> THE DISAGREEMENT: the product page prints a count and the card does not.');
      console.log('     Compare the threshold attributes above: "all" on the page and 5 on the card');
      console.log('     means the card did not recognise the series from the handle in its link;');
      console.log('     no element on the card at all means the card counted no stock from the');
      console.log('     product object it was given.');
    } else if (cardPrinted && pagePrinted) {
      console.log('  -> both surfaces print a count.');
    } else {
      console.log('  -> neither surface prints a count; check the quantities above against the threshold.');
    }
  }
})();
