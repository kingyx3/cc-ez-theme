(() => {
  const alertDuration = 7000;

  function getAlert() {
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

    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'product-listing-cart-alert__close';
    closeButton.setAttribute('aria-label', 'Dismiss message');
    closeButton.textContent = '×';
    closeButton.addEventListener('click', () => {
      alert.hidden = true;
    });

    alert.append(message, closeButton);
    document.body.appendChild(alert);
    return alert;
  }

  function showError(rawMessage, context = {}) {
    const alert = getAlert();
    const messageElement = alert.querySelector(
      '[data-product-listing-cart-alert-message]'
    );
    const feedback = window.PurchaseLimitFeedback;

    messageElement.textContent = feedback
      ? feedback.format({ ...context, rawMessage, mode: 'error' })
      : String(rawMessage || '').replace(/<[^>]*>/g, '').trim();
    alert.hidden = false;

    window.clearTimeout(alert.hideTimer);
    alert.hideTimer = window.setTimeout(() => {
      alert.hidden = true;
    }, alertDuration);
  }

  function fallbackError() {
    return window.purchaseStrings && window.purchaseStrings.addLimitError
      ? window.purchaseStrings.addLimitError
      : 'This item could not be added because the available quantity or purchase limit was reached.';
  }

  function enhanceListingCartButton() {
    const AddToCartButton = customElements.get('add-to-cart-button');
    if (!AddToCartButton || AddToCartButton.prototype.listingCartFeedbackEnhanced) {
      return;
    }

    Object.defineProperty(
      AddToCartButton.prototype,
      'listingCartFeedbackEnhanced',
      { value: true }
    );

    AddToCartButton.prototype.addToCart = function addToCartWithFeedback() {
      if (!this.cartNotification) {
        window.location.href = `/products/${this.button.dataset.productHandle}`;
        return;
      }

      this.cartNotification.setActiveElement(document.activeElement);
      this.button.classList.add('transparent');

      const requestedQuantity = Math.max(
        1,
        Number.parseInt(this.button.dataset.quantity, 10) || 1
      );
      const variantId = this.button.dataset.variantId;
      const feedback = window.PurchaseLimitFeedback;
      const currentQuantity = feedback
        ? feedback.getCartQuantity(variantId)
        : 0;
      const errorContext = {
        currentQuantity,
        requestedQuantity,
      };
      const cartCount = document.querySelector('.js-content-cart-count');
      const parsedItemCount = Number.parseInt(
        cartCount ? cartCount.textContent : '0',
        10
      );
      const previousItemCount = Number.isFinite(parsedItemCount)
        ? parsedItemCount
        : 0;

      const body = {
        _token: this.button.dataset.token,
        id: variantId,
        quantity: requestedQuantity,
      };

      EasyStore.Action.addToCart(body, (cart) => {
        cart = cart || {};

        if (cart.description != null && cart.description !== '') {
          showError(cart.description, errorContext);
          this.setLoading(false);
          return;
        }

        const itemCount = Number(cart.item_count);
        const latestItems = Array.isArray(cart.latest_items)
          ? cart.latest_items
          : [];
        const minimumItemCount = previousItemCount + requestedQuantity;
        const cartConfirmed = Number.isFinite(itemCount)
          && itemCount >= minimumItemCount
          && latestItems.length > 0;

        if (!cartConfirmed) {
          showError(fallbackError(), errorContext);
          this.setLoading(false);
          return;
        }

        if (window.location.pathname === '/cart') {
          window.location.reload();
        } else {
          this.cartNotification.renderContents(cart);
          this.setLoading(false);
        }
      });
    };
  }

  if (customElements.get('add-to-cart-button')) {
    enhanceListingCartButton();
  } else {
    customElements.whenDefined('add-to-cart-button').then(enhanceListingCartButton);
  }
})();
