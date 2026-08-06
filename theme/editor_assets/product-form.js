if (!customElements.get('product-form')) {
  customElements.define('product-form', class ProductForm extends HTMLElement {
    constructor() {
      super();

      this.form = this.querySelector('form');
      this.buyNowButton = this.querySelector('[data-buy-now]');
      this.checkoutForm = this.querySelector('[data-buy-now-checkout-form]');
      this.buyNowLimitModal = this.querySelector('[data-checkout-limit-modal]');
      this.buyNowLimitMessage = this.querySelector('[data-checkout-limit-message]');
      this.cartNotification = document.querySelector('cart-notification');

      if (!this.form) return;

      this.quantityInput = this.form.querySelector('[name="quantity"]');
      this.quantityLimitMessage = this.querySelector('[data-quantity-limit-message]');
      this.nativeQuantityMaximum = this.quantityInput
        ? this.quantityInput.getAttribute('max')
        : null;
      this.currentVariant = null;
      this.rejectedQuantityLimit = null;

      this.form.addEventListener('submit', this.onSubmitHandler.bind(this));
      this.addEventListener('product:variant-change', this.onVariantChange.bind(this));
      if (this.quantityInput) {
        this.quantityInput.addEventListener('input', this.onQuantityChange.bind(this));
        this.quantityInput.addEventListener('change', this.onQuantityChange.bind(this));
      }
      if (this.buyNowButton) {
        this.buyNowButton.addEventListener('click', this.onBuyNowClick.bind(this));
      }

      if (this.buyNowLimitModal) {
        this.buyNowLimitModal
          .querySelectorAll('[data-checkout-limit-cancel]')
          .forEach((button) => {
            button.addEventListener('click', this.closeBuyNowLimitModal.bind(this));
          });

        const continueButton = this.buyNowLimitModal.querySelector(
          '[data-checkout-limit-continue]'
        );
        if (continueButton) {
          continueButton.addEventListener('click', () => {
            this.closeBuyNowLimitModal();
            this.goToCheckout();
          });
        }

        this.buyNowLimitModal.addEventListener(
          'click',
          this.onBuyNowLimitModalClick.bind(this)
        );
      }

      this.validateQuantity();
    }

    onVariantChange(evt) {
      this.currentVariant = evt.detail ? evt.detail.variant : null;
      this.rejectedQuantityLimit = null;
      this.validateQuantity();
    }

    onQuantityChange() {
      this.validateQuantity();
    }

    toPositiveLimit(value) {
      if (value == null || value === '' || typeof value === 'boolean') return null;
      const parsed = Number(value);
      return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : null;
    }

    getQuantityLimit() {
      if (!this.quantityInput) return null;

      const selectedOption = this.form.querySelector('[name="id"] option:checked');
      const variant = this.currentVariant || {};
      const inventory = this.toPositiveLimit(
        variant.inventory_quantity != null
          ? variant.inventory_quantity
          : selectedOption && selectedOption.dataset.inventoryQuantity
      );
      const candidates = [];

      if (inventory && variant.available !== false) {
        candidates.push({ maximum: inventory, reason: window.purchaseStrings.inventoryLimit });
      }

      const metadataLimits = [
        [window.purchaseStrings.purchaseLimit, variant.max_purchase_quantity],
        [window.purchaseStrings.purchaseLimit, variant.maximum_purchase_quantity],
        [window.purchaseStrings.purchaseLimit, variant.purchase_limit],
        [window.purchaseStrings.storeLimit, variant.store_purchase_limit],
        [window.purchaseStrings.customerLimit, variant.customer_purchase_limit],
        [window.purchaseStrings.promotionLimit, variant.promotion_purchase_limit],
        [window.purchaseStrings.promotionLimit, variant.promo_purchase_limit],
        [window.purchaseStrings.orderLimit, variant.max_order_quantity],
        [window.purchaseStrings.orderLimit, variant.order_limit],
        [window.purchaseStrings.quantityRule, variant.quantity_rule && variant.quantity_rule.max],
        [window.purchaseStrings.quantityRule, variant.quantity_limits && variant.quantity_limits.max],
        [window.purchaseStrings.quantityRule, variant.limits && variant.limits.max_quantity],
        [window.purchaseStrings.configuredLimit, this.quantityInput.dataset.maxQuantity],
        [window.purchaseStrings.configuredLimit, this.form.dataset.maxQuantity],
      ];

      metadataLimits.forEach(([reason, value]) => {
        const maximum = this.toPositiveLimit(value);
        if (maximum) candidates.push({ maximum, reason });
      });

      const nativeMaximum = this.toPositiveLimit(this.nativeQuantityMaximum);
      if (nativeMaximum) candidates.push({ maximum: nativeMaximum, reason: window.purchaseStrings.configuredLimit });

      const selectedVariant = this.form.querySelector('[name="id"]');
      const customerLimits = window.CustomerPurchaseLimits;
      if (
        customerLimits
        && typeof customerLimits.quantityLimitForVariant === 'function'
      ) {
        const customerLimit = customerLimits.quantityLimitForVariant(
          selectedVariant && selectedVariant.value
        );
        if (customerLimit) candidates.push(customerLimit);
      }

      if (this.rejectedQuantityLimit) {
        candidates.push(this.rejectedQuantityLimit);
      }

      if (!candidates.length) return null;
      return candidates.reduce((strictest, candidate) => (
        candidate.maximum < strictest.maximum ? candidate : strictest
      ));
    }

    setPurchaseButtonsLimited(limited) {
      this.querySelectorAll('[name="add"], [data-buy-now]').forEach((button) => {
        if (limited) {
          if (button.dataset.quantityLimitDisabled !== 'true') {
            button.dataset.quantityLimitWasDisabled = button.matches('[disabled], [aria-disabled="true"]')
              ? 'true'
              : 'false';
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
    }

    updatePlusButton(maximum, quantity) {
      if (!this.quantityInput) return;
      const plusButton = this.quantityInput
        .closest('quantity-input')
        ?.querySelector('[name="plus"]');
      if (!plusButton) return;

      if (maximum && quantity >= maximum) {
        plusButton.dataset.quantityLimitDisabled = 'true';
        plusButton.setAttribute('disabled', true);
        plusButton.setAttribute('aria-disabled', 'true');
      } else if (plusButton.dataset.quantityLimitDisabled === 'true') {
        plusButton.removeAttribute('disabled');
        plusButton.removeAttribute('aria-disabled');
        delete plusButton.dataset.quantityLimitDisabled;
      }
    }

    showQuantityLimit(message, state) {
      if (!this.quantityInput || !this.quantityLimitMessage) return;
      const wrapper = this.quantityInput.closest('.product-form__quantity');

      this.quantityLimitMessage.textContent = message;
      this.quantityLimitMessage.classList.remove('hidden', 'quantity-limit-message--warning', 'quantity-limit-message--error');
      this.quantityLimitMessage.classList.add(`quantity-limit-message--${state}`);
      this.quantityInput.setAttribute('aria-invalid', state === 'error' ? 'true' : 'false');
      if (wrapper) wrapper.classList.toggle('quantity-limit-exceeded', state === 'error');
    }

    clearQuantityLimit() {
      if (!this.quantityInput || !this.quantityLimitMessage) return;
      const wrapper = this.quantityInput.closest('.product-form__quantity');

      this.quantityLimitMessage.textContent = '';
      this.quantityLimitMessage.classList.add('hidden');
      this.quantityLimitMessage.classList.remove('quantity-limit-message--warning', 'quantity-limit-message--error');
      this.quantityInput.removeAttribute('aria-invalid');
      if (wrapper) wrapper.classList.remove('quantity-limit-exceeded');
    }

    validateQuantity(focusInvalid = false) {
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

      if (quantity > limit.maximum) {
        const message = limit.message
          || window.purchaseStrings.quantityExceeded
            .replace('__QUANTITY__', quantity)
            .replace('__MAXIMUM__', limit.maximum)
            .replace('__REASON__', limit.reason);
        this.showQuantityLimit(message, 'error');
        this.setPurchaseButtonsLimited(true);
        if (focusInvalid) this.quantityInput.focus();
        return false;
      }

      this.setPurchaseButtonsLimited(false);
      if (quantity === limit.maximum) {
        this.showQuantityLimit(
          window.purchaseStrings.quantityMaximum
            .replace('__MAXIMUM__', limit.maximum)
            .replace('__REASON__', limit.reason),
          'warning'
        );
      } else {
        this.clearQuantityLimit();
      }
      return true;
    }

    isQuantityLimitError(message) {
      return /(limit|maximum|max\\b|exceed|stock|inventory|available|promotion|promo|customer|purchase|order quantity)/i
        .test(String(message || ''));
    }

    rememberRejectedQuantity(variantId, quantity, message) {
      if (!this.isQuantityLimitError(message)) return;

      this.rejectedQuantityLimit = {
        maximum: Math.max(0, quantity - 1),
        reason: 'a store purchase rule',
        message: String(message),
        variantId: String(variantId || ''),
      };
      this.validateQuantity();
    }

    onBuyNowClick(evt) {
      evt.preventDefault();
      if (!this.validateQuantity(true)) return;
      this.submitProduct(this.buyNowButton, true);
    }

    onSubmitHandler(evt) {
      evt.preventDefault();
      if (!this.validateQuantity(true)) return;

      const submitButton = evt.submitter
        || this.querySelector('[name="add"]')
        || this.querySelector('[type="submit"]');

      this.submitProduct(submitButton, false);
    }

    submitProduct(submitButton, buyNow) {
      if (!this.validateQuantity(true)) return;
      if (!submitButton || submitButton.matches('[disabled], [aria-disabled="true"]')) return;

      const addButton = this.querySelector('[name="add"]');
      if (buyNow && addButton && addButton.matches('[disabled], [aria-disabled="true"]')) return;

      if (!buyNow && this.cartNotification) {
        this.cartNotification.setActiveElement(document.activeElement);
      }

      const purchaseButtons = this.querySelectorAll('[name="add"], [data-buy-now]');
      const cartCount = document.querySelector('.js-content-cart-count');
      const parsedItemCount = Number.parseInt(cartCount ? cartCount.textContent : '0', 10);
      const previousItemCount = Number.isFinite(parsedItemCount) ? parsedItemCount : 0;

      const setSubmitting = (submitting) => {
        purchaseButtons.forEach((button) => {
          if (submitting) {
            if (button.dataset.submissionWasDisabled == null) {
              button.dataset.submissionWasDisabled = button.matches('[disabled], [aria-disabled="true"]')
                ? 'true'
                : 'false';
            }
            button.setAttribute('disabled', true);
            button.setAttribute('aria-disabled', 'true');
          } else {
            const wasDisabled = button.dataset.submissionWasDisabled === 'true';
            const variantUnavailable = this.currentVariant && this.currentVariant.available === false;
            if (!wasDisabled && !variantUnavailable) {
              button.removeAttribute('disabled');
              button.removeAttribute('aria-disabled');
            }
            delete button.dataset.submissionWasDisabled;
          }
        });

        if (submitting) {
          submitButton.classList.add('loading');
        } else {
          submitButton.classList.remove('loading');
          this.validateQuantity();
        }
      };

      setSubmitting(true);

      let updateCartItem = false;
      if (submitButton.dataset.updateCart && submitButton.dataset.cartItemId) {
        updateCartItem = true;
      }

      const body = JSON.parse(serializeForm(this.form));
      const requestedQuantity = Math.max(1, Number.parseInt(body.quantity, 10) || 1);

      EasyStore.Action.addToCart(body, (cart) => {
        cart = cart || {};
        this.hideErrorMsg();

        if (cart.description != undefined) {
          this.rememberRejectedQuantity(body.id, requestedQuantity, cart.description);
          if (buyNow) {
            this.openBuyNowLimitModal(String(cart.description));
          } else {
            this.renderErrorMsg(cart.description);
          }
          setSubmitting(false);
          return;
        }

        const itemCount = Number(cart.item_count);
        const latestItems = Array.isArray(cart.latest_items) ? cart.latest_items : [];
        const minimumItemCount = previousItemCount + requestedQuantity;
        const cartConfirmed = Number.isFinite(itemCount)
          && itemCount >= minimumItemCount
          && latestItems.length > 0;

        if (buyNow && !cartConfirmed) {
          this.openBuyNowLimitModal(
            window.purchaseStrings.addLimitError
          );
          setSubmitting(false);
          return;
        }

        if (cartConfirmed) {
          const customerLimits = window.CustomerPurchaseLimits;
          if (
            customerLimits
            && typeof customerLimits.recordAdditionForVariant === 'function'
          ) {
            customerLimits.recordAdditionForVariant(
              body.id,
              requestedQuantity
            );
          }
        }

        if (buyNow) {
          this.goToCheckout();
          return;
        }

        if (!updateCartItem && cart.item_count != undefined && cart.latest_items != undefined && this.cartNotification) {
          this.cartNotification.renderContents(cart);
        }

        const cartItem = document.querySelector(`#${submitButton.dataset.cartItemId}`);
        if (updateCartItem && cartItem) {
          cartItem.removeCartItem();
        } else {
          setSubmitting(false);
        }
      });
    }

    goToCheckout() {
      if (!this.checkoutForm) {
        window.location.assign('/cart');
        return;
      }

      if (typeof this.checkoutForm.requestSubmit === 'function') {
        this.checkoutForm.requestSubmit();
      } else {
        this.checkoutForm.submit();
      }
    }

    openBuyNowLimitModal(message) {
      if (!this.buyNowLimitModal || !this.buyNowLimitMessage) {
        this.renderErrorMsg(message);
        return;
      }

      this.buyNowLimitMessage.textContent = message;

      if (typeof this.buyNowLimitModal.showModal === 'function') {
        if (!this.buyNowLimitModal.open) {
          this.buyNowLimitModal.showModal();
        }
      } else {
        this.buyNowLimitModal.setAttribute('open', '');
      }
    }

    closeBuyNowLimitModal() {
      if (!this.buyNowLimitModal) return;

      if (typeof this.buyNowLimitModal.close === 'function') {
        if (this.buyNowLimitModal.open) {
          this.buyNowLimitModal.close();
        }
      } else {
        this.buyNowLimitModal.removeAttribute('open');
      }
    }

    onBuyNowLimitModalClick(evt) {
      if (evt.target === this.buyNowLimitModal) {
        this.closeBuyNowLimitModal();
      }
    }

    renderErrorMsg(html) {
      this.form.querySelector('.form__message').classList.remove('hidden');
      this.form.querySelector('.js-error-content').innerHTML = html;
    }

    hideErrorMsg() {
      this.form.querySelector('.form__message').classList.add('hidden');
    }
  });
}
