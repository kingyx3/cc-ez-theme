if (!customElements.get('product-form')) {
  customElements.define('product-form', class ProductForm extends HTMLElement {
    constructor() {
      super();

      this.form = this.querySelector('form');
      this.buyNowButton = this.querySelector('[data-buy-now]');
      this.buyNowLimitModal = this.querySelector('[data-checkout-limit-modal]');
      this.buyNowLimitMessage = this.querySelector('[data-checkout-limit-message]');
      this.cartNotification = document.querySelector('cart-notification');

      if (!this.form) return;

      this.form.addEventListener('submit', this.onSubmitHandler.bind(this));
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
            window.location.assign('/checkout');
          });
        }

        this.buyNowLimitModal.addEventListener(
          'click',
          this.onBuyNowLimitModalClick.bind(this)
        );
      }
    }

    onBuyNowClick(evt) {
      evt.preventDefault();
      this.submitProduct(this.buyNowButton, true);
    }

    onSubmitHandler(evt) {
      evt.preventDefault();

      const submitButton = evt.submitter
        || this.querySelector('[name="add"]')
        || this.querySelector('[type="submit"]');

      this.submitProduct(submitButton, false);
    }

    submitProduct(submitButton, buyNow) {
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
            button.setAttribute('disabled', true);
            button.setAttribute('aria-disabled', 'true');
          } else {
            button.removeAttribute('disabled');
            button.removeAttribute('aria-disabled');
          }
        });

        if (submitting) {
          submitButton.classList.add('loading');
        } else {
          submitButton.classList.remove('loading');
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
            'This item could not be added because it may exceed a customer, store, or stock limit.'
          );
          setSubmitting(false);
          return;
        }

        if (buyNow) {
          window.location.assign('/checkout');
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
