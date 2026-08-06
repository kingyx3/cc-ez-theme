const customerOrderLimitApi = () => window.CustomerOrderLimits;

function showCustomerOrderLimitCartError(message) {
  const api = customerOrderLimitApi();
  if (api) {
    api.showCartError(message);
    return;
  }
  const cartItems = document.querySelector('cart-items');
  if (cartItems && typeof cartItems.renderErrorMsg === 'function') {
    cartItems.renderErrorMsg(message);
  }
}

document.addEventListener('submit', (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || form.id !== 'cart-form') return;
  const submitter = event.submitter;
  const isCheckout = !submitter
    || submitter.name === 'checkout'
    || submitter.name === 'expresscheckout'
    || submitter.id === 'checkout';
  if (!isCheckout) return;

  const api = customerOrderLimitApi();
  if (!api) return;

  if (api.loginRequiredForCartForm(form) && api.redirectToLogin()) {
    event.preventDefault();
    event.stopImmediatePropagation();
    return;
  }

  const violation = api.cartViolationFromForm(form);
  if (!violation) return;

  event.preventDefault();
  event.stopImmediatePropagation();
  showCustomerOrderLimitCartError(violation.message);
}, true);

document.getElementById('cart-form')?.addEventListener('submit', (event) => {
  if (event.submitter) event.submitter.classList.add('loading');
});

document.body.addEventListener('click', (event) => {
  const trigger = event.target.closest('.product-bundle__toggle');
  if (trigger) {
    const targetId = trigger.getAttribute('data-target');
    const target = document.getElementById(targetId);
    if (target) {
      const isOpening = window.getComputedStyle(target).display === 'none';
      slideToggle(target, 300, trigger);
      trigger.setAttribute('aria-expanded', String(isOpening));
    }
  }
});

class CartRemoveButton extends HTMLElement {
  constructor() {
    super();
    this.addEventListener('click', (event) => {
      event.preventDefault();
      this.closest('.cart-item__quantity').querySelector('.quantity__input').value = 0;
      this.closest('cart-items').removeCartItem(this.dataset.index);
    });
  }
}

customElements.define('cart-remove-button', CartRemoveButton);

class CartEditButton extends HTMLElement {
  constructor() {
    super();
    if (document.querySelector('product-quickview-modal')) this.classList.remove('hide');
    this.button = this.querySelector('[data-product-handle]');
    this.addEventListener('click', () => {
      document.querySelector('product-quickview-modal').open(this.button, true);
    });
  }

  removeCartItem() {
    this.closest('.cart-item__quantity').querySelector('.quantity__input').value = 0;
    this.closest('cart-items').removeCartItem(this.dataset.index, false);
  }
}

customElements.define('cart-edit-button', CartEditButton);

class DiscountInput extends HTMLElement {
  constructor() {
    super();
    this.input = this.querySelector('input');
    this.button = this.querySelector('button');

    this.button.addEventListener('click', this.onButtonClick.bind(this));
    this.input.addEventListener('keypress', (event) => {
      if (event.key === 'Enter' || event.keyCode === 13) {
        event.preventDefault();
        this.onButtonClick(event);
      }
      this.hideErrorMsg();
    });
  }

  onButtonClick(event) {
    event.preventDefault();
    this.hideErrorMsg();

    if (this.input.value !== '') {
      this.button.classList.add('loading');
      EasyStore.Action.updateVoucher('create', this.input.value, (cart) => {
        this.button.classList.remove('loading');
        if (cart.error && cart.error.message) {
          this.renderErrorMsg(cart.error.message);
        } else if (document.querySelector('vouchers-modal')) {
          document.querySelector('vouchers-modal').close();
        }
        if (cart.cart_content) {
          document.querySelector('#cart-template').innerHTML = cart.cart_content;
          customerOrderLimitApi()?.syncCartFromForm(document.getElementById('cart-form'));
        }
      });
    }
  }

  renderErrorMsg(html) {
    const formMessage = this.querySelector('.form__message');
    const errorContent = this.querySelector('.js-error-content');

    if (
      typeof html === 'string'
      && /log in/i.test(html)
      && !/voucher-error__login/.test(html)
    ) {
      const loginUrl = `/account/login?redirect_uri=${encodeURIComponent(window.location.pathname + window.location.search)}`;
      html = html.replace(/log in/i, `<a href="${loginUrl}" class="voucher-error__login">$&</a>`);
    }

    formMessage.classList.remove('hidden');
    errorContent.innerHTML = html;
  }

