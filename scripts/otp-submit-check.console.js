/*
 * Paste into the browser console on /account/login, then walk the whole OTP
 * flow: enter the mobile number, click "Login with SMS", wait for the code
 * screen. Then call __otpCheck().
 *
 * It answers one question: did a request asking EasyStore to send the code
 * actually go out, and what came back?
 *
 * The theme cannot send an SMS - EasyStore does. So there are only two answers:
 *
 *   - no send request fires, or it fails, or it carries the wrong value
 *       -> something on the page is at fault, and the record below names it
 *   - a send request succeeds and still no text arrives
 *       -> EasyStore's side: SMS credits, gateway, provider, or a rate limit.
 *          No theme deploy fixes that.
 *
 * Two things this handles that a naive console snippet does not:
 *
 *   - "Login with SMS" comes from `{% app_snippet 'login/button' %}`, an
 *     EasyStore app snippet. Its endpoint is not a theme URL and cannot be
 *     guessed, so EVERY request is recorded, not a matching subset.
 *   - the flow changes screens. Records persist in sessionStorage and the hooks
 *     reinstall themselves on each page, so a navigation does not lose the trail.
 *
 * Read-only. It wraps fetch, XHR, sendBeacon and submit to observe them, and
 * never blocks, alters or replays anything.
 */
