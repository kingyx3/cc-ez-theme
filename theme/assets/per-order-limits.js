(() => {
  'use strict';

  const source = window.perOrderLimitsV1;
  if (!source || !source.rules || Object.keys(source.rules).length === 0) return;

  const qty = (value, fallback = 0) => {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
  };
  const normalize = (value) => {
    try {
      return decodeURIComponent(String(value || '')).trim().toLowerCase();
    } catch (_error) {
      return String(value || '').trim().toLowerCase();
    }
  };
  const unit = (value) => `${qty(value)} unit${qty(value) === 1 ? '' : 's'}`;
  const rules = {};
  Object.entries(source.rules).forEach(([handle, rule]) => {
    const key = normalize(handle);
    if (key) rules[key] = rule;
  });
  source.rules = rules;

  const handleFromUrl = (value) => {
    const match = String(value || '').match(/\/products\/([^/?#]+)/i);
    return match ? normalize(match[1]) : '';
  };
  const productHandle = (element) => {
    if (!element) return '';
    const owner = element.closest?.('[data-product-handle]');
    if (owner?.dataset.productHandle) return normalize(owner.dataset.productHandle);
    const link = element.querySelector?.('a[href*="/products/"]')
      || element.parentElement?.querySelector?.('a[href*="/products/"]');
    return handleFromUrl(link?.getAttribute('href')) || handleFromUrl(window.location.pathname);
  };
  const ruleFor = (handle) => rules[normalize(handle)] || null;
  const totalsNow = () => Object.fromEntries(
    Object.entries(rules).map(([handle, rule]) => [handle, qty(rule.cartQuantity)])
  );
  const totalsFromForm = (form) => {
    const totals = {};
    form?.querySelectorAll('tr.cart-item').forEach((row) => {
      const input = row.querySelector('[name="updates[]"]');
      const handleInput = row.querySelector('[name="product_handles[]"]');
      const handle = normalize(handleInput?.value || row.dataset.productHandle || productHandle(row));
      if (handle && input) totals[handle] = (totals[handle] || 0) + qty(input.value);
    });
    return totals;
  };
  const remainingFor = (handle, totals = null) => {
    const key = normalize(handle);
    const rule = ruleFor(key);
    if (!rule) return null;
    const inCart = totals && Object.prototype.hasOwnProperty.call(totals, key)
      ? qty(totals[key])
      : qty(rule.cartQuantity);
    return Math.max(0, qty(rule.maximum) - inCart);
  };
  const messageFor = (rule, requested, remaining) => {
    const maximum = qty(rule.maximum);
    const inCart = qty(rule.cartQuantity);
    if (remaining <= 0) {
      return `Limit reached: ${unit(maximum)} per order.${inCart ? ` You already have ${unit(inCart)} in your cart.` : ''}`;
    }
    if (qty(requested, 1) > remaining && inCart) {
      return `Maximum ${unit(remaining)} more (${maximum} per order, ${inCart} already in your cart).`;
    }
    return `Maximum ${unit(inCart ? remaining : maximum)} per order.`;
  };
  const cartMessage = (rule) => (
    `Reduce this item so the order contains at most ${unit(rule.maximum)} for this SKU.`
  );
  const quantityLimitForHandle = (handle) => {
    const rule = ruleFor(handle);
    if (!rule) return null;
    const remaining = remainingFor(handle);
    return {
      contextual: true,
      maximum: remaining,
      totalMaximum: qty(rule.maximum),
      currentQuantity: qty(rule.cartQuantity),
      purchasedQuantity: 0,
      reason: 'an order limit',
      message: messageFor(rule, remaining + 1, remaining),
    };
  };
  const additionViolation = (handle, requestedQuantity) => {
    const key = normalize(handle);
    const rule = ruleFor(key);
    if (!rule) return null;
    const requested = Math.max(1, qty(requestedQuantity, 1));
    const remaining = remainingFor(key);
    if (requested <= remaining) return null;
    return { handle: key, requestedQuantity: requested, remaining, rule, message: messageFor(rule, requested, remaining) };
  };
  const cartViolation = (totals = null, options = {}) => {
    const proposed = totals || totalsNow();
    const current = totalsNow();
    for (const [handle, rule] of Object.entries(rules)) {
      const next = qty(proposed[handle]);
      if (next <= qty(rule.maximum)) continue;
      if (options.allowDecreases === true && next < qty(current[handle])) continue;
      return {
        handle,
        proposedQuantity: next,
        currentQuantity: qty(current[handle]),
        allowedQuantity: qty(rule.maximum),
        rule,
        message: cartMessage(rule),
      };
    }
    return null;
  };
  const cartViolationFromForm = (form, options = {}) => cartViolation(totalsFromForm(form), options);
  const commit = (totals) => {
    Object.entries(rules).forEach(([handle, rule]) => {
      rule.cartQuantity = qty(totals?.[handle]);
      rule.remaining = Math.max(0, qty(rule.maximum) - rule.cartQuantity);
    });
  };
  const recordAddition = (handle, amount) => {
    const key = normalize(handle);
    if (!ruleFor(key)) return;
    const totals = totalsNow();
    totals[key] = qty(totals[key]) + Math.max(1, qty(amount, 1));
    commit(totals);
  };
  const recordRemoval = (handle, amount) => {
    const key = normalize(handle);
    if (!ruleFor(key)) return;
    const totals = totalsNow();
    totals[key] = Math.max(0, qty(totals[key]) - qty(amount));
    commit(totals);
  };

  const fallbackError = (message) => {
    let alert = document.querySelector('[data-per-order-limit-alert]');
    if (!alert) {
      alert = document.createElement('div');
      alert.className = 'product-listing-cart-alert';
      alert.setAttribute('role', 'alert');
      alert.setAttribute('data-per-order-limit-alert', '');
      document.body.appendChild(alert);
    }
    alert.textContent = message;
    alert.hidden = false;
  };
  const show = (surface, context, message) => {
    const customer = window.CustomerOrderLimits;
    const method = surface === 'cart' ? 'showCartError' : surface === 'product' ? 'showProductError' : 'showListingError';
    if (typeof customer?.[method] === 'function') customer[method](...(surface === 'product' ? [context, message] : [message]));
    else fallbackError(message);
  };

  const decorateCartForm = (form) => {
    if (!form) return;
    const totals = totalsFromForm(form);
    form.querySelectorAll('tr.cart-item').forEach((row) => {
      const input = row.querySelector('[name="updates[]"]');
      const handleInput = row.querySelector('[name="product_handles[]"]');
      const handle = normalize(handleInput?.value || row.dataset.productHandle || productHandle(row));
      const rule = ruleFor(handle);
      if (!input || !rule) return;
      const line = qty(input.value);
      const orderMaximum = line + Math.max(0, qty(rule.maximum) - qty(totals[handle]));
      if (!Object.prototype.hasOwnProperty.call(input.dataset, 'perOrderLimitBaseMaximum')) {
        input.dataset.perOrderLimitBaseMaximum = input.getAttribute('max') || '';
      }
      const candidates = [orderMaximum];
      const baseMaximum = qty(input.dataset.perOrderLimitBaseMaximum);
      const customerMaximum = qty(input.dataset.customerOrderLimitMaximum);
      if (baseMaximum > 0) candidates.push(baseMaximum);
      if (customerMaximum > 0) candidates.push(customerMaximum);
      input.max = String(Math.min(...candidates));
      input.dataset.perOrderLimitMaximum = String(orderMaximum);
    });
    form.dataset.perOrderLimitCheckoutBlocked = cartViolation(totals) ? 'true' : 'false';
  };

  const formHandle = (form) => normalize(form?.dataset.productHandle || productHandle(form));
  const addForm = (form) => form.matches('product-form form')
    && !form.matches('[data-buy-now-checkout-form]')
    && Boolean(form.querySelector('[name="add"]') || /\/cart\/add/.test(String(form.getAttribute('action') || '')));

  document.addEventListener('click', (event) => {
    const listing = event.target.closest('add-to-cart-button button[data-product-handle]');
    if (listing) {
      const violation = additionViolation(listing.dataset.productHandle, listing.dataset.quantity);
      if (violation) {
        event.preventDefault();
        event.stopImmediatePropagation();
        show('listing', null, violation.message);
      }
      return;
    }
    const buyNow = event.target.closest('[data-buy-now]');
    if (buyNow) {
      const owner = buyNow.closest('product-form');
      const form = owner?.querySelector('form');
      const handle = formHandle(form);
      const violation = additionViolation(handle, form?.querySelector('[name="quantity"]')?.value);
      if (violation) {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (violation.remaining <= 0 && qty(ruleFor(handle)?.cartQuantity) > 0
          && !window.CustomerOrderLimits?.loginRequiredForHandle?.(handle)
          && typeof owner?.goToCheckout === 'function') owner.goToCheckout();
        else show('product', form, violation.message);
      }
      return;
    }
    const cart = event.target.closest('#cart-form');
    if (cart && event.target.closest('.cart__ctas')) {
      const violation = cartViolationFromForm(cart);
      if (violation) {
        event.preventDefault();
        event.stopImmediatePropagation();
        show('cart', null, violation.message);
      }
    }
  }, true);

  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (addForm(form)) {
      const violation = additionViolation(formHandle(form), form.querySelector('[name="quantity"]')?.value);
      if (violation) {
        event.preventDefault();
        event.stopImmediatePropagation();
        show('product', form, violation.message);
      }
      return;
    }
    if (form.id !== 'cart-form') return;
    const submitter = event.submitter;
    if (submitter && submitter.name !== 'checkout' && submitter.name !== 'expresscheckout' && submitter.id !== 'checkout') return;
    const violation = cartViolationFromForm(form);
    if (violation) {
      event.preventDefault();
      event.stopImmediatePropagation();
      show('cart', null, violation.message);
    }
  }, true);

  const strictest = (customerValue, orderValue, field) => {
    if (!customerValue) return orderValue;
    if (!orderValue) return customerValue;
    return orderValue[field] < customerValue[field] ? orderValue : customerValue;
  };
  const wrapCustomerLimits = () => {
    const customer = window.CustomerOrderLimits;
    if (!customer || customer.perOrderLimitsWrapped) return false;
    const original = {
      quantityLimitForHandle: customer.quantityLimitForHandle?.bind(customer),
      additionViolation: customer.additionViolation?.bind(customer),
      cartViolation: customer.cartViolation?.bind(customer),
      cartViolationFromForm: customer.cartViolationFromForm?.bind(customer),
      commitCartTotals: customer.commitCartTotals?.bind(customer),
      recordAddition: customer.recordAddition?.bind(customer),
      recordRemoval: customer.recordRemoval?.bind(customer),
      decorateCartForm: customer.decorateCartForm?.bind(customer),
    };
    customer.quantityLimitForHandle = (handle) => strictest(original.quantityLimitForHandle?.(handle), quantityLimitForHandle(handle), 'maximum');
    customer.additionViolation = (handle, requested) => strictest(original.additionViolation?.(handle, requested), additionViolation(handle, requested), 'remaining');
    customer.cartViolation = (totals = null, options = {}) => strictest(original.cartViolation?.(totals, options), cartViolation(totals, options), 'allowedQuantity');
    customer.cartViolationFromForm = (form, options = {}) => strictest(original.cartViolationFromForm?.(form, options), cartViolationFromForm(form, options), 'allowedQuantity');
    customer.commitCartTotals = (totals) => { commit(totals); return original.commitCartTotals?.(totals); };
    customer.recordAddition = (handle, amount) => { recordAddition(handle, amount); return original.recordAddition?.(handle, amount); };
    customer.recordRemoval = (handle, amount) => { recordRemoval(handle, amount); return original.recordRemoval?.(handle, amount); };
    customer.decorateCartForm = (form) => { original.decorateCartForm?.(form); decorateCartForm(form); };
    customer.perOrderRuleFor = ruleFor;
    customer.perOrderLimitsWrapped = true;
    decorateCartForm(document.getElementById('cart-form'));
    document.dispatchEvent(new CustomEvent('customer-order-limits:cart-sync'));
    return true;
  };

  window.PerOrderLimits = {
    ruleFor,
    productHandle,
    totalsFromForm,
    remainingFor,
    quantityLimitForHandle,
    additionViolation,
    cartViolation,
    cartViolationFromForm,
    commitCartTotals: commit,
    recordAddition,
    recordRemoval,
    decorateCartForm,
  };
  document.addEventListener('customer-order-limits:ready', wrapCustomerLimits);
  document.addEventListener('customer-order-limits:cart-sync', () => decorateCartForm(document.getElementById('cart-form')));
  decorateCartForm(document.getElementById('cart-form'));
  window.addEventListener('DOMContentLoaded', () => window.setTimeout(wrapCustomerLimits, 0));
})();