  hideErrorMsg() {
    this.querySelector('.form__message').classList.add('hidden');
  }
}
customElements.define('discount-input', DiscountInput);

class DiscountRemoveButton extends HTMLElement {
  constructor() {
    super();
    this.button = this.querySelector('button');
    this.button.addEventListener('click', this.onButtonClick.bind(this));
  }

  onButtonClick(event) {
    event.preventDefault();
    this.enableLoading();
    EasyStore.Action.updateVoucher('remove', this.button.dataset.discount_id, (cart) => {
      if (cart.cart_content) {
        document.querySelector('#cart-template').innerHTML = cart.cart_content;
        customerOrderLimitApi()?.syncCartFromForm(document.getElementById('cart-form'));
      }
    });
  }

  enableLoading() {
    this.closest('.totals').classList.add('cart__items--disabled');
    this.closest('.totals').querySelector('.loading-overlay').classList.remove('hidden');
    document.activeElement.blur();
  }

  disableLoading() {
    this.closest('.totals').classList.remove('cart__items--disabled');
    this.closest('.totals').querySelector('.loading-overlay').classList.add('hidden');
  }
}
customElements.define('discount-remove-button', DiscountRemoveButton);

class CartItems extends HTMLElement {
  constructor() {
    super();

    this.cartNotification = document.querySelector('cart-notification');

    this.currentItemCount = Array.from(this.querySelectorAll('[name="updates[]"]'))
      .reduce((total, quantityInput) => total + parseInt(quantityInput.value, 10), 0);

    this.debouncedOnChange = debounce((event) => {
      this.onChange(event);
    }, 300);

    this.addEventListener('change', this.debouncedOnChange.bind(this));
    this.addEventListener('focusin', (event) => {
      const input = event.target.closest('[name="updates[]"]');
      if (input) input.dataset.customerOrderPreviousValue = input.value;
    });

    this.customerOrderLimitsChanged = () => {
      customerOrderLimitApi()?.decorateCartForm(document.getElementById('cart-form'));
    };
    document.addEventListener(
      'customer-order-limits:ready',
      this.customerOrderLimitsChanged
    );
    document.addEventListener(
      'customer-order-limits:cart-sync',
      this.customerOrderLimitsChanged
    );

    this.querySelectorAll('[name="updates[]"]').forEach((input) => {
      input.dataset.customerOrderPreviousValue = input.value;
    });
    this.customerOrderLimitsChanged();
  }

  onChange(event) {
    const input = event.target;
    const form = document.getElementById('cart-form');
    const api = customerOrderLimitApi();
    const violation = api
      ? api.cartViolationFromForm(form, { allowDecreases: true })
      : null;
    if (violation) {
      input.value = input.dataset.customerOrderPreviousValue || input.value;
      showCustomerOrderLimitCartError(violation.message);
      api.decorateCartForm(form);
      return;
    }

    this.updateQuantity(
      input.dataset.index,
      input.value,
      document.activeElement?.getAttribute('name')
    );
  }

  updateQuantity(line, quantity, name) {
    const form = document.getElementById('cart-form');
    const api = customerOrderLimitApi();
    const changedInput = this.querySelector(
      `[name="updates[]"][data-index="${line}"]`
    );
    const violation = api
      ? api.cartViolationFromForm(form, { allowDecreases: true })
      : null;
    if (violation) {
      if (changedInput) {
        changedInput.value = changedInput.dataset.customerOrderPreviousValue
          || changedInput.value;
      }
      showCustomerOrderLimitCartError(violation.message);
      api.decorateCartForm(form);
      return;
    }
    const proposedTotals = api ? api.cartTotalsFromForm(form) : null;

    this.enableLoading(line);
    this.hideErrorMsg();

    const body = JSON.parse(serializeForm(form));

    EasyStore.Action.updateCart(body, (cart) => {
      cart = cart || {};
      const hasError = Boolean(cart.error && cart.error.message);

      this.classList.toggle('is-empty', cart.item_count === 0);
      const cartFooter = document.getElementById('main-cart-footer');
      if (cartFooter) cartFooter.classList.toggle('is-empty', cart.item_count === 0);

      this.disableLoading();
      if (hasError) {
        this.renderErrorMsg(cart.error.message);
        this.disableLoading(line);
      }
      if (cart.cart_content) {
        document.querySelector('#cart-template').innerHTML = cart.cart_content;
        api?.syncCartFromForm(document.getElementById('cart-form'));
      } else if (!hasError && proposedTotals) {
        api?.commitCartTotals(proposedTotals);
        document.dispatchEvent(new CustomEvent('customer-order-limits:cart-sync'));
        if (changedInput) changedInput.dataset.customerOrderPreviousValue = changedInput.value;
      }

      if (
        this.cartNotification !== undefined
        && this.cartNotification.updateCartCount !== undefined
      ) this.cartNotification.updateCartCount(cart);
      if (
        window.EasyStore !== undefined
        && window.EasyStore.Promotion !== undefined
        && window.EasyStore.Promotion.updateCartPromotion !== undefined
      ) window.EasyStore.Promotion.updateCartPromotion();

      if (window.checkProductProperties !== undefined) {
        window.checkProductProperties();
      }
    });
  }

