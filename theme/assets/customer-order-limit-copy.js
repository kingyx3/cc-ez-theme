(() => {
  'use strict';

  const quantity = (value, fallback = 0) => {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
  };

  const unitLabel = (value) => {
    const count = quantity(value, 0);
    return `${count} unit${count === 1 ? '' : 's'}`;
  };

  const contextFor = (productForm) => {
    const limits = window.CustomerOrderLimits;
    if (!limits || !productForm) return null;

    const form = productForm.form || productForm.querySelector('form');
    if (!form) return null;

    const handle = form.dataset.productHandle || limits.productHandle(form);
    const rule = limits.ruleFor(handle);
    if (!rule) return null;

    const input = form.querySelector('[name="quantity"]');
    const selectedQuantity = Math.max(1, quantity(input && input.value, 1));
    const remaining = limits.remainingForHandle(handle);
    const customerLimitReached = rule.loginRequired === true
      || (remaining != null && selectedQuantity >= remaining);

    if (!customerLimitReached) return null;

    return {
      rule,
      maximum: quantity(rule.maximum, 0),
      purchased: quantity(rule.purchased, 0),
      cartQuantity: quantity(rule.cartQuantity, 0),
    };
  };

  const correctedCopy = (productForm) => {
    const context = contextFor(productForm);
    if (!context) return '';

    const { rule, maximum, purchased, cartQuantity } = context;
    if (rule.loginRequired === true) {
      return String(rule.message || 'Sign in to purchase this limited item.');
    }
    if (maximum <= 0) return '';

    if (purchased > 0 && cartQuantity > 0) {
      return `Maximum quantity reached. You have already purchased ${unitLabel(purchased)} and have ${unitLabel(cartQuantity)} in your cart. The limit is ${unitLabel(maximum)} per customer across orders.`;
    }
    if (cartQuantity > 0) {
      return `Maximum quantity reached. You already have ${unitLabel(cartQuantity)} in your cart. The limit is ${unitLabel(maximum)} per customer across orders.`;
    }
    if (purchased > 0) {
      return `Customer purchase limit reached. You have already purchased ${unitLabel(purchased)} of the ${unitLabel(maximum)} allowed per customer across orders.`;
    }

    return `Maximum quantity reached. The limit is ${unitLabel(maximum)} per customer across orders.`;
  };

  const enhanceProductForm = () => {
    const ProductForm = customElements.get('product-form');
    if (!ProductForm || ProductForm.prototype.customerOrderLimitCopyEnhanced) return;

    const prototype = ProductForm.prototype;
    const originalShowQuantityLimit = prototype.showQuantityLimit;
    const originalOpenBuyNowLimitModal = prototype.openBuyNowLimitModal;

    if (typeof originalShowQuantityLimit === 'function') {
      prototype.showQuantityLimit = function showCustomerOrderLimitCopy(message, state) {
        return originalShowQuantityLimit.call(
          this,
          correctedCopy(this) || message,
          state
        );
      };
    }

    if (typeof originalOpenBuyNowLimitModal === 'function') {
      prototype.openBuyNowLimitModal = function openCustomerOrderLimitCopy(message) {
        return originalOpenBuyNowLimitModal.call(
          this,
          correctedCopy(this) || message
        );
      };
    }

    Object.defineProperty(prototype, 'customerOrderLimitCopyEnhanced', {
      value: true,
    });
  };

  if (customElements.get('product-form')) {
    enhanceProductForm();
  } else {
    customElements.whenDefined('product-form').then(enhanceProductForm);
  }
})();
