(() => {
  'use strict';

  const config = () => {
    window.customerPurchaseLimits = window.customerPurchaseLimits || {
      loggedIn: false,
      loginUrl: '/account/login',
      rules: {},
    };
    window.customerPurchaseLimits.rules = window.customerPurchaseLimits.rules || {};
    return window.customerPurchaseLimits;
  };

  const variantHandles = () => {
    window.customerPurchaseLimitVariantHandles =
      window.customerPurchaseLimitVariantHandles || {};
    return window.customerPurchaseLimitVariantHandles;
  };

  const cartVariants = () => {
    window.purchaseCartQuantities = window.purchaseCartQuantities || {};
    return window.purchaseCartQuantities;
  };

  const cartHandles = () => {
    window.purchaseCartHandleQuantities = window.purchaseCartHandleQuantities || {};
    return window.purchaseCartHandleQuantities;
  };

  const cartLines = () => {
    window.purchaseCartLines = Array.isArray(window.purchaseCartLines)
      ? window.purchaseCartLines
      : [];
    return window.purchaseCartLines;
  };

  const quantity = (value, fallback = 0) => {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
  };

  const units = (value) => `${value} unit${value === 1 ? '' : 's'}`;

  const handleForVariant = (variantId) =>
    String(variantHandles()[String(variantId || '')] || '');

  const ruleForHandle = (handle) => {
    const source = config().rules[String(handle || '')];
    if (!source) return null;

    const maximum = quantity(source.maximum, 0);
    if (maximum <= 0) return null;

    return {
      ...source,
      handle: String(handle),
      maximum,
      purchased: quantity(source.purchased, 0),
    };
  };

  const ruleForVariant = (variantId) => ruleForHandle(handleForVariant(variantId));

  const cartHandleQuantity = (handle) =>
    quantity(cartHandles()[String(handle || '')], 0);

  const setCartHandleQuantity = (handle, value) => {
    if (!handle) return;
    cartHandles()[String(handle)] = quantity(value, 0);
  };

  const setCartVariantQuantity = (variantId, value) => {
    if (variantId == null || variantId === '') return;
    cartVariants()[String(variantId)] = quantity(value, 0);
  };

  const formatDate = (value) => {
    const text = String(value || '').trim();
    if (!text) return '';

    const parts = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    const date = parts
      ? new Date(
        Number.parseInt(parts[1], 10),
        Number.parseInt(parts[2], 10) - 1,
        Number.parseInt(parts[3], 10)
      )
      : new Date(text);

    if (Number.isNaN(date.getTime())) return text;
    return new Intl.DateTimeFormat(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    }).format(date);
  };

  const refreshCopy = (rule) => {
    const label = formatDate(rule && rule.nextRefreshDate);
    return label ? ` Entitlement refreshes on ${label}.` : '';
  };

  const customerMessage = ({
    rule,
    cartQuantity = 0,
    requestedQuantity = 1,
    mode = 'add',
    loginRequired = false,
  }) => {
    if (loginRequired) {
      return 'Sign in to purchase this limited item. Purchase limits are tracked across customer orders.';
    }

    const inCart = quantity(cartQuantity, 0);
    const requested = Math.max(1, quantity(requestedQuantity, 1));
    const purchased = quantity(rule.purchased, 0);
    const availableForCart = Math.max(0, rule.maximum - purchased);
    const remaining = Math.max(0, availableForCart - inCart);
    const history = purchased > 0 ? ` ${units(purchased)} previously purchased.` : '';
    const cart = inCart > 0 ? ` ${units(inCart)} currently in your cart.` : '';
    const refresh = refreshCopy(rule);

    if (mode === 'cart') {
      return `Cart quantity exceeds the customer purchase limit. You may have up to ${units(availableForCart)} in your cart for this entitlement period (${units(rule.maximum)} total per customer).${history}${refresh}`;
    }

    if (remaining === 0) {
      return `Purchase limit reached.${history}${cart} The limit is ${units(rule.maximum)} per customer.${refresh}`;
    }

    if (requested > remaining) {
      return `Purchase limit exceeded. You can add up to ${units(remaining)} more.${history}${cart} The limit is ${units(rule.maximum)} per customer.${refresh}`;
    }

    return `Maximum quantity reached.${history}${cart} The limit is ${units(rule.maximum)} per customer.${refresh}`;
  };

  const customerLimitForVariant = (variantId) => {
    const rule = ruleForVariant(variantId);
    if (!rule) return null;

    const inCart = cartHandleQuantity(rule.handle);
    if (config().loggedIn !== true) {
      return {
        customerEntitlement: true,
        maximum: 0,
        totalMaximum: 0,
        currentQuantity: inCart,
        rule,
        loginRequired: true,
        reason: (window.purchaseStrings || {}).customerLimit || 'a customer limit',
      };
    }

    const availableForCart = Math.max(0, rule.maximum - rule.purchased);
    return {
      customerEntitlement: true,
      maximum: Math.max(0, availableForCart - inCart),
      totalMaximum: availableForCart,
      currentQuantity: inCart,
      rule,
      loginRequired: false,
      reason: (window.purchaseStrings || {}).customerLimit || 'a customer limit',
    };
  };

  const blockedAddition = (variantId, requestedQuantity) => {
    const limit = customerLimitForVariant(variantId);
    if (!limit) return null;

    const requested = Math.max(1, quantity(requestedQuantity, 1));
    if (!limit.loginRequired && requested <= limit.maximum) return null;

    return {
      limit,
      message: customerMessage({
        rule: limit.rule,
        cartQuantity: limit.currentQuantity,
        requestedQuantity: requested,
        loginRequired: limit.loginRequired,
      }),
    };
  };

  const showProductMessage = (productForm, message, state = 'error') => {
    if (!productForm) return;
    if (typeof productForm.showQuantityLimit === 'function') {
      productForm.showQuantityLimit(message, state);
    }
    if (typeof productForm.setPurchaseButtonsLimited === 'function') {
      productForm.setPurchaseButtonsLimited(state === 'error');
    }
  };

  const enhanceProductForm = () => {
    const ProductForm = customElements.get('product-form');
    if (!ProductForm || ProductForm.prototype.customerOrderLimitsEnhanced) return;

    const prototype = ProductForm.prototype;
    const previousGetQuantityLimit = prototype.getQuantityLimit;
    const previousValidateQuantity = prototype.validateQuantity;
    const previousRememberRejectedQuantity = prototype.rememberRejectedQuantity;
    const previousRenderErrorMsg = prototype.renderErrorMsg;
    const previousOpenBuyNowLimitModal = prototype.openBuyNowLimitModal;

    Object.defineProperty(prototype, 'customerOrderLimitsEnhanced', {
      value: true,
    });

    prototype.getCustomerLimitVariantId = function getCustomerLimitVariantId() {
      if (!this.form) return '';
      const selected = this.form.querySelector('[name="id"]');
      return selected ? selected.value : '';
    };

    prototype.getQuantityLimit = function getQuantityLimitWithCustomerOrders() {
      const existing = previousGetQuantityLimit.call(this);
      const customer = customerLimitForVariant(this.getCustomerLimitVariantId());

      if (!customer) return existing;
      if (!existing || customer.maximum < existing.maximum) return customer;
      return existing;
    };

    prototype.validateQuantity = function validateQuantityWithCustomerOrders(
      focusInvalid = false
    ) {
      if (!this.quantityInput) return previousValidateQuantity.call(this, focusInvalid);
      if (typeof this.bindPurchaseLimitInteraction === 'function') {
        this.bindPurchaseLimitInteraction();
      }

      const selected = Math.max(
        1,
        Number.parseInt(this.quantityInput.value, 10) || 1
      );
      const limit = this.getQuantityLimit();

      if (!limit || !limit.customerEntitlement) {
        return previousValidateQuantity.call(this, focusInvalid);
      }

      this.quantityInput.setAttribute('max', String(limit.maximum));
      if (selected <= limit.maximum) {
        if (typeof this.clearQuantityLimit === 'function') this.clearQuantityLimit();
        if (typeof this.setPurchaseButtonsLimited === 'function') {
          this.setPurchaseButtonsLimited(false);
        }
        return true;
      }

      const shouldShow = focusInvalid || this.purchaseLimitInteracted === true;
      if (shouldShow) {
        const message = customerMessage({
          rule: limit.rule,
          cartQuantity: limit.currentQuantity,
          requestedQuantity: selected,
          loginRequired: limit.loginRequired,
        });
        showProductMessage(this, message, 'error');
        if (focusInvalid) this.quantityInput.focus();
      } else {
        if (typeof this.clearQuantityLimit === 'function') this.clearQuantityLimit();
        if (typeof this.setPurchaseButtonsLimited === 'function') {
          this.setPurchaseButtonsLimited(false);
        }
      }
      return false;
    };

    prototype.rememberRejectedQuantity = function rememberCustomerOrderLimit(
      variantId,
      requestedQuantity,
      message
    ) {
      if (ruleForVariant(variantId)) {
        this.customerOrderLimitMessage = String(message || '');
        this.validateQuantity();
        return;
      }
      previousRememberRejectedQuantity.call(
        this,
        variantId,
        requestedQuantity,
        message
      );
    };

    prototype.openBuyNowLimitModal = function openCustomerOrderLimitModal(message) {
      if (!this.customerOrderLimitMessage) {
        previousOpenBuyNowLimitModal.call(this, message);
        return;
      }

      if (!this.buyNowLimitModal || !this.buyNowLimitMessage) {
        this.renderErrorMsg(message);
        return;
      }

      this.buyNowLimitMessage.textContent = String(message || this.customerOrderLimitMessage);
      if (typeof this.buyNowLimitModal.showModal === 'function') {
        if (!this.buyNowLimitModal.open) this.buyNowLimitModal.showModal();
      } else {
        this.buyNowLimitModal.setAttribute('open', '');
      }
    };

    prototype.renderErrorMsg = function renderCustomerOrderLimit(message) {
      if (!this.customerOrderLimitMessage) {
        previousRenderErrorMsg.call(this, message);
        return;
      }

      const container = this.form && this.form.querySelector('.form__message');
      const content = this.form && this.form.querySelector('.js-error-content');
      if (!container || !content) return;
      content.textContent = String(message || this.customerOrderLimitMessage);
      container.classList.remove('hidden');
    };

    document.querySelectorAll('product-form').forEach((productForm) => {
      if (typeof productForm.validateQuantity === 'function') {
        productForm.validateQuantity();
      }
    });
  };

  const getUpdateQuantities = (body) => {
    if (!body || typeof body !== 'object') return null;
    const updates = body.updates != null ? body.updates : body['updates[]'];
    if (Array.isArray(updates)) return updates.map((value) => quantity(value, 0));
    if (updates && typeof updates === 'object') {
      return Object.keys(updates)
        .sort((left, right) => Number(left) - Number(right))
        .map((key) => quantity(updates[key], 0));
    }
    return null;
  };

  const handleQuantitiesForUpdate = (updates) => {
    if (!updates) return null;
    const result = {};

    cartLines().forEach((line, index) => {
      const handle = String(line.handle || handleForVariant(line.variantId) || '');
      if (!handle) return;
      const nextQuantity = updates[index] == null
        ? quantity(line.quantity, 0)
        : quantity(updates[index], 0);
      result[handle] = (result[handle] || 0) + nextQuantity;
    });

    return result;
  };

  const cartViolation = (handleQuantities) => {
    for (const [handle, rawQuantity] of Object.entries(handleQuantities || {})) {
      const inCart = quantity(rawQuantity, 0);
      if (inCart <= 0) continue;

      const rule = ruleForHandle(handle);
      if (!rule) continue;

      if (config().loggedIn !== true) {
        return {
          message: customerMessage({
            rule,
            cartQuantity: inCart,
            loginRequired: true,
            mode: 'cart',
          }),
        };
      }

      const availableForCart = Math.max(0, rule.maximum - rule.purchased);
      if (inCart > availableForCart) {
        return {
          message: customerMessage({
            rule,
            cartQuantity: inCart,
            mode: 'cart',
          }),
        };
      }
    }
    return null;
  };

  const syncCartUpdate = (updates) => {
    if (!updates) return;
    const byHandle = {};
    const byVariant = {};

    cartLines().forEach((line, index) => {
      const nextQuantity = updates[index] == null
        ? quantity(line.quantity, 0)
        : quantity(updates[index], 0);
      line.quantity = nextQuantity;

      const variantId = String(line.variantId || '');
      if (variantId) byVariant[variantId] = (byVariant[variantId] || 0) + nextQuantity;

      const handle = String(line.handle || handleForVariant(variantId) || '');
      if (handle) byHandle[handle] = (byHandle[handle] || 0) + nextQuantity;
    });

    Object.entries(byVariant).forEach(([variantId, value]) => {
      setCartVariantQuantity(variantId, value);
    });
    Object.entries(byHandle).forEach(([handle, value]) => {
      setCartHandleQuantity(handle, value);
    });
  };

  const syncRemovedLine = (body) => {
    const itemId = String((body && body.item_id) || '');
    const variantId = String((body && body.variant_id) || '');
    const lines = cartLines();
    const index = lines.findIndex((line) => (
      (itemId && String(line.itemId || '') === itemId)
      || (!itemId && variantId && String(line.variantId || '') === variantId)
    ));
    if (index < 0) return;

    const [removed] = lines.splice(index, 1);
    const removedQuantity = quantity(removed.quantity, 0);
    const removedVariantId = String(removed.variantId || '');
    const removedHandle = String(
      removed.handle || handleForVariant(removedVariantId) || ''
    );

    if (removedVariantId) {
      setCartVariantQuantity(
        removedVariantId,
        Math.max(
          0,
          quantity(cartVariants()[removedVariantId], 0) - removedQuantity
        )
      );
    }
    if (removedHandle) {
      setCartHandleQuantity(
        removedHandle,
        Math.max(0, cartHandleQuantity(removedHandle) - removedQuantity)
      );
    }
  };

  const callbackError = (callback, message, cartShape = false) => {
    if (typeof callback !== 'function') return;
    window.setTimeout(() => {
      callback(cartShape
        ? {
          error: { message },
          item_count: Object.values(cartVariants())
            .reduce((total, value) => total + quantity(value, 0), 0),
        }
        : { description: message, customer_purchase_limit: true });
    }, 0);
  };

  const patchActions = (attempt = 0) => {
    const action = window.EasyStore && window.EasyStore.Action;
    if (!action || typeof action.addToCart !== 'function') {
      if (attempt < 50) window.setTimeout(() => patchActions(attempt + 1), 100);
      return;
    }

    if (!action.addToCart.customerOrderLimitsEnhanced) {
      const previousAddToCart = action.addToCart;
      const enhancedAddToCart = function addToCartWithCustomerOrderLimits(
        body,
        callback
      ) {
        const blocked = body && blockedAddition(body.id, body.quantity);
        if (blocked) {
          callbackError(callback, blocked.message);
          return undefined;
        }

        return previousAddToCart.call(this, body, (cart) => {
          const response = cart || {};
          const hasError = response.description != null && response.description !== '';
          const latestItems = Array.isArray(response.latest_items)
            ? response.latest_items
            : [];
          if (!hasError && latestItems.length > 0 && body && body.id) {
            const added = Math.max(1, quantity(body.quantity, 1));
            const handle = handleForVariant(body.id);
            if (handle) {
              setCartHandleQuantity(handle, cartHandleQuantity(handle) + added);
            }
          }
          if (typeof callback === 'function') callback(cart);
        });
      };
      Object.defineProperty(enhancedAddToCart, 'customerOrderLimitsEnhanced', {
        value: true,
      });
      action.addToCart = enhancedAddToCart;
    }

    if (
      typeof action.updateCart === 'function'
      && !action.updateCart.customerOrderLimitsEnhanced
    ) {
      const previousUpdateCart = action.updateCart;
      const enhancedUpdateCart = function updateCartWithCustomerOrderLimits(
        body,
        callback
      ) {
        const updates = getUpdateQuantities(body);
        const violation = cartViolation(handleQuantitiesForUpdate(updates));
        if (violation) {
          callbackError(callback, violation.message, true);
          return undefined;
        }

        return previousUpdateCart.call(this, body, (cart) => {
          const response = cart || {};
          if (!(response.error && response.error.message)) syncCartUpdate(updates);
          if (typeof callback === 'function') callback(cart);
        });
      };
      Object.defineProperty(enhancedUpdateCart, 'customerOrderLimitsEnhanced', {
        value: true,
      });
      action.updateCart = enhancedUpdateCart;
    }

    if (
      typeof action.removeCartItem === 'function'
      && !action.removeCartItem.customerOrderLimitsEnhanced
    ) {
      const previousRemoveCartItem = action.removeCartItem;
      const enhancedRemoveCartItem = function removeCartItemWithCustomerOrderLimits(
        body,
        callback
      ) {
        return previousRemoveCartItem.call(this, body, (cart) => {
          const response = cart || {};
          if (!(response.error && response.error.message)) syncRemovedLine(body);
          if (typeof callback === 'function') callback(cart);
        });
      };
      Object.defineProperty(enhancedRemoveCartItem, 'customerOrderLimitsEnhanced', {
        value: true,
      });
      action.removeCartItem = enhancedRemoveCartItem;
    }
  };

  const showCartError = (message) => {
    const container = document.querySelector('.cart_form__error');
    const content = container && container.querySelector('.js-error-content');

    if (container && content) {
      content.textContent = message;
      container.classList.remove('hidden');
      window.scrollTo(0, 0);
      return;
    }

    window.alert(message);
  };

  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!form) return;

    const isCheckoutForm = form.id === 'cart-form'
      || form.querySelector('[name="checkout"]')
      || (event.submitter && event.submitter.name === 'checkout');
    if (!isCheckoutForm) return;

    const violation = cartViolation(cartHandles());
    if (!violation) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    showCartError(violation.message);
  }, true);

  const sharedFeedback = window.PurchaseLimitFeedback;
  if (
    sharedFeedback
    && typeof sharedFeedback.format === 'function'
    && !sharedFeedback.format.customerOrderLimitsEnhanced
  ) {
    const previousFormat = sharedFeedback.format;
    const enhancedFormat = function formatCustomerOrderLimitFeedback(context = {}) {
      const rawMessage = String(context.rawMessage || '');
      if (/(per customer|customer orders|entitlement refreshes)/i.test(rawMessage)) {
        return typeof sharedFeedback.stripMarkup === 'function'
          ? sharedFeedback.stripMarkup(rawMessage)
          : rawMessage;
      }
      return previousFormat(context);
    };
    Object.defineProperty(enhancedFormat, 'customerOrderLimitsEnhanced', {
      value: true,
    });
    sharedFeedback.format = enhancedFormat;
  }

  window.CustomerPurchaseLimits = {
    ruleForHandle,
    ruleForVariant,
    handleForVariant,
    blockedAddition,
    cartViolation,
  };

  patchActions();
  if (customElements.get('product-form')) {
    enhanceProductForm();
  } else {
    customElements.whenDefined('product-form').then(enhanceProductForm);
  }
})();
