(() => {
  'use strict';

  const PROXY_SELECTOR = 'input[data-otp-autofill-proxy="true"]';
  const activeSubmissions = new WeakSet();

  const digits = (value, limit) => String(value || '')
    .replace(/\D/g, '')
    .slice(0, limit);

  const setNativeValue = (input, value, windowObject) => {
    if (!input) return;
    const prototype = windowObject && windowObject.HTMLInputElement
      ? windowObject.HTMLInputElement.prototype
      : null;
    const descriptor = prototype && Object.getOwnPropertyDescriptor(prototype, 'value');
    if (descriptor && typeof descriptor.set === 'function') descriptor.set.call(input, value);
    else input.value = value;
  };

  const defer = (windowObject, callback) => {
    if (windowObject && typeof windowObject.queueMicrotask === 'function') {
      windowObject.queueMicrotask(callback);
      return;
    }
    if (typeof queueMicrotask === 'function') {
      queueMicrotask(callback);
      return;
    }
    if (typeof Promise === 'function') {
      Promise.resolve().then(callback);
      return;
    }
    if (windowObject && typeof windowObject.setTimeout === 'function') {
      windowObject.setTimeout(callback, 0);
      return;
    }
    if (typeof setTimeout === 'function') setTimeout(callback, 0);
  };

  const findProxy = (form) => {
    if (!form) return null;
    if (typeof form.querySelector === 'function') {
      const attached = form.querySelector(PROXY_SELECTOR);
      if (attached) return attached;
    }
    return form.__cardboardOtpAutofillProxy || null;
  };

  const findCells = (form, proxy, documentObject, windowObject) => {
    const remembered = proxy && Array.isArray(proxy.__otpCells)
      ? proxy.__otpCells.filter((cell) => cell && cell !== proxy && cell.form === form)
      : [];
    if (remembered.length) return remembered;

    const api = windowObject && windowObject.CardboardOtpAutofill;
    if (!api || typeof api.findOtpCells !== 'function') return [];
    return api.findOtpCells(form, documentObject, windowObject)
      .filter((cell) => cell && cell !== proxy && cell.form === form);
  };

  const readVisibleCode = (cells) => {
    const values = cells.map((cell) => digits(cell && cell.value, 1));
    return values.every((value) => value.length === 1) ? values.join('') : '';
  };

  const reconcileOtpState = (form, documentObject, windowObject) => {
    const proxy = findProxy(form);
    if (!proxy) return { complete: false, source: 'none', code: '' };

    const cells = findCells(form, proxy, documentObject, windowObject);
    if (!cells.length) return { complete: false, source: 'none', code: '' };

    proxy.__otpCells = cells;
    const expectedLength = cells.length;
    const visibleCode = readVisibleCode(cells);
    const proxyCode = digits(proxy.value, expectedLength);

    if (visibleCode.length === expectedLength) {
      if (proxyCode !== visibleCode) setNativeValue(proxy, visibleCode, windowObject);
      if (proxy.dataset) proxy.dataset.lastOtpValue = visibleCode;
      return { complete: true, source: 'cells', code: visibleCode };
    }

    if (proxyCode.length === expectedLength) {
      cells.forEach((cell, index) => setNativeValue(cell, proxyCode[index], windowObject));
      if (proxy.dataset) proxy.dataset.lastOtpValue = proxyCode;
      return { complete: true, source: 'proxy', code: proxyCode };
    }

    return { complete: false, source: 'partial', code: '' };
  };

  const coordinateSubmit = (event, documentObject, windowObject) => {
    const form = event && event.target;
    if (!form || !form.dataset) return true;

    reconcileOtpState(form, documentObject, windowObject);

    if (activeSubmissions.has(form)) {
      if (typeof event.preventDefault === 'function') event.preventDefault();
      if (typeof event.stopImmediatePropagation === 'function') event.stopImmediatePropagation();
      return false;
    }

    // The parent OTP implementation used a broad ten-second lock. EasyStore can
    // legitimately submit the same form again in a later task to finish login or
    // registration, so retain only same-task re-entrancy protection here.
    delete form.dataset.otpSubmissionInFlight;
    form.dataset.otpSubmissionCoordinator = 'true';
    activeSubmissions.add(form);
    defer(windowObject, () => activeSubmissions.delete(form));
    return true;
  };

  const bind = (documentObject, windowObject) => {
    if (!documentObject || typeof documentObject.addEventListener !== 'function') return;
    if (documentObject.__cardboardOtpSubmitCoordinatorBound) return;

    documentObject.__cardboardOtpSubmitCoordinatorBound = true;
    documentObject.addEventListener(
      'submit',
      (event) => coordinateSubmit(event, documentObject, windowObject),
      true,
    );
  };

  const api = {
    bind,
    coordinateSubmit,
    findCells,
    findProxy,
    readVisibleCode,
    reconcileOtpState,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    window.CardboardOtpVerificationCoordinator = api;
    api.bind(document, window);
  }
})();
