// Paste into the browser console on the landing page, a collection page, or any
// page that renders product cards.
//
// It answers the one question the theme cannot answer from a card alone: for
// each product shown here, does EasyStore report a remaining quantity, and did
// the card print it the way that product's own page does?
//
// Every surface renders the notice element, empty and hidden while there is
// nothing to print, and carries the stock the snippet counted. A count of 0
// means the platform sent no stock with that product; a count above the
// threshold that printed nothing is correct. An element missing altogether
// means the page predates the theme this probe was written for.
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
      // What the snippet counted. 0 means the platform sent no stock with this
      // product; a positive count that printed nothing means the threshold, or
      // the series match, kept it quiet.
      cardRemaining: notice ? notice.dataset.lowInventoryRemaining ?? '(older theme)' : '-',
    });
  }

  console.log(`--- ${cards.length} cards, ${seen.size} products ---`);

  // The page-level reading, printed again at the end. One silent card cannot
  // say whether the listing carried no stock or the card failed to recognise
  // the product; a page where no card at all printed a count can.
  const printedOnThisPage = Array.from(seen.values())
    .flat()
    .filter(entry => entry.cardNotice !== '(no element)' && entry.cardNotice !== '(empty)').length;

  for (const [handle, entries] of seen) {
    console.log(`\n=== ${handle || '(no handle in the card link)'} ===`);
    out('title on the card', entries[0].title);
    out('cards on this page', entries.length);
    entries.forEach((entry, index) => {
      out(`  card ${index + 1} printed`, entry.cardNotice);
      out(`  card ${index + 1} threshold attribute`, entry.cardThreshold);
      out(`  card ${index + 1} stock the card counted`, entry.cardRemaining);
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
      const counted = entries.map(entry => entry.cardRemaining).join(', ');
      if (entries.every(entry => entry.cardRemaining === '0')) {
        console.log(`     The card counted ${counted}: EasyStore sent no stock with this product in`);
        console.log('     the listing, so no card can print it. The product page reads a fuller');
        console.log('     object, which is why it has a number to show.');
      } else {
        console.log(`     The card counted ${counted}, so it had the stock and chose not to print:`);
        console.log('     compare its threshold attribute, where "all" means the series was');
        console.log('     recognised and 5 means it was not.');
      }
    } else if (cardPrinted && pagePrinted) {
      console.log('  -> both surfaces print a count.');
    } else {
      console.log('  -> neither surface prints a count; check the quantities above against the threshold.');
    }
  }

  console.log('\n--- verdict for this page ---');
  out('cards that printed a count', `${printedOnThisPage} of ${cards.length}`);
  const counted = Array.from(seen.values()).flat()
    .filter(entry => entry.cardRemaining !== '0' && entry.cardRemaining !== '-'
      && entry.cardRemaining !== '(older theme)').length;
  out('cards that counted any stock', `${counted} of ${cards.length}`);
  if (counted === 0) {
    console.log('No card was given any stock to print. That is the product data, not the theme:');
    console.log('EasyStore serializes less of a product into a collection listing than into the');
    console.log('product page, and nothing in the theme can print a number it was never sent.');
  } else if (printedOnThisPage === 0) {
    console.log('Cards were given stock and printed none of it, so every one of them is above the');
    console.log('threshold. For a product that should print at every quantity, its threshold');
    console.log('attribute above says whether it was recognised: "all" yes, 5 no.');
  } else {
    console.log('Cards are printing. A card that stayed silent either has more stock than the');
    console.log('threshold - which is correct - or was not recognised as a product that prints at');
    console.log('every quantity; its threshold attribute above says which.');
  }
})();
