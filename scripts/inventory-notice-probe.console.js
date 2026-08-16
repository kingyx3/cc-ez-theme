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

  // Why a notice that carries text might still not be seen.
  function onScreen(notice) {
    const style = getComputedStyle(notice);
    if (notice.hasAttribute('hidden')) return 'no - hidden attribute';
    if (style.display === 'none') return 'no - display:none';
    if (style.visibility === 'hidden') return 'no - visibility:hidden';
    if (Number(style.opacity) === 0) return 'no - opacity:0';

    const rect = notice.getBoundingClientRect();
    if (!rect.width || !rect.height) return `no - no size (${Math.round(rect.width)}x${Math.round(rect.height)})`;
    if (!notice.offsetParent && style.position !== 'fixed') return 'no - an ancestor is not laid out';

    // An ancestor that hides it, which the element's own style will not show.
    for (let parent = notice.parentElement; parent; parent = parent.parentElement) {
      const parentStyle = getComputedStyle(parent);
      if (parentStyle.display === 'none') return `no - ${describe(parent)} is display:none`;
      if (parentStyle.visibility === 'hidden') return `no - ${describe(parent)} is visibility:hidden`;
      if (Number(parentStyle.opacity) === 0) return `no - ${describe(parent)} is opacity:0`;
      const parentRect = parent.getBoundingClientRect();
      if (parentStyle.overflow !== 'visible' && (rect.bottom > parentRect.bottom + 1 || rect.right > parentRect.right + 1)) {
        return `no - clipped by ${describe(parent)}`;
      }
    }
    return `yes (${Math.round(rect.width)}x${Math.round(rect.height)})`;
  }

  function describe(element) {
    const classes = String(element.className || '').trim().split(/\s+/).filter(Boolean).slice(0, 2);
    return element.tagName.toLowerCase() + (classes.length ? `.${classes.join('.')}` : '');
  }
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
      // listing = the count came with the card, lookup = the snippet looked the
      // product up, fetch = card-inventory-fill.js fetched it after load.
      cardSource: notice ? notice.dataset.lowInventorySource ?? '(older theme)' : '-',
      // Text in the markup is not the same as text a shopper can see. This says
      // whether the element is actually painted, and what is hiding it if not.
      cardOnScreen: notice ? onScreen(notice) : '-',
      // The handle the snippet had to look the product up by. Blank means it
      // never made a lookup because it had nothing to look up.
      cardHandle: notice ? notice.dataset.lowInventoryHandle ?? '(older theme)' : '-',
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
      out(`  card ${index + 1} where that came from`, entry.cardSource);
      out(`  card ${index + 1} visible to a shopper`, entry.cardOnScreen);
      if (entry.cardRemaining === '0') {
        out(`  card ${index + 1} handle it could look up`, entry.cardHandle || '(none - no lookup was made)');
      }
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

  // When a card was given no stock, the theme has nothing to print and the only
  // remaining question is whether the browser could fetch the number instead.
  // This asks the store, once, for one such product.
  const starved = Array.from(seen.entries()).find(([handle, entries]) =>
    handle && entries.every(entry => entry.cardRemaining === '0'));
  if (starved) {
    console.log(`\n--- can the browser fetch what the card was not given? (${starved[0]}) ---`);
    for (const path of [`/products/${starved[0]}.json`, `/products/${starved[0]}/product_quickview_html`]) {
      try {
        const response = await fetch(path, { credentials: 'same-origin' });
        if (!response.ok) {
          out(path, `HTTP ${response.status}`);
          continue;
        }
        const body = await response.text();
        const found = body.match(/inventory_quantity["']?\s*[:=]\s*["']?(-?\d+)/)
          || body.match(/data-inventory-quantity=["'](-?\d+)["']/);
        out(path, found ? `reports ${found[1]} - usable` : 'no inventory in the body');
        out('  bytes', body.length);
      } catch (error) {
        out(path, `failed: ${error.message}`);
      }
    }
  }

  console.log('\n--- the fill-in script ---');
  const tag = document.querySelector('script[src*="card-inventory-fill"]');
  out('loaded by the page', tag ? 'yes' : 'NO - the layout is not serving it');
  if (tag) {
    // The file cannot be read from here: theme assets are served from another
    // origin, and a cross-origin fetch of them is blocked. The stamp EasyStore
    // puts on the URL is the useful part anyway. Compare it between two pages:
    // a page whose stamp is older is serving HTML rendered by an older theme,
    // which is a cached page rather than anything the theme did wrong.
    const stamp = (tag.src.match(/[?&]t=(\d+)/) || [])[1];
    out('asset stamp on this page', stamp || '(none on the URL)');
    if (stamp) out('  which is', new Date(Number(stamp) * 1000).toISOString());
    out('asset origin', new URL(tag.src, location.href).origin);
  }
  const fillState = window.cardInventoryFill;
  if (!fillState) {
    out('what it did', tag ? 'it did not run - check the console for an error' : 'not loaded');
  } else {
    out('what it did', `ran=${fillState.ran} starved=${fillState.starved} fetched=${fillState.fetched} filled=${fillState.filled}`);
    if (fillState.errors.length) out('errors', fillState.errors.slice(0, 4).join(' | '));
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
