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

  // The supplied label is read alongside the message because the surfaces that
  // raise a limit from live numbers pass no message at all. Judging those on the
  // message alone always landed on the generic branch, so a customer limit was
  // described as a bare maximum instead of a per-customer one.
  const inferReason = (value, fallbackLabel = '') => {
    const text = `${stripMarkup(value)} ${stripMarkup(fallbackLabel)}`
      .trim()
      .toLowerCase();
    const strings = window.purchaseStrings || {};

    if (/(inventory|stock|available|only left|left\s+\d+\s+unit|\d+\s+unit(?:s|\(s\))?\s+left)/i.test(text)) {
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

  // A whole clause rather than a noun phrase: the copy states what the ceiling
  // is, so it never has to be glued into an equation to make sense.
  const limitClause = (reason, maximum) => {
    switch (reason.key) {
      case 'inventory':
        return `only ${unitLabel(maximum)} ${maximum === 1 ? 'is' : 'are'} available`;
      case 'customer':
        return `the limit is ${unitLabel(maximum)} per customer`;
      case 'promotion':
        return `the limit is ${unitLabel(maximum)} for this promotion`;
      case 'store':
        return `the limit is ${unitLabel(maximum)} for this store`;
      case 'order':
        return `the limit is ${unitLabel(maximum)} per order`;
      default:
        return `the limit is ${unitLabel(maximum)}`;
    }
  };

  const sentence = (clause) => `${clause.charAt(0).toUpperCase()}${clause.slice(1)}`;

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
      // A ceiling of zero is never worth quoting: "the limit is 0 units" is the
      // kind of sentence that sent shoppers looking for a number that means
      // something. Say plainly that nothing more can be added.
      if (parsedMaximum <= 0) {
        return current > 0
          ? `Maximum quantity reached. You already have ${unitLabel(current)} in your cart and cannot add more of this item.`
          : 'Maximum quantity reached. This item cannot be added right now.';
      }

      const remaining = Math.max(0, parsedMaximum - current);
      const clause = limitClause(inferredReason, parsedMaximum);

      if (mode === 'reached') {
        if (current > 0) {
          return `Maximum quantity reached. You already have ${unitLabel(current)} in your cart, and ${clause}.`;
        }
        return `Maximum quantity reached. ${sentence(clause)}.`;
      }

      if (current > 0 && remaining === 0) {
        if (inferredReason.key === 'inventory') {
          return `Stock limit reached. You already have ${unitLabel(current)} in your cart, and ${clause}.`;
        }
        return `Purchase limit reached. You already have ${unitLabel(current)} in your cart, and ${clause}.`;
      }

      if (requested > remaining) {
        if (remaining > 0) {
          return `Quantity limit exceeded. You can add up to ${unitLabel(remaining)} more because ${clause}.`;
        }
        return `Quantity limit exceeded. ${sentence(clause)}.`;
      }

      return `Unable to add this item. ${sentence(clause)}.`;
    }

    if (cleanMessage) return cleanMessage;

    return window.purchaseStrings && window.purchaseStrings.addLimitError
      ? stripMarkup(window.purchaseStrings.addLimitError)
      : 'Unable to add this item because a quantity limit was reached.';
  };

  // A limit that phrased its own copy already knows what the cart holds and what
  // earlier orders used. Rebuilding a sentence from its numbers here would drop
  // the part about past orders and disagree with the cart and listing wording,
  // so its message is quoted as written. Only rejections carrying a raw store
  // message get rewritten.
  const limitMessage = (limit, context) => (
    limit && limit.contextual === true && limit.message
      ? stripMarkup(limit.message)
      : format(context)
  );

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

    prototype.bindPurchaseLimitInteraction = function bindPurchaseLimitInteraction() {
      if (!this.quantityInput || this.quantityInput.dataset.purchaseLimitInteractionBound === 'true') {
        return;
      }

      const markInteraction = () => {
        this.purchaseLimitInteracted = true;
      };

      this.quantityInput.dataset.purchaseLimitInteractionBound = 'true';
      this.quantityInput.addEventListener('input', markInteraction, { capture: true });
      this.quantityInput.addEventListener('change', markInteraction, { capture: true });
    };

    prototype.getCurrentCartQuantity = function getCurrentCartQuantity(variantId) {
      return getCartQuantity(variantId || getVariantId(this));
    };

    prototype.getQuantityLimit = function getContextualQuantityLimit() {
      const limit = originalGetQuantityLimit.call(this);
      if (!limit) return null;

      const currentQuantity = this.getCurrentCartQuantity();

      // A source that measured the cart itself reports what is still addable,
      // so subtracting the cart again would count it twice — and its own total
      // is the ceiling to quote, not the nothing that is left of it.
      if (limit.contextual === true) {
        return {
          ...limit,
          maximum: Math.max(0, toQuantity(limit.maximum, 0)),
          totalMaximum: toQuantity(
            limit.totalMaximum != null ? limit.totalMaximum : limit.maximum,
            0
          ),
          currentQuantity: toQuantity(limit.currentQuantity, currentQuantity),
        };
      }

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

    prototype.updatePlusButton = function updateContextualPlusButton(maximum) {
      if (!this.quantityInput) return;
      const plusButton = this.quantityInput
        .closest('quantity-input')
        ?.querySelector('[name="plus"]');
      if (!plusButton) return;

      if (plusButton.dataset.quantityLimitDisabled === 'true') {
        plusButton.removeAttribute('disabled');
        plusButton.removeAttribute('aria-disabled');
        delete plusButton.dataset.quantityLimitDisabled;
      }

      plusButton.dataset.purchaseLimitMaximum = maximum == null ? '' : String(maximum);

      if (plusButton.dataset.purchaseLimitFeedbackBound === 'true') return;
      plusButton.dataset.purchaseLimitFeedbackBound = 'true';
      plusButton.addEventListener('click', () => {
        const allowedMaximum = Number.parseInt(
          plusButton.dataset.purchaseLimitMaximum,
          10
        );
        const selectedQuantity = Math.max(
          1,
          Number.parseInt(this.quantityInput.value, 10) || 1
        );

        if (!Number.isFinite(allowedMaximum) || selectedQuantity < allowedMaximum) return;

        const limit = this.getQuantityLimit();
        if (!limit) return;

        this.purchaseLimitInteracted = true;
        this.showQuantityLimit(
          limitMessage(limit, {
            currentQuantity: limit.currentQuantity,
            requestedQuantity: selectedQuantity,
            maximum: limit.totalMaximum,
            reason: limit.reason,
            mode: 'reached',
          }),
          'warning'
        );
      });
    };

    prototype.validateQuantity = function validateContextualQuantity(focusInvalid = false) {
      if (!this.quantityInput) return true;
      this.bindPurchaseLimitInteraction();

      const quantity = Math.max(1, Number.parseInt(this.quantityInput.value, 10) || 1);
      const limit = this.getQuantityLimit();
      this.updatePlusButton(limit && limit.maximum);

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
        const shouldShow = focusInvalid || this.purchaseLimitInteracted === true;
        if (shouldShow) {
          this.showQuantityLimit(limitMessage(limit, { ...context, mode: 'error' }), 'error');
          this.setPurchaseButtonsLimited(true);
          if (focusInvalid) this.quantityInput.focus();
        } else {
          this.clearQuantityLimit();
          this.setPurchaseButtonsLimited(false);
        }
        return false;
      }

      this.clearQuantityLimit();
      this.setPurchaseButtonsLimited(false);
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