/*
 * Paste into the browser console on /account/login (or /account/register) BEFORE
 * submitting, then submit a mobile number. It reports which side of the OTP flow
 * is failing.
 *
 * The theme cannot send an SMS - EasyStore does. So there are only two answers,
 * and the POST result tells them apart:
 *
 *   - the POST never fires, or fails, or carries the wrong value
 *       -> the theme's problem, and the report below says which
 *   - the POST succeeds and the flow advances, and still no text arrives
 *       -> EasyStore's side: SMS credits, gateway, provider, or a rate limit.
 *          No theme deploy fixes that.
 *
 * It also answers "is the fix even deployed here", which is the first thing to
 * rule out when a change appears not to have worked: the packaging workflow
 * imports each branch as an UNPUBLISHED theme, so the live storefront keeps
 * serving the published one until someone publishes the new build.
 *
 * Read-only. It wraps fetch, XHR and form submits to observe them, and never
 * blocks, alters or replays anything.
 */
(() => {
  const out = (label, value) => console.log(String(label).padEnd(26), value);
  const AUTH_POST = /\/account\/(login|register|recover|auth|activate)/;
  const seen = [];

  console.log('--- page ---');
  out('path', location.pathname + location.search + location.hash);

  console.log('--- is the fix deployed here? ---');
  // onAuthEntryPage is exported only by the build that stops the order crawl
  // running from the auth pages. Its absence means this storefront is serving a
  // theme from before that change, whatever the repository says.
  const limits = window.CustomerOrderLimits;
  const hasFix = Boolean(limits && typeof limits.onAuthEntryPage === 'function');
  out('CustomerOrderLimits', Boolean(limits));
  out('onAuthEntryPage present', hasFix);
  out('verdict', hasFix
    ? 'this page is running the fixed build'
    : 'PRE-FIX BUILD - publish the imported theme before judging the fix');
  if (hasFix) out('treated as auth page', limits.onAuthEntryPage());

  console.log('--- watching requests (submit the form now) ---');

  const note = (kind, method, url, extra) => {
    const record = { kind, method, url, ...extra };
    seen.push(record);
    if (AUTH_POST.test(url) || /\/account\/orders/.test(url)) {
      console.log(`[${kind}] ${method} ${url}`, extra || '');
    }
  };

  const nativeFetch = window.fetch;
  if (typeof nativeFetch === 'function') {
    window.fetch = function (input, init) {
      const url = String((input && input.url) || input || '');
      const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
      return nativeFetch.apply(this, arguments).then((response) => {
        note('fetch', method, url, { status: response.status });
        return response;
      }, (error) => {
        note('fetch', method, url, { error: String(error && error.message) });
        throw error;
      });
    };
  }

  const nativeOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.addEventListener('loadend', () => {
      note('xhr', String(method).toUpperCase(), String(url), { status: this.status });
    });
    return nativeOpen.apply(this, arguments);
  };

  // A native form submit leaves the page, so it is reported as it happens rather
  // than on a response. The value is what matters: EasyStore texts a phone
  // number, and an autofilled email address is a value it cannot text.
  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    const action = String(form.getAttribute('action') || location.pathname);
    if (!AUTH_POST.test(action)) return;

    const field = form.querySelector('[name="customer[email_or_phone]"], [name="email_or_phone"]');
    const value = String((field && field.value) || '').trim();
    const looksLikeEmail = /@/.test(value);
    const digits = value.replace(/\D/g, '');

    console.log('--- auth form submitted ---');
    out('action', action);
    out('method', String(form.getAttribute('method') || 'get').toUpperCase());
    out('identifier field', field ? field.getAttribute('name') : '(NOT FOUND)');
    out('value looks like', looksLikeEmail ? 'EMAIL - no SMS can be sent' : `phone (${digits.length} digits)`);
    out('csrf token present', Boolean(form.querySelector('[name="_token"]')?.value));
    out('default prevented', event.defaultPrevented);
    if (event.defaultPrevented) {
      out('meaning', 'a script blocked this POST - it never reached EasyStore');
    }
    out('requests so far', JSON.stringify(seen.slice(-10)));
  }, true);

  window.__otpCheck = () => seen;
  console.log('Ready. Submit the form. Call __otpCheck() afterwards for the full list.');
  console.log('If the POST returns 200/302 and the page advances with no SMS,');
  console.log('the theme did its job and the failure is EasyStore-side.');
})();