(() => {
  const KEY = 'otpSubmitCheck';
  const STATIC = /\.(css|js|mjs|png|jpe?g|gif|svg|webp|avif|woff2?|ttf|eot|ico|map)(\?|$)/i;

  const load = () => {
    try {
      return JSON.parse(window.sessionStorage.getItem(KEY) || '[]');
    } catch (_error) {
      return [];
    }
  };

  const save = (records) => {
    try {
      // Bounded so a chatty page cannot fill storage mid-diagnosis.
      window.sessionStorage.setItem(KEY, JSON.stringify(records.slice(-200)));
    } catch (_error) {
      // A full sessionStorage only costs the persisted trail, not the live log.
    }
  };

  const record = (entry) => {
    const records = load();
    records.push({ at: new Date().toISOString().slice(11, 23), page: location.pathname, ...entry });
    save(records);
    // Static assets are recorded but not printed; they drown the interesting rows.
    if (!STATIC.test(entry.url || '')) {
      console.log(`[${entry.kind}] ${entry.method || ''} ${entry.url}`, entry.status ?? entry.error ?? '');
    }
  };

  if (window.__otpCheckInstalled) {
    console.log('Already installed on this page. Call __otpCheck() for the trail.');
  } else {
    window.__otpCheckInstalled = true;

    const nativeFetch = window.fetch;
    if (typeof nativeFetch === 'function') {
      window.fetch = function (input, init) {
        const url = String((input && input.url) || input || '');
        const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
        const body = (init && init.body) || null;
        return nativeFetch.apply(this, arguments).then((response) => {
          record({ kind: 'fetch', method, url, status: response.status, body: summarize(body) });
          return response;
        }, (error) => {
          record({ kind: 'fetch', method, url, error: String(error && error.message), body: summarize(body) });
          throw error;
        });
      };
    }

    const nativeOpen = XMLHttpRequest.prototype.open;
    const nativeSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url) {
      this.__otpMethod = String(method).toUpperCase();
      this.__otpUrl = String(url);
      return nativeOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function (body) {
      this.addEventListener('loadend', () => {
        record({
          kind: 'xhr',
          method: this.__otpMethod,
          url: this.__otpUrl,
          status: this.status,
          body: summarize(body),
        });
      });
      return nativeSend.apply(this, arguments);
    };

    if (typeof navigator.sendBeacon === 'function') {
      const nativeBeacon = navigator.sendBeacon.bind(navigator);
      navigator.sendBeacon = function (url, data) {
        record({ kind: 'beacon', method: 'POST', url: String(url), body: summarize(data) });
        return nativeBeacon(url, data);
      };
    }

    // Capture phase: runs before every other handler, so it sees the form as it
    // was BEFORE anything else could touch it. On its own this proves nothing
    // about what was sent - see the formdata hook below.
    document.addEventListener('submit', (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement)) return;
      record({
        kind: 'submit(before)',
        method: String(form.getAttribute('method') || 'GET').toUpperCase(),
        url: String(form.getAttribute('action') || location.pathname),
        prevented: event.defaultPrevented,
        fields: fieldsOf(form),
      });

      // Bubble phase on the form itself: last thing to run, so a handler that
      // rewrites the action or a value between the two shows up as a difference.
      form.addEventListener('submit', (late) => {
        record({
          kind: 'submit(after)',
          method: String(form.getAttribute('method') || 'GET').toUpperCase(),
          url: String(form.getAttribute('action') || location.pathname),
          prevented: late.defaultPrevented,
          fields: fieldsOf(form),
        });
      }, { once: true });

      // The authoritative payload. `formdata` fires as the browser builds the
      // entry list for the request, after every handler has had its turn, so
      // this is what EasyStore actually receives - including fields no selector
      // guessed at, such as a country or dial code.
      form.addEventListener('formdata', (fd) => {
        const entries = [];
        fd.formData.forEach((value, key) => {
          const shown = key === '_token' ? '(present)' : String(value).slice(0, 60);
          entries.push(`${key}=${shown}`);
        });
        record({ kind: 'PAYLOAD', method: 'POST', url: String(form.getAttribute('action') || location.pathname), body: entries.join('&').slice(0, 600) });
      }, { once: true });
    }, true);
  }

  // Every control in the form, not a guessed subset. A field the theme's CSS has
  // made invisible or untappable - which is how this theme once broke a
  // platform-rendered control - shows up here as empty or hidden rather than
  // being missed entirely.
  function fieldsOf(form) {
    try {
      return Array.from(form.elements)
        .filter((element) => element.name)
        .map((element) => {
          const value = element.type === 'password' ? '(hidden)'
            : element.name === '_token' ? '(present)'
              : String(element.value || '').slice(0, 40);
          const visible = element.offsetParent !== null || element.type === 'hidden';
          return `${element.name}=${JSON.stringify(value)}${visible ? '' : ' [NOT VISIBLE]'}`;
        })
        .join(' ')
        .slice(0, 600);
    } catch (_error) {
      return '[unreadable]';
    }
  }

  function summarize(body) {
    if (!body) return null;
    try {
      if (typeof body === 'string') return body.slice(0, 300);
      if (body instanceof FormData) {
        return Array.from(body.entries())
          .map(([key, value]) => `${key}=${String(value).slice(0, 60)}`)
          .join('&')
          .slice(0, 300);
      }
      if (body instanceof URLSearchParams) return body.toString().slice(0, 300);
      return `[${body.constructor && body.constructor.name}]`;
    } catch (_error) {
      return '[unreadable]';
    }
  }

  const limits = window.CustomerOrderLimits;
  console.log('--- page ---', location.pathname);
  console.log('fixed build:', Boolean(limits && typeof limits.onAuthEntryPage === 'function'));
  console.log('records carried over:', load().length);

  window.__otpCheck = () => {
    const records = load();
    const interesting = records.filter((row) => !STATIC.test(row.url || ''));
    console.log(`--- ${interesting.length} non-static events (${records.length} total) ---`);
    console.table(interesting);
    console.log('Look for the request fired by "Login with SMS".');
    console.log('Succeeded (2xx/3xx) and still no text? EasyStore-side, not the theme.');
    return interesting;
  };
  window.__otpReset = () => {
    try { window.sessionStorage.removeItem(KEY); } catch (_error) { /* nothing to clear */ }
    console.log('Trail cleared.');
  };

  // Printed on install, not only on demand: the flow changes screens and takes
  // the console with it, so anyone re-pasting here has already lost the last
  // page's output and should not have to remember a second call to get it back.
  if (load().length) window.__otpCheck();

  console.log('Installed. Re-paste on each new screen; the trail prints itself.');
  console.log('Signup posts natively (POST /account/register -> 302 /account/auth),');
  console.log('so open DevTools Network with "Preserve log" to see that response.');
})();
