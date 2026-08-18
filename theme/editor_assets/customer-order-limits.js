(() => {
  'use strict';

  const source = window.customerOrderLimitsV2;
  if (!source || !source.rules || Object.keys(source.rules).length === 0) return;

  const quantity = (value, fallback = 0) => {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
  };

  const normalizeHandle = (value) => {
    try {
      return decodeURIComponent(String(value || '')).trim().toLowerCase();
    } catch (_error) {
      return String(value || '').trim().toLowerCase();
    }
  };

  const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

  const nowMs = () => new Date().getTime();

  // EasyStore's `json` filter renders a Liquid boolean as 1 or 0, so a strict
  // `=== true` read of anything the snippets publish is false for a signed-in
  // customer. Every flag from Liquid goes through here.
  const truthy = (value) => (
    value === true || value === 1 || value === '1' || value === 'true'
  );

  const unitLabel = (value) => {
    const count = quantity(value, 0);
    return `${count} unit${count === 1 ? '' : 's'}`;
  };

  // A refresh date is store configuration, not something a shopper needs to
  // reason about, so no message names it. The resolved window still travels on
  // the rule as `refreshAt` and `limitWindowLabel` for console verification.

  const rules = {};
  Object.entries(source.rules).forEach(([handle, rule]) => {
    const normalized = normalizeHandle(handle);
    if (normalized) rules[normalized] = rule;
  });
  source.rules = rules;

  const productHandleFromUrl = (value) => {
    const match = String(value || '').match(/\/products\/([^/?#]+)/i);
    return match ? normalizeHandle(match[1]) : '';
  };

  const productHandle = (element) => {
    if (!element) return '';
    const owner = element.closest('[data-product-handle]');
    if (owner && owner.dataset.productHandle) {
      return normalizeHandle(owner.dataset.productHandle);
    }

    const link = element.querySelector?.('a[href*="/products/"]')
      || element.parentElement?.querySelector?.('a[href*="/products/"]');
    const linkedHandle = productHandleFromUrl(link?.getAttribute('href'));
    if (linkedHandle) return linkedHandle;

    return productHandleFromUrl(window.location.pathname);
  };

  const ruleFor = (handle) => rules[normalizeHandle(handle)] || null;

  const customerAuthenticated = truthy(source.customerAuthenticated);

  // `body.customer-logged-in` comes from the layout and the markers come from
  // the header, both rendered by the same `customer` check the rest of the theme
  // uses for its account links, so together they are the reliable signal for
  // sign-in state. The Liquid flag above reports only what the limit snippet
  // itself could see, so it counts as a signed-in hint and never as proof that a
  // shopper is signed out. Signing out is only ever concluded from the header's
  // signed-out marker, never from missing markup.
  const SIGNED_IN_MARKUP = 'body.customer-logged-in, [data-customer-authenticated="true"], a[href^="/account/logout"]';
  const SIGNED_OUT_MARKUP = '[data-customer-authenticated="false"]';

  const onAccountPage = () => (
    /^\/account(\/|$)/.test(String(window.location.pathname || ''))
  );

  // Cached once the page proves sign-in state either way. While the state is
  // unproven the answer stays "not signed out" so no purchase is ever
  // redirected on a guess: a wrong redirect breaks buying for real customers.
  let signedOut = null;
  const shopperSignedOut = () => {
    if (signedOut !== null) return signedOut;
    if (customerAuthenticated || onAccountPage()) {
      signedOut = false;
      return signedOut;
    }
    if (document.querySelector(SIGNED_IN_MARKUP)) {
      signedOut = false;
      return signedOut;
    }
    if (!document.querySelector(SIGNED_OUT_MARKUP)) return false;
    signedOut = true;
    return signedOut;
  };

  // Limits count units per customer across orders, so they only exist for a
  // signed-in customer. A shopper proven to be signed out is sent to sign in
  // instead of being measured against a limit they cannot own yet.
  const loginRequiredForRule = (rule) => Boolean(rule) && shopperSignedOut();

  const loginRequiredForHandle = (handle) => loginRequiredForRule(ruleFor(handle));

  const loginRedirectUrl = () => {
    const target = `${window.location.pathname}${window.location.search}`;
    return `/account/login?redirect_uri=${encodeURIComponent(target)}`;
  };

  // What the shopper was trying to buy when they were sent to sign in. The
  // click cannot survive the round trip through EasyStore's login, so the
  // attempt is recorded here and answered on the page they come back to: a
  // customer whose allowance is already spent would otherwise return to a page
  // that says nothing about it until they press the button a second time.
  const INTENT_KEY = 'cc:pending-purchase-intent';
  // The same window the login redirect keeps its target for, so an attempt and
  // the trip back from login expire together.
  const INTENT_MAX_AGE_MS = 1800000;

  // Storage is unavailable in some privacy modes. The attempt is then simply
  // not replayed, exactly as it is not replayed today.
  const rememberPurchaseIntent = (intent) => {
    if (!intent) return;
    try {
      window.sessionStorage.setItem(INTENT_KEY, JSON.stringify({
        handle: normalizeHandle(intent.handle),
        quantity: Math.max(1, quantity(intent.quantity, 1)),
        surface: String(intent.surface || 'product'),
        storedAt: nowMs(),
      }));
    } catch (_error) {
      /* the attempt is not recorded */
    }
  };

  // Read once and removed as it is read, so an attempt answered on one page can
  // never resurface on the next one.
  const takePurchaseIntent = () => {
    let raw = null;
    try {
      raw = window.sessionStorage.getItem(INTENT_KEY);
      window.sessionStorage.removeItem(INTENT_KEY);
    } catch (_error) {
      return null;
    }
    if (!raw) return null;
    try {
      const intent = JSON.parse(raw);
      const storedAt = quantity(intent && intent.storedAt, 0);
      if (!storedAt || storedAt + INTENT_MAX_AGE_MS < nowMs()) return null;
      return {
        handle: normalizeHandle(intent && intent.handle),
        quantity: Math.max(1, quantity(intent && intent.quantity, 1)),
        surface: String((intent && intent.surface) || 'product'),
      };
    } catch (_error) {
      return null;
    }
  };

  const redirectToLogin = (intent = null) => {
    if (!shopperSignedOut()) return false;
    rememberPurchaseIntent(intent);
    window.location.assign(loginRedirectUrl());
    return true;
  };

  const currentCartTotals = () => {
    const totals = {};
    Object.entries(rules).forEach(([handle, rule]) => {
      totals[handle] = quantity(rule.cartQuantity, 0);
    });
    return totals;
  };

  const cartTotalsFromForm = (form) => {
    const totals = {};
    if (!form) return totals;

    form.querySelectorAll('tr.cart-item').forEach((row) => {
      const input = row.querySelector('[name="updates[]"]');
      const handleInput = row.querySelector('[name="product_handles[]"]');
      const handle = normalizeHandle(
        handleInput?.value || row.dataset.productHandle || productHandle(row)
      );
      if (!handle || !input) return;
      totals[handle] = (totals[handle] || 0) + quantity(input.value, 0);
    });

    return totals;
  };

  const allowedCartQuantity = (rule) => quantity(rule && rule.allowedCartQuantity, 0);

  const loginRequiredForCart = (totals = null) => (
    Object.entries(rules).some(([handle, rule]) => {
      if (!loginRequiredForRule(rule)) return false;
      const cartQuantity = totals && hasOwn(totals, handle)
        ? quantity(totals[handle], 0)
        : quantity(rule.cartQuantity, 0);
      return cartQuantity > 0;
    })
  );

  // Returns null when no limit applies to this handle, either because the
  // product is unlimited or because the shopper has to sign in first.
  const remainingForHandle = (handle, totals = null) => {
    const normalized = normalizeHandle(handle);
    const rule = ruleFor(normalized);
    if (!rule || loginRequiredForRule(rule)) return null;
    const cartQuantity = totals && hasOwn(totals, normalized)
      ? quantity(totals[normalized], 0)
      : quantity(rule.cartQuantity, 0);
    return Math.max(0, allowedCartQuantity(rule) - cartQuantity);
  };

  // Built from live numbers rather than the server-rendered `rule.message`: once
  // the shopper adds or removes a unit the rendered copy is stale, and saying
  // "you can add up to 1 more" to someone who cannot add anything is worse than
  // saying nothing.
  const messageFor = (rule, requestedQuantity, remaining) => {
    const maximum = quantity(rule && rule.maximum, 0);
    const purchased = quantity(rule && rule.purchased, 0);
    const cartQuantity = quantity(rule && rule.cartQuantity, 0);
    const limitSuffix = `The limit is ${unitLabel(maximum)} per customer across orders.`;

    if (remaining <= 0) {
      if (purchased > 0 && cartQuantity > 0) {
        return `Maximum quantity reached. You have already purchased ${unitLabel(purchased)} and have ${unitLabel(cartQuantity)} in your cart. ${limitSuffix}`;
      }
      if (cartQuantity > 0) {
        return `Maximum quantity reached. You already have ${unitLabel(cartQuantity)} in your cart. ${limitSuffix}`;
      }
      if (purchased > 0) {
        return `Customer purchase limit reached. You have already purchased ${unitLabel(purchased)} of the ${unitLabel(maximum)} allowed per customer across orders.`;
      }
      return `Maximum quantity reached. ${limitSuffix}`;
    }

    if (requestedQuantity > remaining) {
      return `Customer purchase limit exceeded. You can add up to ${unitLabel(remaining)} more. ${limitSuffix}`;
    }
    return `You can add up to ${unitLabel(remaining)} more. ${limitSuffix}`;
  };

  const cartMessageFor = (rule, allowed) => {
    const maximum = quantity(rule && rule.maximum, 0);
    const purchased = quantity(rule && rule.purchased, 0);
    const limitSuffix = `The limit is ${unitLabel(maximum)} per customer across orders.`;

    if (allowed <= 0) {
      if (purchased > 0) {
        return `Customer purchase limit reached. You have already purchased ${unitLabel(purchased)} of the ${unitLabel(maximum)} allowed, so remove this product before checkout.`;
      }
      return `Customer purchase limit reached. Remove this product before checkout. ${limitSuffix}`;
    }
    return `Customer purchase limit exceeded. Reduce this product to ${unitLabel(allowed)} before checkout. ${limitSuffix}`;
  };

  // --- purchase history ------------------------------------------------------
  // `customer.orders` carries line items on the account order pages, but a
  // product or cart page can receive the orders list without them. The inline
  // Liquid pass then counts zero units and the limit silently stops applying
  // across orders. When the page reports that it read no line items, history is
  // treated as unknown rather than as "nothing purchased", and is loaded from
  // the account order page, which publishes it as JSON.
  const HISTORY_URL = '/account/orders';
  const HISTORY_PAYLOAD_ID = 'customer-order-limit-history';
  const HISTORY_CACHE_KEY = 'customerOrderLimitHistory';
  const HISTORY_MAX_AGE_MS = 300000;

  const diagnostics = source.diagnostics || {};
  // Only line items actually read prove the page saw history. Zero orders is
  // ambiguous for a signed-in shopper — no orders, or orders not loaded here —
  // and guessing "no orders" is what let the limit lapse.
  const inlineHistoryRead = quantity(diagnostics.lineItemsSeen, 0) > 0;

  // 'inline'      the page read history itself, nothing to load
  // 'unknown'     history is missing and has not been loaded yet
  // 'pending'     a load is in flight
  // 'loaded'      history came from the account order page
  // 'unavailable' the load failed; limits fall back to cart-only enforcement
  let historyState = inlineHistoryRead ? 'inline' : 'unknown';
  let historyRequest = null;

  const historyKnown = () => historyState === 'inline' || historyState === 'loaded';
  const historyResolving = () => historyState === 'unknown' || historyState === 'pending';

  const historyLines = (payload) => (
    Array.isArray(payload && payload.lines) ? payload.lines : []
  );

  // The order list is tab filtered and paginated, so one request only covers the
  // default tab's first page — a live store returned zero lines that way. Every
  // tab that reports orders is walked, following its pages, with a request cap so
  // a large history cannot turn into an unbounded crawl.
  const HISTORY_MAX_REQUESTS = 12;

  const historyUrlsFrom = (payload, fetched) => {
    const urls = [];
    const push = (url) => {
      if (url && !fetched.has(url) && !urls.includes(url)) urls.push(url);
    };

    // A tab's count is not a reason to skip it: the live store rendered a count
    // for the tab being viewed and nothing for the rest, so trusting the count
    // would skip every tab that actually held the orders. Tabs reporting orders
    // are simply visited first, and the request cap bounds the rest.
    const tabs = Array.isArray(payload && payload.tabs) ? payload.tabs : [];
    const visitable = tabs
      .map((tab) => ({
        status: String((tab && tab.status) || '').trim(),
        count: quantity(tab && tab.count, 0),
      }))
      // Cancelled orders are excluded from the tally anyway.
      .filter((tab) => tab.status && !/cancel/i.test(tab.status))
      .filter((tab) => tab.status !== String((payload && payload.currentTab) || ''));
    visitable
      .slice()
      .sort((left, right) => right.count - left.count)
      .forEach((tab) => push(`${HISTORY_URL}?filter=${encodeURIComponent(tab.status)}`));

    push(String((payload && payload.nextUrl) || '').trim());
    return urls;
  };

  const mergeHistory = (payloads) => {
    const seen = new Set();
    const lines = [];
    payloads.forEach((payload) => {
      historyLines(payload).forEach((line) => {
        if (!Array.isArray(line)) return;
        // The same order shows up under more than one tab; its lines are
        // identical, so an identical line is the same purchase, counted once.
        const key = line.slice(0, 7).join('|');
        if (seen.has(key)) return;
        seen.add(key);
        lines.push(line);
      });
    });
    return { lines, truncated: payloads.some((payload) => payload && payload.truncated) };
  };

  // Order line items always carry a variant id — this theme's own order pages
  // read it — while a handle or SKU is not guaranteed on every store. The current
  // product publishes its ids, so history still matches when the strings do not.
  const idText = (value) => String(value === null || value === undefined ? '' : value).trim();
  const pageProduct = source.pageProduct || {};
  const pageProductHandle = normalizeHandle(pageProduct.handle);
  const pageProductSku = normalizeHandle(pageProduct.sku);
  const pageProductId = idText(pageProduct.productId);
  const pageVariantIds = new Set(
    (Array.isArray(pageProduct.variantIds) ? pageProduct.variantIds : [])
      .map(idText)
      .filter(Boolean),
  );

  const purchasedFromLines = (handle, rule, lines) => {
    const normalized = normalizeHandle(handle);
    const windowStart = quantity(rule && rule.windowStart, 0);
    // The published ids describe one product, so they only identify the rule
    // configured for that product — never another slot's handle.
    const idsIdentifyRule = Boolean(normalized)
      && (normalized === pageProductHandle || normalized === pageProductSku);
    return lines.reduce((total, line) => {
      if (!Array.isArray(line)) return total;
      const lineHandle = normalizeHandle(line[0]);
      const lineSku = normalizeHandle(line[1]);
      const matchedById = idsIdentifyRule && (
        (Boolean(pageProductId) && idText(line[5]) === pageProductId)
        || pageVariantIds.has(idText(line[6]))
      );
      if (lineHandle !== normalized && lineSku !== normalized && !matchedById) return total;
      if (quantity(line[2], 0) < windowStart) return total;
      return total + quantity(line[3], 0);
    }, 0);
  };

  // Kept so a console check can show exactly which lines were read and compare
  // them with the configured handle, instead of guessing why a count is zero.
  let appliedHistoryLines = [];

  const applyHistory = (payload) => {
    const lines = historyLines(payload);
    appliedHistoryLines = lines;
    Object.entries(rules).forEach(([handle, rule]) => {
      const purchased = purchasedFromLines(handle, rule, lines);
      const maximum = quantity(rule.maximum, 0);
      rule.purchased = purchased;
      rule.allowedCartQuantity = Math.max(0, maximum - purchased);
    });
    commitCartTotals(currentCartTotals());
    decorateCartForm(document.getElementById('cart-form'));
    document.dispatchEvent(new CustomEvent('customer-order-limits:history'));
    document.dispatchEvent(new CustomEvent('customer-order-limits:cart-sync'));
  };

  const cachedHistory = () => {
    try {
      const raw = window.sessionStorage?.getItem(HISTORY_CACHE_KEY);
      if (!raw) return null;
      const cached = JSON.parse(raw);
      const sameCustomer = String(cached.customer || '')
        === String(source.customerId || cached.customer || '');
      const fresh = quantity(cached.storedAt, 0) + HISTORY_MAX_AGE_MS > nowMs();
      return sameCustomer && fresh ? cached.payload : null;
    } catch (_error) {
      return null;
    }
  };

  const storeHistory = (payload) => {
    try {
      window.sessionStorage?.setItem(HISTORY_CACHE_KEY, JSON.stringify({
        customer: payload && payload.customer,
        storedAt: nowMs(),
        payload,
      }));
    } catch (_error) {
      // A full or unavailable sessionStorage only costs an extra request.
    }
  };

  const parseHistoryDocument = (html) => {
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    const payload = parsed.getElementById(HISTORY_PAYLOAD_ID);
    if (!payload) throw new Error('history payload missing');
    return JSON.parse(payload.textContent || '{}');
  };

  // Loading needs fetch and DOMParser. Without them the limit stays cart-only
  // rather than throwing from a purchase handler or from page load.
  const historySupported = () => (
    typeof fetch === 'function'
    && typeof DOMParser === 'function'
    && typeof Promise === 'function'
  );

  const loadHistory = () => {
    if (historyKnown() || historyState === 'unavailable') return Promise.resolve();
    if (shopperSignedOut() || !historySupported()) {
      historyState = 'unavailable';
      return Promise.resolve();
    }
    if (historyRequest) return historyRequest;

    const cached = cachedHistory();
    if (cached) {
      historyState = 'loaded';
      applyHistory(cached);
      return Promise.resolve();
    }

    historyState = 'pending';

    const fetchPayload = (url) => fetch(url, {
      credentials: 'same-origin',
      headers: { Accept: 'text/html' },
    })
      .then((response) => {
        if (!response.ok) throw new Error(`history request failed: ${response.status}`);
        return response.text();
      })
      .then(parseHistoryDocument);

    const walk = (url, fetched, collected) => {
      if (fetched.size >= HISTORY_MAX_REQUESTS) return Promise.resolve(collected);
      fetched.add(url);
      return fetchPayload(url).then((payload) => {
        collected.push(payload);
        const next = historyUrlsFrom(payload, fetched);
        return next.reduce(
          (chain, candidate) => chain.then((soFar) => (
            fetched.has(candidate) || fetched.size >= HISTORY_MAX_REQUESTS
              ? soFar
              : walk(candidate, fetched, soFar)
          )),
          Promise.resolve(collected)
        );
      });
    };

    let started;
    try {
      started = walk(HISTORY_URL, new Set(), []);
    } catch (_error) {
      historyState = 'unavailable';
      return Promise.resolve();
    }

    historyRequest = started
      .then((payloads) => {
        if (!payloads.length) throw new Error('history payload missing');
        const merged = mergeHistory(payloads);
        const payload = {
          customer: payloads[0].customer,
          renderedAt: payloads[0].renderedAt,
          truncated: merged.truncated,
          lines: merged.lines,
        };
        historyState = 'loaded';
        storeHistory(payload);
        applyHistory(payload);
      })
      .catch(() => {
        // Never block buying because history could not be read.
        historyState = 'unavailable';
        document.dispatchEvent(new CustomEvent('customer-order-limits:history-unavailable'));
      })
      .then(() => { historyRequest = null; });

    return historyRequest;
  };

  // A purchase attempt made while history is still unknown must not be measured
  // against an allowance that assumes nothing was ever bought. The attempt is
  // held, history is loaded, and the shopper is told to try again a moment later.
  const HISTORY_PENDING_MESSAGE = 'Checking your purchase limit for this product. One moment, then try again.';

  const historyBlocks = (handle) => {
    const rule = ruleFor(handle);
    if (!rule || loginRequiredForRule(rule)) return false;
    if (!historyResolving() || !historySupported()) return false;
    loadHistory();
    return historyResolving();
  };

  const historyBlocksCart = (totals = null) => (
    Object.entries(rules).some(([handle, rule]) => {
      const cartQuantity = totals && hasOwn(totals, handle)
        ? quantity(totals[handle], 0)
        : quantity(rule.cartQuantity, 0);
      return cartQuantity > 0 && historyBlocks(handle);
    })
  );

  const additionViolation = (handle, requestedQuantity) => {
    const normalized = normalizeHandle(handle);
    const rule = ruleFor(normalized);
    if (!rule || loginRequiredForRule(rule)) return null;
    const requested = Math.max(1, quantity(requestedQuantity, 1));
    const remaining = remainingForHandle(normalized);
    if (requested <= remaining) return null;
    return {
      handle: normalized,
      requestedQuantity: requested,
      remaining,
      rule,
      message: messageFor(rule, requested, remaining),
    };
  };

  const cartQuantityForHandle = (handle) => {
    const rule = ruleFor(handle);
    return rule ? quantity(rule.cartQuantity, 0) : 0;
  };

  const quantityLimitForHandle = (handle) => {
    const normalized = normalizeHandle(handle);
    const rule = ruleFor(normalized);
    if (!rule || loginRequiredForRule(rule)) return null;
    const remaining = remainingForHandle(normalized);
    return {
      // Already net of what the cart holds and what past orders used, so a
      // reader must not subtract the cart from it a second time. `contextual`
      // says so, and `totalMaximum` carries the ceiling worth quoting to the
      // shopper — `maximum` alone would quote 0 as if it were the limit.
      contextual: true,
      maximum: remaining,
      totalMaximum: quantity(rule.maximum, 0),
      currentQuantity: quantity(rule.cartQuantity, 0),
      purchasedQuantity: quantity(rule.purchased, 0),
      reason: 'a customer purchase limit across orders',
      message: messageFor(rule, Math.max(1, remaining + 1), remaining),
    };
  };

  const cartViolation = (totals = null, options = {}) => {
    const proposedTotals = totals || currentCartTotals();
    const currentTotals = currentCartTotals();
    const allowDecreases = options.allowDecreases === true;

    for (const [handle, rule] of Object.entries(rules)) {
      if (loginRequiredForRule(rule)) continue;
      const proposed = quantity(proposedTotals[handle], 0);
      const current = quantity(currentTotals[handle], 0);
      const allowed = allowedCartQuantity(rule);
      if (proposed <= allowed) continue;
      if (allowDecreases && proposed < current) continue;
      return {
        handle,
        proposedQuantity: proposed,
        currentQuantity: current,
        allowedQuantity: allowed,
        rule,
        message: cartMessageFor(rule, allowed),
      };
    }

    return null;
  };

  const cartViolationFromForm = (form, options = {}) => (
    cartViolation(cartTotalsFromForm(form), options)
  );

  const loginRequiredForCartForm = (form) => (
    form ? loginRequiredForCart(cartTotalsFromForm(form)) : loginRequiredForCart()
  );

  const commitCartTotals = (totals) => {
    Object.entries(rules).forEach(([handle, rule]) => {
      const cartQuantity = quantity(totals && totals[handle], 0);
      const allowed = allowedCartQuantity(rule);
      rule.cartQuantity = cartQuantity;
      rule.remaining = Math.max(0, allowed - cartQuantity);
      rule.cartExceeded = cartQuantity > allowed;
    });
  };

  const syncCartFromForm = (form) => {
    const totals = cartTotalsFromForm(form);
    commitCartTotals(totals);
    decorateCartForm(form);
    document.dispatchEvent(new CustomEvent('customer-order-limits:cart-sync'));
    return totals;
  };

  const recordAddition = (handle, addedQuantity) => {
    const normalized = normalizeHandle(handle);
    const rule = ruleFor(normalized);
    if (!rule) return;
    const totals = currentCartTotals();
    totals[normalized] = quantity(totals[normalized], 0)
      + Math.max(1, quantity(addedQuantity, 1));
    commitCartTotals(totals);
    document.dispatchEvent(new CustomEvent('customer-order-limits:cart-sync'));
  };

  const recordRemoval = (handle, removedQuantity) => {
    const normalized = normalizeHandle(handle);
    const rule = ruleFor(normalized);
    if (!rule) return;
    const totals = currentCartTotals();
    totals[normalized] = Math.max(
      0,
      quantity(totals[normalized], 0) - quantity(removedQuantity, 0)
    );
    commitCartTotals(totals);
    document.dispatchEvent(new CustomEvent('customer-order-limits:cart-sync'));
  };

  const ensureAlert = () => {
    let alert = document.querySelector('[data-customer-order-limit-alert]');
    if (alert) return alert;
    alert = document.createElement('div');
    alert.hidden = true;
    alert.className = 'product-listing-cart-alert';
    alert.setAttribute('role', 'alert');
    alert.setAttribute('aria-live', 'assertive');
    alert.setAttribute('data-customer-order-limit-alert', '');
    document.body.appendChild(alert);
    return alert;
  };

  const showListingError = (message) => {
    const alert = ensureAlert();
    alert.textContent = String(message || 'Customer purchase limit exceeded.');
    alert.hidden = false;
    window.clearTimeout(alert.hideTimer);
    alert.hideTimer = window.setTimeout(() => { alert.hidden = true; }, 7000);
  };

  const showProductError = (context, message) => {
    const productForm = context?.closest?.('product-form');
    const formMessage = productForm?.querySelector('.form__message');
    const formContent = formMessage?.querySelector('.js-error-content');
    if (!formMessage || !formContent) {
      showListingError(message);
      return;
    }
    formContent.textContent = String(message || 'Customer purchase limit exceeded.');
    formMessage.classList.remove('hidden');
    formMessage.focus?.();
  };

  const showCartError = (message) => {
    const cartItems = document.querySelector('cart-items');
    if (cartItems && typeof cartItems.renderErrorMsg === 'function') {
      cartItems.renderErrorMsg(String(message || 'Reduce limited-item quantities before checkout.'));
      return;
    }
    const wrapper = document.querySelector('.cart_form__error');
    const content = wrapper?.querySelector('.js-error-content');
    if (wrapper && content) {
      content.textContent = String(message || 'Reduce limited-item quantities before checkout.');
      wrapper.classList.remove('hidden');
      window.scrollTo(0, 0);
      return;
    }
    showListingError(message);
  };

  function decorateCartForm(form) {
    if (!form) return;
    const totals = cartTotalsFromForm(form);

    form.querySelectorAll('tr.cart-item').forEach((row) => {
      const input = row.querySelector('[name="updates[]"]');
      const handleInput = row.querySelector('[name="product_handles[]"]');
      const handle = normalizeHandle(
        handleInput?.value || row.dataset.productHandle || productHandle(row)
      );
      const rule = ruleFor(handle);
      if (!input || !rule || loginRequiredForRule(rule)) return;

      const currentLine = quantity(input.value, 0);
      const currentTotal = quantity(totals[handle], 0);
      const maximum = currentLine + Math.max(
        0,
        allowedCartQuantity(rule) - currentTotal
      );
      row.dataset.productHandle = handle;
      input.dataset.customerOrderLimitEnabled = 'true';
      input.dataset.customerOrderLimitMaximum = String(maximum);
      input.dataset.customerOrderLimitMessage = cartMessageFor(
        rule,
        allowedCartQuantity(rule)
      );
      input.max = String(maximum);
    });

    const violation = cartViolation(totals);
    form.dataset.customerOrderLimitCheckoutBlocked = violation ? 'true' : 'false';

    form.querySelectorAll('#checkout, [name="checkout"], [name="expresscheckout"]').forEach((control) => {
      if (violation) {
        if (!control.dataset.customerOrderLimitDisabled) {
          control.dataset.customerOrderLimitWasDisabled = control.disabled ? 'true' : 'false';
        }
        control.dataset.customerOrderLimitDisabled = 'true';
        control.disabled = true;
        control.setAttribute('aria-disabled', 'true');
      } else if (control.dataset.customerOrderLimitDisabled === 'true') {
        if (control.dataset.customerOrderLimitWasDisabled !== 'true') control.disabled = false;
        control.removeAttribute('aria-disabled');
        delete control.dataset.customerOrderLimitDisabled;
        delete control.dataset.customerOrderLimitWasDisabled;
      }
    });

    form.querySelectorAll('.cart__ctas').forEach((container) => {
      if (container.querySelector('#checkout, [name="checkout"], [name="expresscheckout"]')) return;
      if (violation) {
        container.dataset.customerOrderLimitHidden = 'true';
        container.hidden = true;
      } else if (container.dataset.customerOrderLimitHidden === 'true') {
        container.hidden = false;
        delete container.dataset.customerOrderLimitHidden;
      }
    });
  }

  const formHandle = (form) => normalizeHandle(
    form?.dataset.productHandle || productHandle(form)
  );

  // The hidden Buy Now checkout form lives inside <product-form> too, so an
  // addition guard that matched every `product-form form` blocked checkout and
  // stranded the shopper. Only forms that actually add to the cart qualify.
  const isAddToCartForm = (form) => (
    form.matches('product-form form')
    && !form.matches('[data-buy-now-checkout-form]')
    && Boolean(
      form.querySelector('[name="add"]')
      || /\/cart\/add/.test(String(form.getAttribute('action') || ''))
    )
  );

  // Only takes over the event when the shopper is actually being redirected, so
  // an unproven sign-in state leaves the native purchase path untouched.
  const sendToLogin = (event, intent = null) => {
    if (!shopperSignedOut()) return false;
    event.preventDefault();
    event.stopImmediatePropagation();
    return redirectToLogin(intent);
  };

  document.addEventListener('click', (event) => {
    const listingButton = event.target.closest(
      'add-to-cart-button button[data-product-handle]'
    );
    if (listingButton) {
      if (
        loginRequiredForHandle(listingButton.dataset.productHandle)
        && sendToLogin(event, {
          handle: listingButton.dataset.productHandle,
          quantity: listingButton.dataset.quantity,
          surface: 'listing',
        })
      ) return;
      if (historyBlocks(listingButton.dataset.productHandle)) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showListingError(HISTORY_PENDING_MESSAGE);
        return;
      }
      const violation = additionViolation(
        listingButton.dataset.productHandle,
        listingButton.dataset.quantity
      );
      if (violation) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showListingError(violation.message);
      }
      return;
    }

    const buyNowButton = event.target.closest('[data-buy-now]');
    if (buyNowButton) {
      const owner = buyNowButton.closest('product-form');
      const form = owner?.querySelector('form');
      const handle = formHandle(form);
      if (
        loginRequiredForHandle(handle)
        && sendToLogin(event, {
          handle,
          quantity: form?.querySelector('[name="quantity"]')?.value,
          surface: 'buy-now',
        })
      ) return;
      if (historyBlocks(handle)) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showProductError(form, HISTORY_PENDING_MESSAGE);
        return;
      }
      const violation = additionViolation(
        handle,
        form?.querySelector('[name="quantity"]')?.value
      );
      if (violation) {
        event.preventDefault();
        event.stopImmediatePropagation();
        // Nothing more can be added but the cart already holds the allowance, so
        // Buy Now means "check out with what I have" rather than a dead end.
        if (
          violation.remaining <= 0
          && cartQuantityForHandle(handle) > 0
          && typeof owner?.goToCheckout === 'function'
        ) {
          owner.goToCheckout();
          return;
        }
        showProductError(form, violation.message);
      }
      return;
    }

    const cartForm = event.target.closest('#cart-form');
    if (cartForm && event.target.closest('.cart__ctas')) {
      if (loginRequiredForCartForm(cartForm) && sendToLogin(event, { surface: 'cart' })) return;
      if (historyBlocksCart(cartTotalsFromForm(cartForm))) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showCartError(HISTORY_PENDING_MESSAGE);
        return;
      }
      if (cartForm.dataset.customerOrderLimitCheckoutBlocked === 'true') {
        const violation = cartViolationFromForm(cartForm);
        if (violation) {
          event.preventDefault();
          event.stopImmediatePropagation();
          showCartError(violation.message);
        }
      }
    }
  }, true);

  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;

    if (isAddToCartForm(form)) {
      const handle = formHandle(form);
      if (
        loginRequiredForHandle(handle)
        && sendToLogin(event, {
          handle,
          quantity: form.querySelector('[name="quantity"]')?.value,
          surface: 'product',
        })
      ) return;
      if (historyBlocks(handle)) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showProductError(form, HISTORY_PENDING_MESSAGE);
        return;
      }
      const violation = additionViolation(
        handle,
        form.querySelector('[name="quantity"]')?.value
      );
      if (violation) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showProductError(form, violation.message);
      }
      return;
    }

    if (form.id === 'cart-form') {
      const submitter = event.submitter;
      const isCheckout = !submitter
        || submitter.name === 'checkout'
        || submitter.name === 'expresscheckout'
        || submitter.id === 'checkout';
      if (!isCheckout) return;
      if (loginRequiredForCartForm(form) && sendToLogin(event, { surface: 'cart' })) return;
      if (historyBlocksCart(cartTotalsFromForm(form))) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showCartError(HISTORY_PENDING_MESSAGE);
        return;
      }
      const violation = cartViolationFromForm(form);
      if (violation) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showCartError(violation.message);
      }
    }
  }, true);

  // --- the attempt that signing in interrupted -------------------------------
  // Proof of sign-in, not merely the absence of proof of signing out: an
  // attempt is answered for a customer whose allowance can actually be
  // measured, and is left untouched for anyone else.
  const shopperSignedIn = () => (
    customerAuthenticated || Boolean(document.querySelector(SIGNED_IN_MARKUP))
  );

  // A shopper who has passed the mobile-number step but not the one-time code
  // carries every signed-in marker a finished customer does, so a step still on
  // the page overrules them. `#otp-form .otp-input` is the platform widget's own
  // markup; the rest are the fields the theme's login and register templates
  // render. The path is checked too, but never on its own: EasyStore owns those
  // URLs, and the OTP step renders no form to recognise it by.
  const AUTHENTICATING_MARKUP = [
    '#otp-form',
    '.otp-input',
    'input[name="customer[password]"]',
    'input[name="customer[email_or_phone]"]',
    'form[action^="/account/login"]',
    'form[action^="/account/auth"]',
  ].join(', ');

  const stillAuthenticating = () => (
    onAccountPage() || Boolean(document.querySelector(AUTHENTICATING_MARKUP))
  );

  const addToCartFormFor = (handle) => {
    const normalized = normalizeHandle(handle);
    return Array.from(document.querySelectorAll('product-form form')).find(
      (form) => isAddToCartForm(form) && formHandle(form) === normalized
    ) || null;
  };

  // The message a click would have produced, on the surface that click came
  // from. A shopper who can still buy what they asked for is told nothing.
  const answerPurchaseIntent = (intent) => {
    if (intent.surface === 'cart') {
      const violation = cartViolation();
      if (violation) showCartError(violation.message);
      return violation;
    }

    const violation = additionViolation(intent.handle, intent.quantity);
    if (!violation) return null;
    // Buy Now with the allowance already in the cart means "check out with what
    // I have" rather than a dead end, which is what the button still does, so
    // there is nothing to warn the shopper about.
    if (
      intent.surface === 'buy-now'
      && violation.remaining <= 0
      && cartQuantityForHandle(intent.handle) > 0
    ) return null;
    const form = addToCartFormFor(intent.handle);
    if (form) showProductError(form, violation.message);
    else showListingError(violation.message);
    return violation;
  };

  const applyPurchaseIntent = () => {
    // EasyStore lands a freshly signed-in customer on its own account page, and
    // account-login-redirect.js is about to move them off it, so the attempt is
    // answered on the page they actually return to rather than in passing. A
    // page still asking for a one-time code is not that page either: the
    // shopper counts as a customer there while the code is outstanding.
    if (stillAuthenticating() || !shopperSignedIn()) return;
    const intent = takePurchaseIntent();
    if (!intent) return;

    // Measuring before history has landed would measure against an allowance
    // that assumes nothing was ever bought, which is the reverse of the mistake
    // worth making, so the answer waits for the load to land or to give up.
    const waiting = intent.surface === 'cart'
      ? historyBlocksCart()
      : historyBlocks(intent.handle);
    if (!waiting) {
      answerPurchaseIntent(intent);
      return;
    }

    const answer = () => {
      document.removeEventListener('customer-order-limits:history', answer);
      document.removeEventListener('customer-order-limits:history-unavailable', answer);
      answerPurchaseIntent(intent);
    };
    document.addEventListener('customer-order-limits:history', answer);
    document.addEventListener('customer-order-limits:history-unavailable', answer);
  };

  window.CustomerOrderLimits = {
    customerAuthenticated,
    normalizeHandle,
    ruleFor,
    productHandle,
    loginRequiredForHandle,
    loginRequiredForCart,
    loginRequiredForCartForm,
    loginRedirectUrl,
    redirectToLogin,
    rememberPurchaseIntent,
    takePurchaseIntent,
    applyPurchaseIntent,
    cartTotalsFromForm,
    historyState: () => historyState,
    historyLines: () => appliedHistoryLines.slice(),
    pageIdentifiers: () => ({
      handle: pageProductHandle,
      sku: pageProductSku,
      productId: pageProductId,
      variantIds: Array.from(pageVariantIds),
    }),
    loadHistory,
    remainingForHandle,
    cartQuantityForHandle,
    quantityLimitForHandle,
    additionViolation,
    cartViolation,
    cartViolationFromForm,
    commitCartTotals,
    syncCartFromForm,
    recordAddition,
    recordRemoval,
    decorateCartForm,
    showListingError,
    showProductError,
    showCartError,
  };

  decorateCartForm(document.getElementById('cart-form'));
  document.dispatchEvent(new CustomEvent('customer-order-limits:ready'));

  // Start loading before the shopper can click, so the held-purchase path above
  // is a rare fallback rather than the normal experience.
  if (historyResolving()) {
    if (historySupported()) loadHistory();
    // Report the honest state so nothing waits for a load that cannot happen.
    else historyState = 'unavailable';
  }

  applyPurchaseIntent();
})();
