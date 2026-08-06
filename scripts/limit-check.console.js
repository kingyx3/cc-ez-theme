(async () => {
  const config = window.customerOrderLimitsV2;
  const api = window.CustomerOrderLimits;
  const out = (label, value) => console.log(label.padEnd(26), value);

  if (!config) return console.log('LIMITS: not on this page — no rule configured for this product, or the theme predates this feature.');
  if (!api) return console.log('LIMITS: customer-order-limits.js did not run. Check the console for an earlier error.');

  const hasDiagnostics = Boolean(config.diagnostics);
  const hasHistoryLoader = typeof api.historyState === 'function' && typeof api.loadHistory === 'function';
  const state = () => (hasHistoryLoader ? api.historyState() : 'not in this build');
  if (!hasDiagnostics || !hasHistoryLoader) {
    console.log('BUILD IS OLD: this page is missing', [
      !hasDiagnostics ? 'diagnostics' : null,
      !hasHistoryLoader ? 'the history loader' : null,
    ].filter(Boolean).join(' and ') + '. Upload the current artifact, then run this again.');
  }

  const handle = (location.pathname.match(/\/products\/([^/?#]+)/) || [])[1] || '';
  const rule = api.ruleFor(handle);
  const d = config.diagnostics || {};

  console.log('--- sign in ---');
  out('liquid says signed in', config.customerAuthenticated);
  out('body class', document.body.classList.contains('customer-logged-in'));
  out('header marker', document.querySelector('[data-customer-authenticated]')?.dataset.customerAuthenticated ?? 'none');

  console.log('--- history the page read ---');
  out('lineItemsSeen', d.lineItemsSeen ?? 'not in this build');
  out('identifiers', JSON.stringify(d.identifiers ?? 'not in this build'));
  out('ordersSeen', d.ordersSeen ?? 'not in this build');
  out('historyState', state());

  if (hasHistoryLoader && (state() === 'unknown' || state() === 'pending')) {
    console.log('loading history…');
    await api.loadHistory();
    out('historyState after load', state());
  }

  console.log('--- this product ---');
  out('handle', handle);
  if (!rule) {
    console.log('LIMITS: no limit configured for this handle. Check it matches customer-order-limit-config.liquid exactly.');
  } else {
    const fresh = api.ruleFor(handle);
    out('maximum', fresh.maximum);
    out('purchased (past orders)', fresh.purchased);
    out('in cart', fresh.cartQuantity);
    out('can still add', api.remainingForHandle(handle));
    out('counted since', fresh.limitWindowLabel || 'all orders');
  }

  console.log('--- account payload ---');
  try {
    const html = await (await fetch('/account/orders', { credentials: 'same-origin' })).text();
    const el = new DOMParser().parseFromString(html, 'text/html')
      .getElementById('customer-order-limit-history');
    if (!el) console.log('payload MISSING at /account/orders — the account template is not published, or that URL redirected.');
    else {
      const payload = JSON.parse(el.textContent);
      out('payload lines', payload.lines.length);
      out('matching this handle', payload.lines.filter((l) => l[0] === handle || l[1] === handle).length);
    }
  } catch (error) {
    console.log('payload fetch failed:', error.message);
  }

  console.log('--- verdict ---');
  const signedIn = config.customerAuthenticated || document.body.classList.contains('customer-logged-in');
  if (!signedIn) console.log('GUEST: limits do not apply. Purchase clicks should go to the login page.');
  else if (!rule) console.log('NOT LIMITED: this product has no configured limit.');
  else if (!hasHistoryLoader) console.log('CANNOT TELL: this build has no history loader. Upload the current artifact and run this again.');
  else if (state() === 'unavailable') console.log('BROKEN: history could not be read or loaded. Only the current cart is capped.');
  else if (api.ruleFor(handle).purchased > 0) console.log('WORKING: past orders are counted for this product.');
  else console.log('NO PURCHASES COUNTED: either this customer has not bought it before, or the identifiers do not match. Compare "identifiers" and "payload lines" above with the configured handle.');
})();
