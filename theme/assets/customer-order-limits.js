(() => {
  'use strict';

  const source = window.customerOrderLimitsV2;
  if (!source || !source.rules || Object.keys(source.rules).length === 0) return;

  const quantity = (value, fallback = 0) => {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
  };

  const normalizeHandle = (value) => {
    try {
      return decodeURIComponent(String(value || '')).trim().toLowerCase();
    } catch (_error) {
      return String(value || '').trim().toLowerCase();
    }
  };

  const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

  const rules = {};
  Object.entries(source.rules).forEach(([handle, rule]) => {
    const normalized = normalizeHandle(handle);
    if (normalized) rules[normalized] = rule;
  });
  source.rules = rules;

  const productHandleFromUrl = (value) => {
    const match = String(value || '').match(/\/products\/([^/?#]+)/i);
    return match ? normalizeHandle(match[1]) : '';
  };

  const productHandle = (element) => {
    if (!element) return '';
    const owner = element.closest('[data-product-handle]');
    if (owner && owner.dataset.productHandle) {
      return normalizeHandle(owner.dataset.productHandle);
    }

    const link = element.querySelector?.('a[href*="/products/"]')
      || element.parentElement?.querySelector?.('a[href*="/products/"]');
    const linkedHandle = productHandleFromUrl(link?.getAttribute('href'));
    if (linkedHandle) return linkedHandle;

    return productHandleFromUrl(window.location.pathname);
  };

  const ruleFor = (handle) => rules[normalizeHandle(handle)] || null;

  const customerAuthenticated = source.customerAuthenticated === true;

  // `body.customer-logged-in` comes from the layout and the markers come from
  // the header, both rendered by the same `customer` check the rest of the theme
  // uses for its account links, so together they are the reliable signal for
  // sign-in state. The Liquid flag above reports only what the limit snippet
  // itself could see, so it counts as a signed-in hint and never as proof that a
  // shopper is signed out. Signing out is only ever concluded from the header's
  // signed-out marker, never from missing markup.
  const SIGNED_IN_MARKUP = 'body.customer-logged-in, [data-customer-authenticated="true"], a[href^="/account/logout"]';
  const SIGNED_OUT_MARKUP = '[data-customer-authenticated="false"]';

  const onAccountPage = () => (
    /^\/account(\/|$)/.test(String(window.location.pathname || ''))
  );

  // Cached once the page proves sign-in state either way. While the state is
  // unproven the answer stays "not signed out" so no purchase is ever
  // redirected on a guess: a wrong redirect breaks buying for real customers.
  let signedOut = null;
  const shopperSignedOut = () => {
    if (signedOut !== null) return signedOut;
    if (customerAuthenticated || onAccountPage()) {
      signedOut = false;
      return signedOut;
    }
    if (document.querySelector(SIGNED_IN_MARKUP)) {
      signedOut = false;
      return signedOut;
    }
    if (!document.querySelector(SIGNED_OUT_MARKUP)) return false;
    signedOut = true;
    return signedOut;
  };

  // Limits count units per customer across orders, so they only exist for a
  // signed-in customer. A shopper proven to be signed out is sent to sign in
  // instead of being measured against a limit they cannot own yet.
  const loginRequiredForRule = (rule) => Boolean(rule) && shopperSignedOut();

  const loginRequiredForHandle = (handle) => loginRequiredForRule(ruleFor(handle));

  const loginRedirectUrl = () => {
    const target = `${window.location.pathname}${window.location.search}`;
    return `/account/login?redirect_uri=${encodeURIComponent(target)}`;
  };

  const redirectToLogin = () => {
    if (!shopperSignedOut()) return false;
    window.location.assign(loginRedirectUrl());
    return true;
  };

  const currentCartTotals = () => {
    const totals = {};
    Object.entries(rules).forEach(([handle, rule]) => {
      totals[handle] = quantity(rule.cartQuantity, 0);
    });
    return totals;
  };

  const cartTotalsFromForm = (form) => {
    const totals = {};
    if (!form) return totals;

    form.querySelectorAll('tr.cart-item').forEach((row) => {
      const input = row.querySelector('[name="updates[]"]');
      const handleInput = row.querySelector('[name="product_handles[]"]');
      const handle = normalizeHandle(
        handleInput?.value || row.dataset.productHandle || productHandle(row)
      );
      if (!handle || !input) return;
      totals[handle] = (totals[handle] || 0) + quantity(input.value, 0);
    });

    return totals;
  };

  const allowedCartQuantity = (rule) => quantity(rule && rule.allowedCartQuantity, 0);

  const loginRequiredForCart = (totals = null) => (
    Object.entries(rules).some(([handle, rule]) => {
      if (!loginRequiredForRule(rule)) return false;
      const cartQuantity = totals && hasOwn(totals, handle)
        ? quantity(totals[handle], 0)
        : quantity(rule.cartQuantity, 0);
      return cartQuantity > 0;
    })
  );

  // Returns null when no limit applies to this handle, either because the
  // product is unlimited or because the shopper has to sign in first.
  const remainingForHandle = (handle, totals = null) => {
    const normalized = normalizeHandle(handle);
    const rule = ruleFor(normalized);
    if (!rule || loginRequiredForRule(rule)) return null;
    const cartQuantity = totals && hasOwn(totals, normalized)
      ? quantity(totals[normalized], 0)
      : quantity(rule.cartQuantity, 0);
    return Math.max(0, allowedCartQuantity(rule) - cartQuantity);
  };

  const messageFor = (rule, requestedQuantity, remaining) => {
    if (remaining <= 0) {
      return String(rule.message || 'Customer purchase limit reached.');
    }
    if (requestedQuantity > remaining) {
      return `Customer purchase limit exceeded. You can add up to ${remaining} more.`;
    }
    return String(rule.message || `You can add up to ${remaining} more.`);
  };

  const additionViolation = (handle, requestedQuantity) => {
    const normalized = normalizeHandle(handle);
    const rule = ruleFor(normalized);
    if (!rule || loginRequiredForRule(rule)) return null;
    const requested = Math.max(1, quantity(requestedQuantity, 1));
    const remaining = remainingForHandle(normalized);
    if (requested <= remaining) return null;
    return {
      handle: normalized,
      requestedQuantity: requested,
      remaining,
      rule,
      message: messageFor(rule, requested, remaining),
    };
  };

  const quantityLimitForHandle = (handle) => {
    const normalized = normalizeHandle(handle);
    const rule = ruleFor(normalized);
    if (!rule || loginRequiredForRule(rule)) return null;
    const remaining = remainingForHandle(normalized);
    return {
      maximum: remaining,
      reason: 'a customer purchase limit across orders',
      message: messageFor(rule, Math.max(1, remaining + 1), remaining),
    };
  };

  const cartViolation = (totals = null, options = {}) => {
    const proposedTotals = totals || currentCartTotals();
    const currentTotals = currentCartTotals();
    const allowDecreases = options.allowDecreases === true;

    for (const [handle, rule] of Object.entries(rules)) {
      if (loginRequiredForRule(rule)) continue;
      const proposed = quantity(proposedTotals[handle], 0);
      const current = quantity(currentTotals[handle], 0);
      const allowed = allowedCartQuantity(rule);
      if (proposed <= allowed) continue;
      if (allowDecreases && proposed < current) continue;
      return {
        handle,
        proposedQuantity: proposed,
        currentQuantity: current,
        allowedQuantity: allowed,
        rule,
        message: String(
          rule.message
          || `Customer purchase limit exceeded. Reduce this product to ${allowed} before checkout.`
        ),
      };
    }

    return null;
  };

  const cartViolationFromForm = (form, options = {}) => (
    cartViolation(cartTotalsFromForm(form), options)
  );

  const loginRequiredForCartForm = (form) => (
    form ? loginRequiredForCart(cartTotalsFromForm(form)) : loginRequiredForCart()
  );

  const commitCartTotals = (totals) => {
    Object.entries(rules).forEach(([handle, rule]) => {
      const cartQuantity = quantity(totals && totals[handle], 0);
      const allowed = allowedCartQuantity(rule);
      rule.cartQuantity = cartQuantity;
      rule.remaining = Math.max(0, allowed - cartQuantity);
      rule.cartExceeded = cartQuantity > allowed;
    });
  };

  const syncCartFromForm = (form) => {
    const totals = cartTotalsFromForm(form);
    commitCartTotals(totals);
    decorateCartForm(form);
    document.dispatchEvent(new CustomEvent('customer-order-limits:cart-sync'));
    return totals;
  };

  const recordAddition = (handle, addedQuantity) => {
    const normalized = normalizeHandle(handle);
    const rule = ruleFor(normalized);
    if (!rule) return;
    const totals = currentCartTotals();
    totals[normalized] = quantity(totals[normalized], 0)
      + Math.max(1, quantity(addedQuantity, 1));
    commitCartTotals(totals);
    document.dispatchEvent(new CustomEvent('customer-order-limits:cart-sync'));
  };

  const recordRemoval = (handle, removedQuantity) => {
    const normalized = normalizeHandle(handle);
    const rule = ruleFor(normalized);
    if (!rule) return;
    const totals = currentCartTotals();
    totals[normalized] = Math.max(
      0,
      quantity(totals[normalized], 0) - quantity(removedQuantity, 0)
    );
    commitCartTotals(totals);
    document.dispatchEvent(new CustomEvent('customer-order-limits:cart-sync'));
  };

  const ensureAlert = () => {
    let alert = document.querySelector('[data-customer-order-limit-alert]');
    if (alert) return alert;
    alert = document.createElement('div');
    alert.hidden = true;
    alert.className = 'product-listing-cart-alert';
    alert.setAttribute('role', 'alert');
    alert.setAttribute('aria-live', 'assertive');
    alert.setAttribute('data-customer-order-limit-alert', '');
    document.body.appendChild(alert);
    return alert;
  };

  const showListingError = (message) => {
    const alert = ensureAlert();
    alert.textContent = String(message || 'Customer purchase limit exceeded.');
    alert.hidden = false;
    window.clearTimeout(alert.hideTimer);
    alert.hideTimer = window.setTimeout(() => { alert.hidden = true; }, 7000);
  };

  const showProductError = (context, message) => {
    const productForm = context?.closest?.('product-form');
    const formMessage = productForm?.querySelector('.form__message');
    const formContent = formMessage?.querySelector('.js-error-content');
    if (!formMessage || !formContent) {
      showListingError(message);
      return;
    }
    formContent.textContent = String(message || 'Customer purchase limit exceeded.');
    formMessage.classList.remove('hidden');
    formMessage.focus?.();
  };

  const showCartError = (message) => {
    const cartItems = document.querySelector('cart-items');
    if (cartItems && typeof cartItems.renderErrorMsg === 'function') {
      cartItems.renderErrorMsg(String(message || 'Reduce limited-item quantities before checkout.'));
      return;
    }
    const wrapper = document.querySelector('.cart_form__error');
    const content = wrapper?.querySelector('.js-error-content');
    if (wrapper && content) {
      content.textContent = String(message || 'Reduce limited-item quantities before checkout.');
      wrapper.classList.remove('hidden');
      window.scrollTo(0, 0);
      return;
    }
    showListingError(message);
  };

  function decorateCartForm(form) {
    if (!form) return;
    const totals = cartTotalsFromForm(form);

    form.querySelectorAll('tr.cart-item').forEach((row) => {
      const input = row.querySelector('[name="updates[]"]');
      const handleInput = row.querySelector('[name="product_handles[]"]');
      const handle = normalizeHandle(
        handleInput?.value || row.dataset.productHandle || productHandle(row)
      );
      const rule = ruleFor(handle);
      if (!input || !rule || loginRequiredForRule(rule)) return;

      const currentLine = quantity(input.value, 0);
      const currentTotal = quantity(totals[handle], 0);
      const maximum = currentLine + Math.max(
        0,
        allowedCartQuantity(rule) - currentTotal
      );
      row.dataset.productHandle = handle;
      input.dataset.customerOrderLimitEnabled = 'true';
      input.dataset.customerOrderLimitMaximum = String(maximum);
      input.dataset.customerOrderLimitMessage = String(rule.message || '');
      input.max = String(maximum);
    });

    const violation = cartViolation(totals);
    form.dataset.customerOrderLimitCheckoutBlocked = violation ? 'true' : 'false';

    form.querySelectorAll('#checkout, [name="checkout"], [name="expresscheckout"]').forEach((control) => {
      if (violation) {
        if (!control.dataset.customerOrderLimitDisabled) {
          control.dataset.customerOrderLimitWasDisabled = control.disabled ? 'true' : 'false';
        }
        control.dataset.customerOrderLimitDisabled = 'true';
        control.disabled = true;
        control.setAttribute('aria-disabled', 'true');
      } else if (control.dataset.customerOrderLimitDisabled === 'true') {
        if (control.dataset.customerOrderLimitWasDisabled !== 'true') control.disabled = false;
        control.removeAttribute('aria-disabled');
        delete control.dataset.customerOrderLimitDisabled;
        delete control.dataset.customerOrderLimitWasDisabled;
      }
    });

    form.querySelectorAll('.cart__ctas').forEach((container) => {
      if (container.querySelector('#checkout, [name="checkout"], [name="expresscheckout"]')) return;
      if (violation) {
        container.dataset.customerOrderLimitHidden = 'true';
        container.hidden = true;
      } else if (container.dataset.customerOrderLimitHidden === 'true') {
        container.hidden = false;
        delete container.dataset.customerOrderLimitHidden;
      }
    });
  }

  const formHandle = (form) => normalizeHandle(
    form?.dataset.productHandle || productHandle(form)
  );

  // Only takes over the event when the shopper is actually being redirected, so
  // an unproven sign-in state leaves the native purchase path untouched.
  const sendToLogin = (event) => {
    if (!shopperSignedOut()) return false;
    event.preventDefault();
    event.stopImmediatePropagation();
    return redirectToLogin();
  };

  document.addEventListener('click', (event) => {
    const listingButton = event.target.closest(
      'add-to-cart-button button[data-product-handle]'
    );
    if (listingButton) {
      if (
        loginRequiredForHandle(listingButton.dataset.productHandle)
        && sendToLogin(event)
      ) return;
      const violation = additionViolation(
        listingButton.dataset.productHandle,
        listingButton.dataset.quantity
      );
      if (violation) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showListingError(violation.message);
      }
      return;
    }

    const buyNowButton = event.target.closest('[data-buy-now]');
    if (buyNowButton) {
      const form = buyNowButton.closest('product-form')?.querySelector('form');
      const handle = formHandle(form);
      if (loginRequiredForHandle(handle) && sendToLogin(event)) return;
      const violation = additionViolation(
        handle,
        form?.querySelector('[name="quantity"]')?.value
      );
      if (violation) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showProductError(form, violation.message);
      }
      return;
    }

    const cartForm = event.target.closest('#cart-form');
    if (cartForm && event.target.closest('.cart__ctas')) {
      if (loginRequiredForCartForm(cartForm) && sendToLogin(event)) return;
      if (cartForm.dataset.customerOrderLimitCheckoutBlocked === 'true') {
        const violation = cartViolationFromForm(cartForm);
        if (violation) {
          event.preventDefault();
          event.stopImmediatePropagation();
          showCartError(violation.message);
        }
      }
    }
  }, true);

  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;

    if (form.matches('product-form form')) {
      const handle = formHandle(form);
      if (loginRequiredForHandle(handle) && sendToLogin(event)) return;
      const violation = additionViolation(
        handle,
        form.querySelector('[name="quantity"]')?.value
      );
      if (violation) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showProductError(form, violation.message);
      }
      return;
    }

    if (form.id === 'cart-form') {
      const submitter = event.submitter;
      const isCheckout = !submitter
        || submitter.name === 'checkout'
        || submitter.name === 'expresscheckout'
        || submitter.id === 'checkout';
      if (!isCheckout) return;
      if (loginRequiredForCartForm(form) && sendToLogin(event)) return;
      const violation = cartViolationFromForm(form);
      if (violation) {
        event.preventDefault();
        event.stopImmediatePropagation();
        showCartError(violation.message);
      }
    }
  }, true);

  window.CustomerOrderLimits = {
    customerAuthenticated,
    normalizeHandle,
    ruleFor,
    productHandle,
    loginRequiredForHandle,
    loginRequiredForCart,
    loginRequiredForCartForm,
    loginRedirectUrl,
    redirectToLogin,
    cartTotalsFromForm,
    remainingForHandle,
    quantityLimitForHandle,
    additionViolation,
    cartViolation,
    cartViolationFromForm,
    commitCartTotals,
    syncCartFromForm,
    recordAddition,
    recordRemoval,
    decorateCartForm,
    showListingError,
    showProductError,
    showCartError,
  };

  decorateCartForm(document.getElementById('cart-form'));
  document.dispatchEvent(new CustomEvent('customer-order-limits:ready'));
})();
