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

  // One ceiling, three sentence positions, so each reason spells all three out
  // together rather than being reassembled at each use: `clause` follows "Limit
  // reached:", `short` sits in a parenthetical where the noun is already in the
  // sentence, and `sentence` states the ceiling on its own.
  const ceiling = (reason, maximum) => {
    switch (reason.key) {
      case 'inventory':
        return {
          clause: `only ${unitLabel(maximum)} in stock`,
          short: `only ${maximum} left`,
          sentence: `Only ${unitLabel(maximum)} left.`,
        };
      case 'customer':
        return {
          clause: `${unitLabel(maximum)} per customer`,
          short: `${maximum} per customer`,
          sentence: `Maximum ${unitLabel(maximum)} per customer.`,
        };
      case 'promotion':
        return {
          clause: `${unitLabel(maximum)} for this promotion`,
          short: `${maximum} for this promotion`,
          sentence: `Maximum ${unitLabel(maximum)} for this promotion.`,
        };
      case 'store':
        return {
          clause: `${unitLabel(maximum)} for this store`,
          short: `${maximum} for this store`,
          sentence: `Maximum ${unitLabel(maximum)} for this store.`,
        };
      case 'order':
        return {
          clause: `${unitLabel(maximum)} per order`,
          short: `${maximum} per order`,
          sentence: `Maximum ${unitLabel(maximum)} per order.`,
        };
      default:
        return {
          clause: unitLabel(maximum),
          short: String(maximum),
          sentence: `Maximum ${unitLabel(maximum)}.`,
        };
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
      // A ceiling of zero is never worth quoting: "the limit is 0 units" is the
      // kind of sentence that sent shoppers looking for a number that means
      // something. Say plainly that nothing more can be added.
      if (parsedMaximum <= 0) {
        return current > 0
          ? `Limit reached. You have ${unitLabel(current)} in your cart.`
          : 'This item cannot be added right now.';
      }

      const remaining = Math.max(0, parsedMaximum - current);
      const limit = ceiling(inferredReason, parsedMaximum);

      // Nothing left to add, whether the shopper is at the ceiling or asked for
      // more than it allows. One message covers both: the ceiling, and what the
      // cart already holds of it.
      if (mode === 'reached' || remaining === 0) {
        return current > 0
          ? `Limit reached: ${limit.clause}. You have ${current} in your cart.`
          : `Limit reached: ${limit.clause}.`;
      }

      // A cap, not an action. This lands under the quantity picker, where "you
      // can add 2 more units" read as add-to-cart and invited the 2 to be
      // measured against the field rather than against the cart.
      if (requested > remaining) {
        return current > 0
          ? `Maximum ${unitLabel(remaining)} (${limit.short}).`
          : limit.sentence;
      }

      return `Unable to add this item (${limit.short}).`;
    }

    if (cleanMessage) return cleanMessage;

    return window.purchaseStrings && window.purchaseStrings.addLimitError
      ? stripMarkup(window.purchaseStrings.addLimitError)
      : 'This item cannot be added right now.';
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

      // What the field held before `quantity-input` stepped it. Recorded from a
      // capture listener on the wrapper, which runs ahead of the button's own
      // listeners wherever inside the button the click landed.
      const stepper = this.quantityInput.closest('quantity-input');
      if (stepper && stepper.dataset.purchaseLimitStepBound !== 'true') {
        stepper.dataset.purchaseLimitStepBound = 'true';
        stepper.addEventListener('click', (event) => {
          if (!event.target?.closest?.('[name="plus"]')) return;
          stepper.dataset.purchaseLimitQuantityBefore = String(
            Math.max(1, Number.parseInt(this.quantityInput.value, 10) || 1)
          );
        }, { capture: true });
      }

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

        // The step landed, so the shopper has exactly what they asked for and is
        // at the ceiling rather than past it. Selecting the last unit you are
        // allowed to buy is not a limit to be told about; only a refused step is.
        const before = Number.parseInt(
          stepper && stepper.dataset.purchaseLimitQuantityBefore,
          10
        );
        if (Number.isFinite(before) && selectedQuantity !== before) return;

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

      // Never below the field's own minimum. `max="0"` against `min="1"` is an
      // impossible range, so the browser refused the submit with "Minimum value
      // (1) must be less than the maximum value (0)." — a developer's sentence,
      // shown to a shopper, in place of ours, which never got to run. Held at 1,
      // the field stays valid, the submit reaches the purchase guard, and the
      // guard answers with the limit copy.
      this.quantityInput.setAttribute('max', String(Math.max(1, limit.maximum)));
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
        container.dataset.purchaseLimitMessage = 'false';
        content.textContent = cleanMessage;
        container.classList.remove('hidden');
        return;
      }

      const context = this.lastRejectedQuantityContext || {
        rawMessage: cleanMessage,
        currentQuantity: this.getCurrentCartQuantity(),
        requestedQuantity: this.quantityInput ? this.quantityInput.value : 1,
      };
      const text = format({ ...context, rawMessage: cleanMessage });

      // The store's own rejection stays in the alert. Routing it to the quantity
      // note instead lost it outright: `setSubmitting` revalidates immediately
      // afterwards, and a quantity that no longer breaches the rejected maximum
      // clears the note, leaving the shopper with no message at all. If that
      // revalidation does raise the note, it hides this alert on its way in, so
      // the two still never show the same sentence together.
      container.dataset.purchaseLimitMessage = 'true';
      content.textContent = text;
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