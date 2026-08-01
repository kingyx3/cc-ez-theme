if (!customElements.get('product-form')) {
  customElements.define('product-form', class ProductForm extends HTMLElement {
    constructor() {
      super();

      this.form = this.querySelector('form');
      this.cartNotification = document.querySelector('cart-notification');

      if (!this.form) return;

      this.form.addEventListener('submit', this.onSubmitHandler.bind(this));
      this.addEventListener('click', this.onBuyNowClick.bind(this), true);
    }

    isBuyNowAction(action) {
      if (!action) return false;

      const actionName = (action.getAttribute('name') || '').toLowerCase();
      const href = action.getAttribute('href') || '';
      const formAction = action.getAttribute('formaction') || '';

      return actionName === 'buy_now'
        || actionName === 'checkout'
        || action.matches('[data-buy-now], .product-form__buy-now')
        || href.includes('/checkout')
        || formAction.includes('/checkout');
    }

    onBuyNowClick(evt) {
      if (!evt.target || typeof evt.target.closest !== 'function') return;

      const buyNowButton = evt.target.closest(
        '[name="buy_now"], [name="checkout"], [data-buy-now], .product-form__buy-now, a[href*="/checkout"], [formaction*="/checkout"]'
      );

      if (!buyNowButton || !this.contains(buyNowButton)) return;

      evt.preventDefault();
      evt.stopPropagation();
      this.submitProduct(buyNowButton, true);
    }

    onSubmitHandler(evt) {
      evt.preventDefault();

      const submitButton = evt.submitter
        || this.querySelector('[name="add"]')
        || this.querySelector('[type="submit"]');

      this.submitProduct(submitButton, this.isBuyNowAction(submitButton));
    }

    submitProduct(submitButton, buyNow) {
      if (!submitButton || submitButton.matches('[disabled], [aria-disabled="true"]')) return;

      const addButton = this.querySelector('[name="add"]');
      if (buyNow && addButton && addButton.matches('[disabled], [aria-disabled="true"]')) return;

      if (!buyNow && this.cartNotification) {
        this.cartNotification.setActiveElement(document.activeElement);
      }

      const purchaseButtons = this.querySelectorAll(
        '.product-form__buttons [name="add"], .product-form__buttons [name="buy_now"], .product-form__buttons [name="checkout"], .product-form__buttons [data-buy-now], .product-form__buttons .product-form__buy-now, .product-form__buttons a[href*="/checkout"], .product-form__buttons [formaction*="/checkout"]'
      );

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
          submitButton.setAttribute('disabled', true);
          submitButton.setAttribute('aria-disabled', 'true');
          submitButton.classList.add('loading');
        } else {
          submitButton.removeAttribute('disabled');
          submitButton.removeAttribute('aria-disabled');
          submitButton.classList.remove('loading');
        }
      };

      setSubmitting(true);

      let updateCartItem = false;
      if (submitButton.dataset.updateCart && submitButton.dataset.cartItemId) {
        updateCartItem = true;
      }

      const body = JSON.parse(serializeForm(this.form));

      EasyStore.Action.addToCart(body, (cart) => {
        cart = cart || {};
        this.hideErrorMsg();

        if (cart.description != undefined) {
          this.renderErrorMsg(cart.description);
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

    renderErrorMsg(html) {
      this.form.querySelector('.form__message').classList.remove('hidden');
      this.form.querySelector('.js-error-content').innerHTML = html;
    }

    hideErrorMsg() {
      this.form.querySelector('.form__message').classList.add('hidden');
    }
  });
}
