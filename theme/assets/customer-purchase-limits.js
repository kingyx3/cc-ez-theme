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

  const units = (value) => `${value} unit${value === 1 ? '' : 's'}`;
  const ruleForHandle = (handle) => rules[String(handle || '')] || null;
  const handleForVariant = (variantId) => String(
    variantHandles[String(variantId || '')] || ''
  );
  const cartQuantity = (handle) => quantity(cart.handles[String(handle || '')], 0);
  const availableForCart = (rule) => Math.max(0, rule.maximum - rule.purchased);
  const remainingForHandle = (handle) => {
    const rule = ruleForHandle(handle);
    if (!rule) return null;
    return Math.max(0, availableForCart(rule) - cartQuantity(handle));
  };

  const messageFor = ({ rule, handle, cartMode = false, loginRequired = false }) => {
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
        message: messageFor({ rule, handle: rule.handle, loginRequired: true }),
      };
    }

    const remaining = remainingForHandle(rule.handle);
    if (requested <= remaining) return null;
    return {
      handle: rule.handle,
      remaining,
      message: messageFor({ rule, handle: rule.handle }),
    };
  };

  const additionViolationForVariant = (variantId, requestedQuantity = 1) => (
    additionViolation(handleForVariant(variantId), requestedQuantity)
  );

  const quantityLimitForVariant = (variantId) => {
    const handle = handleForVariant(variantId);
    const rule = ruleForHandle(handle);
    if (!rule) return null;
    const loginRequired = source.loggedIn !== true;
    return {
      maximum: loginRequired ? 0 : remainingForHandle(handle),
      reason: (window.purchaseStrings || {}).customerLimit || 'a customer limit',
      message: messageFor({ rule, handle, loginRequired }),
      customerPurchaseLimit: true,
      handle,
    };
  };

  const arrayValue = (sourceObject, key) => {
    if (!sourceObject || typeof sourceObject !== 'object') return [];
    const value = sourceObject[key] != null
      ? sourceObject[key]
      : sourceObject[`${key}[]`];
    if (Array.isArray(value)) return value;
    return value == null ? [] : [value];
  };

  const bodyFromForm = (formOrBody) => {
    if (!formOrBody) return {};
    if (typeof HTMLFormElement !== 'undefined' && formOrBody instanceof HTMLFormElement) {
      try {
        return JSON.parse(serializeForm(formOrBody));
      } catch (error) {
        return {};
      }
    }
    return typeof formOrBody === 'object' ? formOrBody : {};
  };

  const cartStateFromForm = (formOrBody) => {
    const body = bodyFromForm(formOrBody);
    const updates = arrayValue(body, 'updates');
    const variants = arrayValue(body, 'ids');
    const itemIds = arrayValue(body, 'item_ids');
    const handles = arrayValue(body, 'product_handles');
    const lineCount = Math.max(updates.length, variants.length, handles.length);
    const lines = [];
    const handleQuantities = {};

    for (let index = 0; index < lineCount; index += 1) {
      const previous = cart.lines[index] || {};
      const variantId = String(variants[index] || previous.variantId || '');
      const handle = String(
        handles[index] || previous.handle || handleForVariant(variantId) || ''
      );
      const lineQuantity = quantity(
        updates[index],
        quantity(previous.quantity, 0)
      );
      lines.push({
        itemId: String(itemIds[index] || previous.itemId || ''),
        variantId,
        handle,
        quantity: lineQuantity,
      });
      if (handle) {
        handleQuantities[handle] = (handleQuantities[handle] || 0) + lineQuantity;
      }
    }

    return { lines, handles: handleQuantities };
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
          message: messageFor({ rule, handle, cartMode: true, loginRequired: true }),
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

  const cartViolationFromForm = (formOrBody, options = {}) => {
    const state = cartStateFromForm(formOrBody);
    const violation = cartViolation(state.handles, options);
    return violation ? { ...violation, state } : null;
  };

  const commitCartState = (state) => {
    if (!state) return;
    cart.lines = Array.isArray(state.lines) ? state.lines : [];
    Object.keys(cart.handles).forEach((handle) => { cart.handles[handle] = 0; });
    Object.entries(state.handles || {}).forEach(([handle, value]) => {
      cart.handles[handle] = quantity(value, 0);
    });
  };

  const syncCartFromForm = (form = document.getElementById('cart-form')) => {
    if (!form) return;
    commitCartState(cartStateFromForm(form));
  };

  const recordAddition = (handle, requestedQuantity = 1) => {
    const normalizedHandle = String(handle || '');
    if (!ruleForHandle(normalizedHandle)) return;
    cart.handles[normalizedHandle] = cartQuantity(normalizedHandle)
      + Math.max(1, quantity(requestedQuantity, 1));
  };

  const recordAdditionForVariant = (variantId, requestedQuantity = 1) => {
    recordAddition(handleForVariant(variantId), requestedQuantity);
  };

  const recordRemovalForVariant = (variantId, removedQuantity = 1) => {
    const handle = handleForVariant(variantId);
    if (!handle) return;
    cart.handles[handle] = Math.max(
      0,
      cartQuantity(handle) - quantity(removedQuantity, 0)
    );
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
    alert.customerLimitTimer = window.setTimeout(() => { alert.hidden = true; }, 7000);
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

  window.CustomerPurchaseLimits = Object.freeze({
    enabled: true,
    ruleForHandle,
    handleForVariant,
    remainingForHandle,
    quantityLimitForVariant,
    additionViolation,
    additionViolationForVariant,
    cartStateFromForm,
    cartViolation,
    cartViolationFromForm,
    commitCartState,
    syncCartFromForm,
    recordAddition,
    recordAdditionForVariant,
    recordRemovalForVariant,
    showListingError,
    showCartError,
  });

  const initialize = () => {
    syncCartFromForm();
    document.querySelectorAll('product-form').forEach((productForm) => {
      if (typeof productForm.validateQuantity === 'function') {
        productForm.validateQuantity();
      }
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize, { once: true });
  } else {
    initialize();
  }
})();
