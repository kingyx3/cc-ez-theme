(() => {
  'use strict';

  const cartQuantities = () => {
    window.purchaseCartQuantities = window.purchaseCartQuantities || {};
    return window.purchaseCartQuantities;
  };

  const toQuantity = (value, fallback = 0) => {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
  };

  const unitLabel = (quantity) => `${quantity} unit${quantity === 1 ? '' : 's'}`;

  const stripMarkup = (value) => {
    const container = document.createElement('div');
    container.innerHTML = String(value == null ? '' : value);
    return (container.textContent || container.innerText || '')
      .replace(/\s+/g, ' ')
      .trim();
  };

  const extractMaximum = (value, fallback = null) => {
    const text = stripMarkup(value);
    const patterns = [
      /only\s+(?:has\s+)?(?:left\s+)?(\d+)\s+unit/i,
      /(\d+)\s+unit(?:\(s\))?\s+(?:left|available)/i,
      /(?:maximum|max(?:imum)?|limit(?:ed)?(?:\s+to)?|up\s+to)\D{0,30}(\d+)/i,
    ];

    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (match) return toQuantity(match[1], fallback);
    }

    return fallback;
  };

  const isLimitMessage = (value) => {
    const text = stripMarkup(value);
    return /(limit|maximum|max\b|exceed|stock|inventory|available|only left|left\s+\d+\s+unit|promotion|promo|customer|purchase|order quantity)/i.test(text)
      || extractMaximum(text, null) != null;
  };

  const inferReason = (value, fallbackLabel = '') => {
    const text = stripMarkup(value).toLowerCase();
    const strings = window.purchaseStrings || {};

    if (/(inventory|stock|available|only left|left\s+\d+\s+unit)/i.test(text)) {
      return { key: 'inventory', label: strings.inventoryLimit || 'inventory' };
    }
    if (/(customer|member|per customer)/i.test(text)) {
      return { key: 'customer', label: strings.customerLimit || 'customer limit' };
    }
    if (/(promotion|promo)/i.test(text)) {
      return { key: 'promotion', label: strings.promotionLimit || 'promotion limit' };
    }
    if (/(store limit|store purchase)/i.test(text)) {
      return { key: 'store', label: strings.storeLimit || 'store limit' };
    }
    if (/(order limit|per order|order quantity)/i.test(text)) {
      return { key: 'order', label: strings.orderLimit || 'order limit' };
    }
    if (/(quantity rule|configured limit)/i.test(text)) {
      return { key: 'quantity', label: fallbackLabel || strings.quantityRule || 'quantity limit' };
    }

    return {
      key: 'purchase',
      label: fallbackLabel || strings.purchaseLimit || 'purchase limit',
    };
  };

  const getCartQuantity = (variantId) => {
    if (variantId == null || variantId === '') return 0;
    return toQuantity(cartQuantities()[String(variantId)], 0);
  };

  const setCartQuantity = (variantId, quantity) => {
    if (variantId == null || variantId === '') return;
    cartQuantities()[String(variantId)] = toQuantity(quantity, 0);
  };

  const incrementCartQuantity = (variantId, quantity) => {
    setCartQuantity(
      variantId,
      getCartQuantity(variantId) + Math.max(0, toQuantity(quantity, 0))
    );
  };

  const limitStatement = (reason, maximum) => {
    switch (reason.key) {
      case 'inventory':
        return `only ${unitLabel(maximum)} ${maximum === 1 ? 'is' : 'are'} available`;
      case 'customer':
        return `customer limit is ${unitLabel(maximum)}`;
      case 'promotion':
        return `promotion limit is ${unitLabel(maximum)}`;
      case 'store':
        return `store limit is ${unitLabel(maximum)}`;
      case 'order':
        return `order limit is ${unitLabel(maximum)}`;
      default:
        return `maximum is ${unitLabel(maximum)} (${reason.label})`;
    }
  };

  const reasonName = (reason) => {
    switch (reason.key) {
      case 'inventory': return 'inventory limit';
      case 'customer': return 'customer limit';
      case 'promotion': return 'promotion limit';
      case 'store': return 'store limit';
      case 'order': return 'order limit';
      default: return reason.label || 'purchase limit';
    }
  };

  const format = ({
    rawMessage = '',
    currentQuantity = 0,
    requestedQuantity = 1,
    maximum = null,
    reason = '',
    mode = 'error',
  } = {}) => {
    const cleanMessage = stripMarkup(rawMessage);
    const current = toQuantity(currentQuantity, 0);
    const requested = Math.max(1, toQuantity(requestedQuantity, 1));
    const parsedMaximum = extractMaximum(cleanMessage, maximum);
    const inferredReason = inferReason(cleanMessage, reason);

    if (parsedMaximum != null) {
      const remaining = Math.max(0, parsedMaximum - current);

      if (mode === 'warning') {
        if (current > 0) {
          return `Maximum reached: ${unitLabel(current)} in cart + ${unitLabel(requested)} selected = ${unitLabel(parsedMaximum)} (${reasonName(inferredReason)}).`;
        }
        return `Maximum reached: ${unitLabel(requested)} selected (${reasonName(inferredReason)}).`;
      }

      if (current > 0 && remaining === 0) {
        return `Limit reached: ${unitLabel(current)} in cart; ${limitStatement(inferredReason, parsedMaximum)}. Remove an item before adding more.`;
      }

      if (current > 0 && requested > remaining) {
        return `You have ${unitLabel(current)} in your cart; ${limitStatement(inferredReason, parsedMaximum)}. You can add ${unitLabel(remaining)} more.`;
      }

      if (requested > parsedMaximum) {
        return `You requested ${unitLabel(requested)}; ${limitStatement(inferredReason, parsedMaximum)}.`;
      }

      return `Unable to add item: ${limitStatement(inferredReason, parsedMaximum)}.`;
    }

    if (cleanMessage) return cleanMessage;

    return window.purchaseStrings && window.purchaseStrings.addLimitError
      ? stripMarkup(window.purchaseStrings.addLimitError)
      : 'Unable to add item: an inventory or purchase limit was reached.';
  };

  const getVariantId = (productForm) => {
    if (!productForm || !productForm.form) return '';
    const selected = productForm.form.querySelector('[name="id"]');
    return selected ? selected.value : '';
  };

  const enhanceProductForm = () => {
    const ProductForm = customElements.get('product-form');
    if (!ProductForm || ProductForm.prototype.contextualPurchaseLimitsEnhanced) return;

    const prototype = ProductForm.prototype;
    const originalGetQuantityLimit = prototype.getQuantityLimit;
    const originalOpenBuyNowLimitModal = prototype.openBuyNowLimitModal;

    Object.defineProperty(prototype, 'contextualPurchaseLimitsEnhanced', {
      value: true,
    });

    prototype.getCurrentCartQuantity = function getCurrentCartQuantity(variantId) {
      return getCartQuantity(variantId || getVariantId(this));
    };

    prototype.getQuantityLimit = function getContextualQuantityLimit() {
      const limit = originalGetQuantityLimit.call(this);
      if (!limit) return null;

      const currentQuantity = this.getCurrentCartQuantity();
      const totalMaximum = toQuantity(
        limit.totalMaximum != null ? limit.totalMaximum : limit.maximum,
        0
      );

      return {
        ...limit,
        maximum: Math.max(0, totalMaximum - currentQuantity),
        totalMaximum,
        currentQuantity,
      };
    };

    prototype.updatePlusButton = function updateContextualPlusButton(maximum, quantity) {
      if (!this.quantityInput) return;
      const plusButton = this.quantityInput
        .closest('quantity-input')
        ?.querySelector('[name="plus"]');
      if (!plusButton) return;

      if (maximum != null && quantity >= maximum) {
        plusButton.dataset.quantityLimitDisabled = 'true';
        plusButton.setAttribute('disabled', true);
        plusButton.setAttribute('aria-disabled', 'true');
      } else if (plusButton.dataset.quantityLimitDisabled === 'true') {
        plusButton.removeAttribute('disabled');
        plusButton.removeAttribute('aria-disabled');
        delete plusButton.dataset.quantityLimitDisabled;
      }
    };

    prototype.validateQuantity = function validateContextualQuantity(focusInvalid = false) {
      if (!this.quantityInput) return true;

      const quantity = Math.max(1, Number.parseInt(this.quantityInput.value, 10) || 1);
      const limit = this.getQuantityLimit();
      this.updatePlusButton(limit && limit.maximum, quantity);

      if (!limit) {
        if (this.nativeQuantityMaximum == null) {
          this.quantityInput.removeAttribute('max');
        } else {
          this.quantityInput.setAttribute('max', this.nativeQuantityMaximum);
        }
        this.clearQuantityLimit();
        this.setPurchaseButtonsLimited(false);
        return true;
      }

      this.quantityInput.setAttribute('max', String(limit.maximum));
      const context = {
        rawMessage: limit.message || '',
        currentQuantity: limit.currentQuantity,
        requestedQuantity: quantity,
        maximum: limit.totalMaximum,
        reason: limit.reason,
      };

      if (quantity > limit.maximum) {
        this.showQuantityLimit(format({ ...context, mode: 'error' }), 'error');
        this.setPurchaseButtonsLimited(true);
        if (focusInvalid) this.quantityInput.focus();
        return false;
      }

      this.setPurchaseButtonsLimited(false);
      if (quantity === limit.maximum) {
        this.showQuantityLimit(format({ ...context, mode: 'warning' }), 'warning');
      } else {
        this.clearQuantityLimit();
      }
      return true;
    };

    prototype.rememberRejectedQuantity = function rememberContextualRejectedQuantity(
      variantId,
      requestedQuantity,
      rawMessage
    ) {
      const cleanMessage = stripMarkup(rawMessage);
      if (!isLimitMessage(cleanMessage)) return;

      const currentQuantity = this.getCurrentCartQuantity(variantId);
      const maximum = extractMaximum(
        cleanMessage,
        Math.max(currentQuantity, currentQuantity + requestedQuantity - 1)
      );
      const inferredReason = inferReason(cleanMessage);

      this.rejectedQuantityLimit = {
        maximum,
        totalMaximum: maximum,
        reason: inferredReason.label,
        reasonKey: inferredReason.key,
        message: cleanMessage,
        variantId: String(variantId || ''),
      };
      this.lastRejectedQuantityContext = {
        rawMessage: cleanMessage,
        currentQuantity,
        requestedQuantity,
        maximum,
        reason: inferredReason.label,
        mode: 'error',
      };
      this.validateQuantity();
    };

    prototype.openBuyNowLimitModal = function openContextualBuyNowLimitModal(message) {
      const context = this.lastRejectedQuantityContext || {
        rawMessage: message,
        currentQuantity: this.getCurrentCartQuantity(),
        requestedQuantity: this.quantityInput ? this.quantityInput.value : 1,
      };
      originalOpenBuyNowLimitModal.call(this, format({ ...context, rawMessage: message }));
    };

    prototype.renderErrorMsg = function renderContextualErrorMessage(message) {
      const container = this.form && this.form.querySelector('.form__message');
      const content = this.form && this.form.querySelector('.js-error-content');
      if (!container || !content) return;

      const cleanMessage = stripMarkup(message);
      if (!this.lastRejectedQuantityContext && !isLimitMessage(cleanMessage)) {
        content.textContent = cleanMessage;
        container.classList.remove('hidden');
        return;
      }

      const context = this.lastRejectedQuantityContext || {
        rawMessage: cleanMessage,
        currentQuantity: this.getCurrentCartQuantity(),
        requestedQuantity: this.quantityInput ? this.quantityInput.value : 1,
      };
      content.textContent = format({ ...context, rawMessage: cleanMessage });
      container.classList.remove('hidden');
    };

    document.querySelectorAll('product-form').forEach((productForm) => {
      if (typeof productForm.validateQuantity === 'function') {
        productForm.validateQuantity();
      }
    });
  };

  const patchAddToCart = (attempt = 0) => {
    const action = window.EasyStore && window.EasyStore.Action;
    if (!action || typeof action.addToCart !== 'function') {
      if (attempt < 50) window.setTimeout(() => patchAddToCart(attempt + 1), 100);
      return;
    }
    if (action.addToCart.contextualPurchaseLimitsEnhanced) return;

    const originalAddToCart = action.addToCart;
    const enhancedAddToCart = function addToCartWithQuantityTracking(body, callback) {
      return originalAddToCart.call(this, body, (cart) => {
        const response = cart || {};
        const hasError = response.description != null && response.description !== '';
        const latestItems = Array.isArray(response.latest_items) ? response.latest_items : [];
        if (!hasError && latestItems.length > 0 && body && body.id) {
          incrementCartQuantity(body.id, body.quantity);
        }
        if (typeof callback === 'function') callback(cart);
      });
    };
    Object.defineProperty(enhancedAddToCart, 'contextualPurchaseLimitsEnhanced', {
      value: true,
    });
    action.addToCart = enhancedAddToCart;
  };

  window.PurchaseLimitFeedback = {
    stripMarkup,
    extractMaximum,
    inferReason,
    isLimitMessage,
    format,
    getCartQuantity,
    setCartQuantity,
    incrementCartQuantity,
  };

  patchAddToCart();
  if (customElements.get('product-form')) {
    enhanceProductForm();
  } else {
    customElements.whenDefined('product-form').then(enhanceProductForm);
  }
})();
