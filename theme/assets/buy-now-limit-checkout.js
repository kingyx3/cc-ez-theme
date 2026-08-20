(() => {
  'use strict';

  const toQuantity = (value, fallback = 0) => {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
  };

  const productHandle = (form) => {
    if (!form || !window.CustomerOrderLimits) return '';
    return form.dataset.productHandle
      || window.CustomerOrderLimits.productHandle(form);
  };

  const restoreBuyNowButton = (productForm) => {
    productForm.querySelectorAll('[data-buy-now]').forEach((button) => {
      if (button.dataset.quantityLimitDisabled !== 'true') return;

      if (button.dataset.quantityLimitWasDisabled === 'false') {
        button.removeAttribute('disabled');
        button.removeAttribute('aria-disabled');
      }
      delete button.dataset.quantityLimitDisabled;
      delete button.dataset.quantityLimitWasDisabled;
    });
  };

  const enhanceProductForm = () => {
    const ProductForm = customElements.get('product-form');
    if (!ProductForm || ProductForm.prototype.buyNowLimitCheckoutEnhanced) return;

    const prototype = ProductForm.prototype;
    Object.defineProperty(prototype, 'buyNowLimitCheckoutEnhanced', {
      value: true,
    });

    prototype.setPurchaseButtonsLimited = function setAddToCartLimited(limited) {
      this.querySelectorAll('[name="add"]').forEach((button) => {
        if (limited) {
          if (button.dataset.quantityLimitDisabled !== 'true') {
            button.dataset.quantityLimitWasDisabled = button.matches(
              '[disabled], [aria-disabled="true"]'
            ) ? 'true' : 'false';
          }
          button.dataset.quantityLimitDisabled = 'true';
          button.setAttribute('disabled', true);
          button.setAttribute('aria-disabled', 'true');
          return;
        }

        if (button.dataset.quantityLimitDisabled === 'true') {
          if (button.dataset.quantityLimitWasDisabled === 'false') {
            button.removeAttribute('disabled');
            button.removeAttribute('aria-disabled');
          }
          delete button.dataset.quantityLimitDisabled;
          delete button.dataset.quantityLimitWasDisabled;
        }
      });

      restoreBuyNowButton(this);
    };

    document.querySelectorAll('product-form').forEach((productForm) => {
      restoreBuyNowButton(productForm);
      if (typeof productForm.validateQuantity === 'function') {
        productForm.validateQuantity();
      }
    });
  };

  const quantityLimitMessage = (productForm, limit, requestedQuantity) => {
    if (limit && limit.message) return String(limit.message);

    const strings = window.purchaseStrings || {};
    if (limit && strings.quantityExceeded) {
      return String(strings.quantityExceeded)
        .replace('__QUANTITY__', requestedQuantity)
        .replace('__MAXIMUM__', limit.maximum)
        .replace('__REASON__', limit.reason || strings.purchaseLimit || 'a purchase limit');
    }

    return String(
      strings.addLimitError
      || 'This item cannot be added right now.'
    );
  };

  document.addEventListener('click', (event) => {
    const buyNowButton = event.target.closest?.('[data-buy-now]');
    if (!buyNowButton) return;

    const productForm = buyNowButton.closest('product-form');
    const form = productForm?.form || productForm?.querySelector('form');
    if (!productForm || !form) return;

    const limits = window.CustomerOrderLimits;
    if (
      limits
      && limits.loginRequiredForHandle(productHandle(form))
      && limits.redirectToLogin({
        handle: productHandle(form),
        quantity: form.querySelector('[name="quantity"]')?.value,
        surface: 'buy-now',
      })
    ) {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }

    const handle = productHandle(form);
    const requestedQuantity = Math.max(
      1,
      toQuantity(form.querySelector('[name="quantity"]')?.value, 1)
    );
    const customerViolation = limits
      ? limits.additionViolation(handle, requestedQuantity)
      : null;

    // The cart already holds every unit this customer may buy, so Buy Now means
    // "check out with what I have" — adding another unit would only fail.
    if (
      customerViolation
      && customerViolation.remaining <= 0
      && limits.cartQuantityForHandle(handle) > 0
      && typeof productForm.goToCheckout === 'function'
    ) {
      event.preventDefault();
      event.stopImmediatePropagation();
      productForm.goToCheckout();
      return;
    }

    let message = customerViolation ? customerViolation.message : '';
    if (!message && typeof productForm.getQuantityLimit === 'function') {
      const limit = productForm.getQuantityLimit();
      if (!limit || requestedQuantity <= limit.maximum) return;
      message = quantityLimitMessage(productForm, limit, requestedQuantity);
    }

    if (!message) return;

    event.preventDefault();
    event.stopImmediatePropagation();

    if (typeof productForm.openBuyNowLimitModal === 'function') {
      productForm.openBuyNowLimitModal(String(message));
      return;
    }

    if (limits) {
      limits.showProductError(form, message);
    }
  }, true);

  if (customElements.get('product-form')) {
    enhanceProductForm();
  } else {
    customElements.whenDefined('product-form').then(enhanceProductForm);
  }
})();
