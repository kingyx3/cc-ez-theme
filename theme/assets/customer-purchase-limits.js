(() => {
  'use strict';

  const source = window.customerPurchaseLimits;
  if (!source || source.enabled !== true || !source.rules) return;

  const quantity = (value, fallback = 0) => {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
  };

  const rules = Object.entries(source.rules).reduce((result, [handle, rawRule]) => {
    const maximum = quantity(rawRule && rawRule.maximum, 0);
    if (!handle || maximum <= 0) return result;
    result[String(handle)] = {
      handle: String(handle),
      maximum,
      purchased: quantity(rawRule && rawRule.purchased, 0),
    };
    return result;
  }, {});

  if (Object.keys(rules).length === 0) return;

  const variantHandles = source.variantHandles
    && typeof source.variantHandles === 'object'
    ? source.variantHandles
    : {};

  const cart = source.cart && typeof source.cart === 'object'
    ? source.cart
    : { handles: {}, lines: [] };
  cart.handles = cart.handles && typeof cart.handles === 'object'
    ? cart.handles
    : {};
  cart.lines = Array.isArray(cart.lines) ? cart.lines : [];

  const pendingAdds = [];
  let lastVisibleCartCount = null;

  const units = (value) => `${value} unit${value === 1 ? '' : 's'}`;
  const ruleForHandle = (handle) => rules[String(handle || '')] || null;
  const cartQuantity = (handle) => quantity(cart.handles[String(handle || '')], 0);

  const availableForCart = (rule) => Math.max(0, rule.maximum - rule.purchased);
  const remainingForHandle = (handle) => {
    const rule = ruleForHandle(handle);
    if (!rule) return null;
    return Math.max(
      0,
      availableForCart(rule) - cartQuantity(handle)
    );
  };

  const messageFor = ({
    rule,
    handle,
    requested = 1,
    cartMode = false,
    loginRequired = false,
  }) => {
    if (loginRequired) {
      return 'Sign in to purchase this limited item. Purchase limits are tracked across customer orders.';
    }

    const inCart = cartQuantity(handle);
    const purchased = quantity(rule.purchased, 0);
    const available = availableForCart(rule);
    const remaining = Math.max(0, available - inCart);
    const history = purchased > 0 ? ` ${units(purchased)} previously purchased.` : '';
    const currentCart = inCart > 0 ? ` ${units(inCart)} currently in your cart.` : '';

    if (cartMode) {
      return `Cart quantity exceeds the customer purchase limit. You may have up to ${units(available)} in your cart for this entitlement period (${units(rule.maximum)} total per customer).${history}`;
    }
    if (remaining === 0) {
      return `Purchase limit reached.${history}${currentCart} The limit is ${units(rule.maximum)} per customer.`;
    }
    return `Purchase limit exceeded. You can add up to ${units(remaining)} more.${history}${currentCart} The limit is ${units(rule.maximum)} per customer.`;
  };

  const additionViolation = (handle, requestedQuantity = 1) => {
    const rule = ruleForHandle(handle);
    if (!rule) return null;

    const requested = Math.max(1, quantity(requestedQuantity, 1));
    if (source.loggedIn !== true) {
      return {
        handle: rule.handle,
        rule,
        requested,
        message: messageFor({
          rule,
          handle: rule.handle,
          requested,
          loginRequired: true,
        }),
      };
    }

    const remaining = remainingForHandle(rule.handle);
    if (requested <= remaining) return null;
    return {
      handle: rule.handle,
      rule,
      requested,
      remaining,
      message: messageFor({ rule, handle: rule.handle, requested }),
    };
  };

  const cartViolation = (handleQuantities, options = {}) => {
    const allowDecreases = options.allowDecreases === true;
    for (const [handle, rawValue] of Object.entries(handleQuantities || {})) {
      const rule = ruleForHandle(handle);
      if (!rule) continue;
      const proposed = quantity(rawValue, 0);
      if (proposed <= 0) continue;
      if (allowDecreases && proposed <= cartQuantity(handle)) continue;

      if (source.loggedIn !== true) {
        return {
          handle,
          message: messageFor({
            rule,
            handle,
            cartMode: true,
            loginRequired: true,
          }),
        };
      }

      if (proposed > availableForCart(rule)) {
        return {
          handle,
          message: messageFor({ rule, handle, cartMode: true }),
        };
      }
    }
    return null;
  };

  const cleanMessage = (rawMessage) => {
    const raw = String(rawMessage || '').trim();
    const feedback = window.PurchaseLimitFeedback;
    return feedback && typeof feedback.stripMarkup === 'function'
      ? feedback.stripMarkup(raw)
      : raw.replace(/<[^>]*>/g, '').trim();
  };

  const getListingAlert = () => {
    let alert = document.querySelector('[data-product-listing-cart-alert]');
    if (alert) return alert;

    alert = document.createElement('div');
    alert.className = 'product-listing-cart-alert';
    alert.hidden = true;
    alert.setAttribute('role', 'alert');
    alert.setAttribute('aria-live', 'assertive');
    alert.setAttribute('data-product-listing-cart-alert', '');

    const message = document.createElement('span');
    message.setAttribute('data-product-listing-cart-alert-message', '');
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'product-listing-cart-alert__close';
    close.setAttribute('aria-label', 'Dismiss message');
    close.textContent = '×';
    close.addEventListener('click', () => { alert.hidden = true; });
    alert.append(message, close);
    document.body.appendChild(alert);
    return alert;
  };

  const showListingError = (message) => {
    const alert = getListingAlert();
    const content = alert.querySelector('[data-product-listing-cart-alert-message]');
    if (content) content.textContent = cleanMessage(message);
    alert.hidden = false;
    window.clearTimeout(alert.customerLimitTimer);
    alert.customerLimitTimer = window.setTimeout(() => {
      alert.hidden = true;
    }, 7000);
  };

  const showProductError = (form, message) => {
    const productForm = form && form.closest('product-form');
    const quantityMessage = productForm
      && productForm.querySelector('[data-quantity-limit-message]');
    const formMessage = form && form.querySelector('.form__message');
    const formContent = form && form.querySelector('.js-error-content');
    const cleaned = cleanMessage(message);

    if (quantityMessage) {
      quantityMessage.textContent = cleaned;
      quantityMessage.classList.remove('hidden', 'quantity-limit-message--warning');
      quantityMessage.classList.add('quantity-limit-message--error');
    }
    if (formMessage && formContent) {
      form.dataset.customerLimitError = 'true';
      formContent.textContent = cleaned;
      formMessage.classList.remove('hidden');
    }
  };

  const clearProductError = (form) => {
    const productForm = form && form.closest('product-form');
    const quantityMessage = productForm
      && productForm.querySelector('[data-quantity-limit-message]');
    if (quantityMessage && quantityMessage.dataset.customerLimitMessage === 'true') {
      quantityMessage.textContent = '';
      quantityMessage.classList.add('hidden');
      quantityMessage.classList.remove('quantity-limit-message--error');
      delete quantityMessage.dataset.customerLimitMessage;
    }

    if (form && form.dataset.customerLimitError === 'true') {
      const formMessage = form.querySelector('.form__message');
      const formContent = form.querySelector('.js-error-content');
      if (formMessage) formMessage.classList.add('hidden');
      if (formContent) formContent.textContent = '';
      delete form.dataset.customerLimitError;
    }
  };

  const showCartError = (message) => {
    const container = document.querySelector('.cart_form__error');
    const content = container && container.querySelector('.js-error-content');
    if (container && content) {
      content.textContent = cleanMessage(message);
      container.classList.remove('hidden');
      window.scrollTo(0, 0);
      return;
    }
    showListingError(message);
  };

  const handleForVariant = (variantId) => String(
    variantHandles[String(variantId || '')] || ''
  );

  const handleForProductForm = (form) => {
    const selected = form && form.querySelector('[name="id"]');
    return handleForVariant(selected && selected.value);
  };

  const requestedProductQuantity = (form) => {
    const input = form && form.querySelector('[name="quantity"]');
    return Math.max(1, quantity(input && input.value, 1));
  };

  const queueAdditionCandidate = (handle, amount) => {
    const normalizedHandle = String(handle || '');
    const normalizedAmount = Math.max(1, quantity(amount, 1));
    if (!normalizedHandle) return;

    const pending = {
      handle: normalizedHandle,
      remaining: normalizedAmount,
      timer: null,
    };
    pending.timer = window.setTimeout(() => {
      const index = pendingAdds.indexOf(pending);
      if (index >= 0) pendingAdds.splice(index, 1);
    }, 15000);
    pendingAdds.push(pending);
  };

  const settlePendingAdditions = (increase) => {
    let remainingIncrease = Math.max(0, quantity(increase, 0));
    while (remainingIncrease > 0 && pendingAdds.length > 0) {
      const pending = pendingAdds[0];
      const settled = Math.min(remainingIncrease, pending.remaining);
      pending.remaining -= settled;
      remainingIncrease -= settled;
      cart.handles[pending.handle] = cartQuantity(pending.handle) + settled;

      if (pending.remaining === 0) {
        window.clearTimeout(pending.timer);
        pendingAdds.shift();
      }
    }
  };

  const visibleCartCount = () => {
    const counter = document.querySelector('.js-content-cart-count');
    if (!counter) return null;
    const parsed = Number.parseInt(counter.textContent, 10);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const observeCartCount = () => {
    const counter = document.querySelector('.js-content-cart-count');
    if (!counter || typeof MutationObserver !== 'function') return;
    lastVisibleCartCount = visibleCartCount();
    const observer = new MutationObserver(() => {
      const current = visibleCartCount();
      if (current == null) return;
      if (lastVisibleCartCount != null && current > lastVisibleCartCount) {
        settlePendingAdditions(current - lastVisibleCartCount);
      }
      lastVisibleCartCount = current;
    });
    observer.observe(counter, { childList: true, characterData: true, subtree: true });
  };

  const readCartFromDom = () => {
    const inputs = Array.from(
      document.querySelectorAll('cart-items [name="updates[]"]')
    );
    if (inputs.length === 0) {
      return { lines: cart.lines.slice(), handles: { ...cart.handles } };
    }

    const variantInputs = Array.from(
      document.querySelectorAll('#cart-form [name="ids[]"]')
    );
    const itemInputs = Array.from(
      document.querySelectorAll('#cart-form [name="item_ids[]"]')
    );
    const lines = [];
    const handles = {};

    inputs.forEach((input, index) => {
      const previous = cart.lines[index] || {};
      const variantId = String(
        (variantInputs[index] && variantInputs[index].value)
        || previous.variantId
        || ''
      );
      const handle = String(previous.handle || handleForVariant(variantId) || '');
      const lineQuantity = quantity(input.value, 0);
      if (input.dataset.customerLimitPreviousValue == null) {
        input.dataset.customerLimitPreviousValue = String(lineQuantity);
      }

      lines.push({
        itemId: String(
          (itemInputs[index] && itemInputs[index].value)
          || previous.itemId
          || ''
        ),
        variantId,
        handle,
        quantity: lineQuantity,
      });
      if (handle) handles[handle] = (handles[handle] || 0) + lineQuantity;
    });

    return { lines, handles };
  };

  const commitCartState = (state) => {
    cart.lines = state.lines;
    Object.keys(cart.handles).forEach((handle) => { cart.handles[handle] = 0; });
    Object.entries(state.handles).forEach(([handle, value]) => {
      cart.handles[handle] = quantity(value, 0);
    });
  };

  const syncCartFromDom = () => {
    const state = readCartFromDom();
    commitCartState(state);
    return state.handles;
  };

  const observeCartRows = () => {
    const template = document.querySelector('#cart-template');
    if (!template || typeof MutationObserver !== 'function') return;
    const observer = new MutationObserver(syncCartFromDom);
    observer.observe(template, { childList: true, subtree: true });
  };

  const block = (event) => {
    event.preventDefault();
    event.stopImmediatePropagation();
  };

  document.addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const listingButton = target.closest(
      '.addToClassList[data-product-handle]'
    );
    if (listingButton) {
      const handle = String(listingButton.dataset.productHandle || '');
      const requested = Math.max(1, quantity(listingButton.dataset.quantity, 1));
      const violation = additionViolation(handle, requested);
      if (violation) {
        block(event);
        showListingError(violation.message);
        return;
      }
      if (ruleForHandle(handle)) queueAdditionCandidate(handle, requested);
      return;
    }

    const buyNowButton = target.closest('product-form [data-buy-now]');
    if (!buyNowButton) return;
    const form = buyNowButton.closest('product-form')?.querySelector('form[action="/cart/add"]');
    const handle = handleForProductForm(form);
    const requested = requestedProductQuantity(form);
    const violation = additionViolation(handle, requested);
    if (violation) {
      block(event);
      showProductError(form, violation.message);
      return;
    }
    if (ruleForHandle(handle)) queueAdditionCandidate(handle, requested);
  }, true);

  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;

    if (form.matches('product-form form[action="/cart/add"]')) {
      const handle = handleForProductForm(form);
      const requested = requestedProductQuantity(form);
      const violation = additionViolation(handle, requested);
      if (violation) {
        block(event);
        showProductError(form, violation.message);
        return;
      }
      if (ruleForHandle(handle)) queueAdditionCandidate(handle, requested);
      return;
    }

    const isCheckout = form.id === 'cart-form'
      && (form.querySelector('[name="checkout"]')
        || (event.submitter && event.submitter.name === 'checkout'));
    if (!isCheckout) return;

    const proposed = readCartFromDom();
    const violation = cartViolation(proposed.handles);
    if (!violation) {
      commitCartState(proposed);
      return;
    }
    block(event);
    showCartError(violation.message);
  }, true);

  const validateProductQuantity = (input) => {
    const form = input.closest('form[action="/cart/add"]');
    if (!form) return;
    const handle = handleForProductForm(form);
    const violation = additionViolation(handle, input.value);
    const productForm = form.closest('product-form');
    const quantityMessage = productForm
      && productForm.querySelector('[data-quantity-limit-message]');

    if (violation) {
      if (quantityMessage) quantityMessage.dataset.customerLimitMessage = 'true';
      showProductError(form, violation.message);
    } else {
      clearProductError(form);
    }
  };

  document.addEventListener('input', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    if (target.matches('product-form [name="quantity"]')) {
      window.setTimeout(() => validateProductQuantity(target), 0);
    }
  }, true);

  document.addEventListener('change', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    if (target.matches('product-form [name="quantity"]')) {
      window.setTimeout(() => validateProductQuantity(target), 0);
      return;
    }

    if (!target.matches('cart-items [name="updates[]"]')) return;
    const proposed = readCartFromDom();
    const violation = cartViolation(proposed.handles, { allowDecreases: true });
    if (!violation) {
      commitCartState(proposed);
      target.dataset.customerLimitPreviousValue = String(
        quantity(target.value, 0)
      );
      return;
    }

    block(event);
    const previousValue = quantity(
      target.dataset.customerLimitPreviousValue,
      quantity(target.defaultValue, 0)
    );
    target.value = String(previousValue);
    showCartError(violation.message);
  }, true);

  window.CustomerPurchaseLimits = Object.freeze({
    enabled: true,
    ruleForHandle,
    remainingForHandle,
    additionViolation,
    cartViolation,
    syncCartFromDom,
    readCartFromDom,
  });

  const initialize = () => {
    observeCartCount();
    observeCartRows();
    document.querySelectorAll('product-form [name="quantity"]').forEach(
      validateProductQuantity
    );
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize, { once: true });
  } else {
    initialize();
  }
})();