  removeCartItem(line, isCheckProductProperties = true) {
    const cartItem = this.querySelector(`#CartItem-${line}`);
    if (!cartItem) return;
    const cartItemDeleteBtn = cartItem.querySelector('cart-remove-button [data-item-id]');
    if (!cartItemDeleteBtn) return;

    const removedHandle = cartItem.querySelector('[name="product_handles[]"]')?.value
      || cartItem.dataset.productHandle;
    const removedQuantity = Number.parseInt(
      cartItem.querySelector('[name="updates[]"]')?.value,
      10
    ) || 0;

    this.enableLoading(line);
    this.hideErrorMsg();
    const body = {
      variant_id: cartItemDeleteBtn.dataset.variantId,
      item_id: cartItemDeleteBtn.dataset.itemId,
    };

    EasyStore.Action.removeCartItem(body, (cart) => {
      cart = cart || {};
      const hasError = Boolean(cart.error && cart.error.message);

      this.classList.toggle('is-empty', cart.item_count === 0);
      const cartFooter = document.getElementById('main-cart-footer');
      if (cartFooter) cartFooter.classList.toggle('is-empty', cart.item_count === 0);

      this.disableLoading();
      if (hasError) {
        this.renderErrorMsg(cart.error.message);
        this.disableLoading(line);
      }
      if (cart.cart_content) {
        document.querySelector('#cart-template').innerHTML = cart.cart_content;
        customerOrderLimitApi()?.syncCartFromForm(document.getElementById('cart-form'));
      } else if (!hasError) {
        customerOrderLimitApi()?.recordRemoval(removedHandle, removedQuantity);
      }

      if (
        this.cartNotification !== undefined
        && this.cartNotification.updateCartCount !== undefined
      ) this.cartNotification.updateCartCount(cart);
      if (
        window.EasyStore !== undefined
        && window.EasyStore.Promotion !== undefined
        && window.EasyStore.Promotion.updateCartPromotion !== undefined
      ) window.EasyStore.Promotion.updateCartPromotion();

      if (window.checkProductProperties !== undefined && isCheckProductProperties) {
        window.checkProductProperties();
      }
      if (
        document.querySelector('product-quickview-modal')
        && document.querySelector('product-quickview-modal').isOpen()
      ) document.querySelector('product-quickview-modal').close(true);
    });
  }

  renderErrorMsg(html) {
    this.querySelector('.cart_form__error').classList.remove('hidden');
    this.querySelector('.cart_form__error .js-error-content').innerHTML = html;
    window.scrollTo(0, 0);
  }

  hideErrorMsg() {
    this.querySelector('.cart_form__error').classList.add('hidden');
  }

  enableLoading(line) {
    document.getElementById('main-cart-items').classList.add('cart__items--disabled');
    this.querySelectorAll(`#CartItem-${line} .loading-overlay`)
      .forEach((overlay) => overlay.classList.remove('hidden'));
    document.activeElement.blur();
  }

  disableLoading() {
    document.getElementById('main-cart-items').classList.remove('cart__items--disabled');
    this.querySelectorAll('.loading-overlay')
      .forEach((overlay) => overlay.classList.add('hidden'));
  }
}

customElements.define('cart-items', CartItems);
