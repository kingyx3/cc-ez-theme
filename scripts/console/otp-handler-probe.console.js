/*
 * Second read-only probe for the one-time-code step. Run it after
 * otp-widget-capture.console.js, on the same screen.
 *
 * The capture answered the first question: the cells hold no framework state,
 * so the widget reads input.value and the digits could be written by plain
 * assignment. It also showed the widget has no Verify button of its own - the
 * only control is "Resend in Ns" - which means it almost certainly posts by
 * itself once the last cell fills. That is the exact mechanism that broke
 * signup: PR #66 wrote every cell and fired input and change on each, so the
 * widget's own completion path ran more than once and the second POST came back
 * "Customer already exists (phone)".
 *
 * So the remaining question is narrow and decisive: which events does the widget
 * actually listen to, and what does its handler do when the code is complete? A
 * fix may dispatch at most the single event a human's last keystroke would
 * produce, and to know which one that is, the handler has to be read.
 *
 * jQuery is on the page, and jQuery keeps its handlers in a registry, so they
 * can be printed as source instead of guessed at from minified bundles. Native
 * listeners are covered too via getEventListeners, which exists when this is
 * pasted into DevTools.
 *
 * Like the capture, this only reads. No value is set, no event dispatched, no
 * listener added, no node removed. It is safe to run during a real signup, and
 * it prints no digits - a live code is a secret.
 */
(async () => {
  const out = (label, value) => console.log(String(label).padEnd(26), value);
  const text = (node) => ((node && node.textContent) || '').replace(/\s+/g, ' ').trim();

  const cells = Array.from(document.querySelectorAll('.otp-input, input[maxlength="1"][pattern]'));
  const container = document.getElementById('otp-form')
    || (cells[0] ? cells[0].parentElement : null);

  if (!cells.length) {
    console.log('NO CELLS FOUND: run this on the six-cell code step.');
    return;
  }

  console.log('--- widget ---');
  out('cells', cells.length);
  out('container', container ? (container.id ? '#' + container.id : container.className) : '(not found)');

  // The submit control may live outside the widget, so the whole page is swept
  // rather than just the container the capture looked in.
  console.log('--- every button on the page ---');
  Array.from(document.querySelectorAll('button, input[type="submit"], a.btn, [role="button"]'))
    .forEach((node) => out(
      node.tagName.toLowerCase() + (node.id ? '#' + node.id : ''),
      JSON.stringify(text(node) || node.value || '(no label)')
        + (node.offsetParent === null ? ' [hidden]' : ' [visible]')
    ));

  // jQuery's registry names the events the widget cares about and hands back the
  // handler functions themselves, which is the whole answer when it binds this
  // way. jQuery.migrate is loaded too, so _data is present.
  console.log('--- jQuery handlers ---');
  const jq = window.jQuery || window.$;
  if (!jq || !jq._data) {
    out('jQuery registry', '(unavailable — rely on the native listeners below)');
  } else {
    const seen = new Set();
    const report = (node, label) => {
      const events = jq._data(node, 'events');
      if (!events) return out(label, '(no jQuery handlers)');
      Object.keys(events).forEach((type) => {
        events[type].forEach((entry) => {
          const source = String(entry.handler);
          const key = type + source;
          out(label + ' on:' + type, entry.selector ? 'delegated ' + entry.selector : 'direct');
          if (seen.has(key)) return;
          seen.add(key);
          console.log(source.length > 4000 ? source.slice(0, 4000) + '\n…truncated' : source);
        });
      });
      return undefined;
    };
    report(cells[0], 'cell 0');
    report(cells[cells.length - 1], 'last cell');
    if (container) report(container, 'container');
    // Delegated handlers commonly sit on document or body.
    report(document, 'document');
    report(document.body, 'body');
  }

  // Anything bound with addEventListener instead of jQuery shows up here. This
  // API only exists in DevTools, which is where this script is meant to run.
  console.log('--- native listeners ---');
  if (typeof getEventListeners !== 'function') {
    out('getEventListeners', '(not available — paste this straight into DevTools console)');
  } else {
    [[cells[0], 'cell 0'], [cells[cells.length - 1], 'last cell'], [container, 'container'],
     [document, 'document']].forEach(([node, label]) => {
      if (!node) return;
      const listeners = getEventListeners(node);
      const types = Object.keys(listeners || {});
      out(label, types.length ? types.join(', ') : '(none)');
      types.forEach((type) => listeners[type].forEach((entry) => {
        const source = String(entry.listener);
        console.log(label + ' ' + type + ':\n'
          + (source.length > 2000 ? source.slice(0, 2000) + '\n…truncated' : source));
      }));
    });
  }

  // Where the verification is posted from, read straight out of the bundles.
  console.log('--- bundle search ---');
  const sources = Array.from(document.querySelectorAll('script[src]'))
    .map((node) => node.src)
    .filter((src) => src.startsWith(location.origin) || /easystore/i.test(src))
    .filter((src) => !/global\.js|search-history|account-otp-copy|account-recovery|cart-|details-modal|product-|purchase-limit|buy-now/.test(src));

  for (const src of sources) {
    let body = '';
    try {
      body = await (await fetch(src, { credentials: 'same-origin' })).text();
    } catch (error) {
      out('could not read', src + ' — ' + error.message);
      continue;
    }
    // Hits that matter: where the widget names the cells, and where it posts.
    const marks = [];
    [/otp[-_ ]?input/gi, /otp[-_ ]?form/gi, /\/account\/auth\/[a-z]+/gi, /verify/gi].forEach((pattern) => {
      let match = pattern.exec(body);
      let guard = 0;
      while (match && guard < 12) {
        marks.push(match.index);
        guard += 1;
        match = pattern.exec(body);
      }
    });
    if (!marks.length) continue;
    out('hits in', src.split('/').pop() + ' — ' + marks.length);
    // Merge nearby hits so one region is not printed many times over.
    const windows = [];
    marks.sort((a, b) => a - b).forEach((index) => {
      const last = windows[windows.length - 1];
      if (last && index - last < 400) return;
      windows.push(index);
    });
    windows.slice(0, 8).forEach((index) => {
      console.log('… ' + body.slice(Math.max(0, index - 500), index + 700).replace(/\n{2,}/g, '\n') + ' …');
    });
  }

  console.log('--- what to send back ---');
  console.log(
    'The handler source above is the answer. Two things decide the fix: which '
    + 'event the widget listens to on a cell, and whether it posts by itself once '
    + 'all six are filled. Copy this whole output.'
  );
})();
