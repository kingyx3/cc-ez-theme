/*
 * Paste into the browser console on the live one-time-code step (/account/auth)
 * to capture the verification widget's real markup and its own submit
 * behaviour.
 *
 * Why this exists rather than a fix
 * --------------------------------
 * The one-time-code step is rendered by EasyStore, not by this theme, so its
 * markup is not in this repository and cannot be read from source. Theme code
 * that wrote into those cells shipped twice (PR #65, PR #66) and broke signup
 * the same day: each synthetic event drove the widget's own submit path, the
 * verification posted more than once, and the second POST came back "Customer
 * already exists (phone)". The widget posts over fetch, so a submit-event lock
 * cannot deduplicate it. See tests/test_otp_cell_autofill.py.
 *
 * The two facts a safe fix needs, and neither is guessable, are exactly what
 * this probe reports:
 *   1. The cells' real structure and attributes - how many, what maxlength,
 *      what autocomplete, whether they sit in a <form>, which framework owns
 *      them. That decides whether Android's split-autofill can be fixed with
 *      attributes alone or needs values written.
 *   2. What the widget already does by itself when the code arrives - which
 *      events it reacts to and how many verification requests it fires. That
 *      decides what a fix must avoid triggering a second time.
 *
 * This probe is strictly passive. It never writes a cell value, never
 * dispatches an event, and never blocks or alters a request - it only reads
 * attributes and records what the page and the browser do on their own. It
 * lives in scripts/, which is excluded from the theme ZIP, so nothing here ever
 * ships to the storefront.
 *
 * Running it on the Android handset
 * ---------------------------------
 *   1. Enable USB debugging on the phone and connect it to a computer.
 *   2. Open chrome://inspect/#devices in desktop Chrome and "inspect" the tab
 *      showing the verification step.
 *   3. Paste this whole file into that console and press enter.
 *   4. On the phone, tap the OTP autofill suggestion on the keyboard exactly as
 *      you normally would. Do not type anything.
 *   5. Back in the console run: __otpProbe.report()
 *      It prints the transcript and returns it as a string. copy(__otpProbe.report())
 *      puts it on the clipboard.
 *   6. __otpProbe.stop() restores fetch and XHR when you are done.
 *
 * Every digit is masked as a bullet before anything is printed, so the report
 * can be pasted into an issue or a chat without leaking a live code or a phone
 * number.
 */
(() => {
  'use strict';

  const MIN_CELLS = 4;
  const MAX_CELLS = 8;
  // Cells are usually wrapped one-per-<div>, so the element that groups a whole
  // widget is rarely the direct parent. Never widened as far as <body>: inputs
  // scattered across a page are unrelated fields, not one widget.
  const MAX_CONTAINER_DEPTH = 5;
  // Fields that merely look narrow or contain "code" but are never one-time
  // codes. Kept as a deny list so a country or postal code cannot be reported
  // as an OTP cell.
  const NON_OTP_PATTERN = /(?:country|dial|calling|postal|postcode|zip|area|state|province|city|address|currency|language|locale|discount|promo|coupon|voucher|referral|invite|product|variant|sku|barcode|colou?r|search|query)/i;
  const OTP_PATTERN = /(?:otp|passcode|one[-_ ]?time|verification|verify|token|challenge|two[-_ ]?factor|2fa|pin|digit|code)/i;
  const RECORDED_EVENTS = ['beforeinput', 'input', 'change', 'keydown', 'paste', 'submit', 'focus'];
  // Requests the page makes anyway. Filtered out of the verdict so the count of
  // verification posts is not buried in analytics and asset traffic.
  const NOISE_PATTERN = /(?:\.(?:js|css|png|jpe?g|gif|svg|woff2?|ico)(?:\?|$)|google-analytics|googletagmanager|facebook|hotjar|sentry|doubleclick|clarity\.ms)/i;

  // Digits are masked before printing: a live code, a phone number and a
  // customer id are all digits, and this report is meant to be shared.
  const mask = (value) => String(value == null ? '' : value).replace(/\d/g, '•');
  const out = (label, value) => console.log(String(label).padEnd(24), value);

  // Attributes that can carry a code or a phone number. Everything else -
  // maxlength, size, pattern, inputmode, autocomplete, name, id - is printed
  // verbatim, because those digits are the answer, not the secret: masking
  // maxlength="1" into maxlength="•" would hide the one attribute that decides
  // whether Android truncates the autofilled code.
  const SENSITIVE_ATTRIBUTES = ['value', 'placeholder', 'aria-label', 'title'];

  const maskedMarkup = (container) => {
    const clone = container.cloneNode(true);
    const live = [container].concat(Array.from(container.querySelectorAll('input, textarea')));
    const copies = [clone].concat(Array.from(clone.querySelectorAll('input, textarea')));

    copies.forEach((node, index) => {
      // A cell's current contents live on the property, not the attribute, so
      // a filled cell would print an empty value="" without this.
      if (node.tagName === 'INPUT' || node.tagName === 'TEXTAREA') {
        node.setAttribute('value', mask(live[index] ? live[index].value : ''));
      }
      SENSITIVE_ATTRIBUTES.forEach((name) => {
        if (node.hasAttribute && node.hasAttribute(name)) {
          node.setAttribute(name, mask(node.getAttribute(name)));
        }
      });
    });

    // Text nodes carry the "we sent a code to +65 ..." line.
    const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT, null);
    while (walker.nextNode()) walker.currentNode.nodeValue = mask(walker.currentNode.nodeValue);

    return clone.outerHTML.replace(/\s+/g, ' ').trim();
  };

  const started = (window.performance && performance.now) ? performance.now() : 0;
  const now = () => Math.round(((window.performance && performance.now) ? performance.now() : 0) - started);

  const lines = [];
  const record = (text) => {
    lines.push('[+' + String(now()).padStart(6) + 'ms] ' + text);
  };

  const attr = (element, name) => {
    const value = element.getAttribute(name);
    return value === null ? null : value;
  };

  const isCandidate = (input) => {
    const type = (attr(input, 'type') || 'text').toLowerCase();
    if (['hidden', 'checkbox', 'radio', 'submit', 'button', 'file', 'password'].includes(type)) return false;
    if (input.disabled) return false;

    const context = [
      attr(input, 'name') || '',
      input.id || '',
      input.className || '',
      attr(input, 'aria-label') || '',
      attr(input, 'placeholder') || '',
    ].join(' ');
    if (NON_OTP_PATTERN.test(context)) return false;

    return input.maxLength === 1
      || attr(input, 'size') === '1'
      || (attr(input, 'autocomplete') || '').toLowerCase() === 'one-time-code'
      || OTP_PATTERN.test(context);
  };

  const groupContainer = (cell, cells) => {
    let node = cell.parentElement;
    let depth = 0;
    while (node && node !== document.body && depth < MAX_CONTAINER_DEPTH) {
      if (cells.filter((candidate) => node.contains(candidate)).length >= MIN_CELLS) return node;
      node = node.parentElement;
      depth += 1;
    }
    return null;
  };

  const findGroups = () => {
    const candidates = Array.from(document.querySelectorAll('input')).filter(isCandidate);
    const groups = new Map();

    candidates.forEach((cell) => {
      const container = groupContainer(cell, candidates);
      if (!container) return;
      if (!groups.has(container)) groups.set(container, []);
      groups.get(container).push(cell);
    });

    const grouped = Array.from(groups.entries())
      .filter(([, cells]) => cells.length >= MIN_CELLS && cells.length <= MAX_CELLS)
      .map(([container, cells]) => ({ container, cells }));

    // A store that already uses one wide input still needs reporting - it is
    // the shape the fix might be moving towards, and "there are no cells" is a
    // finding, not a failure.
    if (grouped.length) return grouped;

    const singles = candidates.filter((input) => input.maxLength !== 1 && attr(input, 'size') !== '1');
    return singles.length ? [{ container: singles[0].parentElement, cells: singles.slice(0, 1) }] : [];
  };

  const describePath = (element) => {
    const parts = [];
    for (let node = element; node && node !== document.body && parts.length < 6; node = node.parentElement) {
      let part = node.tagName.toLowerCase();
      if (node.id) part += '#' + node.id;
      else if (node.className && typeof node.className === 'string') {
        part += '.' + node.className.trim().split(/\s+/).slice(0, 3).join('.');
      }
      parts.unshift(part);
    }
    return parts.join(' > ');
  };

  // Which library owns the cells decides whether writing a value is even seen.
  // React and Vue read their own state, not the DOM property, so a fix has to
  // go through the native value setter rather than assigning input.value.
  const frameworkHints = (element) => {
    const hints = [];
    for (let node = element; node && node !== document.body; node = node.parentElement) {
      const keys = Object.keys(node);
      if (keys.some((key) => key.startsWith('__react'))) hints.push('React (' + node.tagName.toLowerCase() + ')');
      if (keys.some((key) => key === '__vue__' || key.startsWith('__vue'))) hints.push('Vue (' + node.tagName.toLowerCase() + ')');
      if (keys.some((key) => key.startsWith('_x_'))) hints.push('Alpine (' + node.tagName.toLowerCase() + ')');
      if (node.hasAttribute && node.hasAttribute('data-controller')) hints.push('Stimulus: ' + attr(node, 'data-controller'));
      if (node.hasAttribute && node.hasAttribute('wire:id')) hints.push('Livewire');
      if (node.attributes && Array.from(node.attributes).some((one) => one.name.startsWith('data-v-'))) {
        hints.push('Vue SFC scope (' + node.tagName.toLowerCase() + ')');
      }
    }
    return Array.from(new Set(hints));
  };

  console.log('=== OTP widget probe ===');
  console.log('--- page ---');
  out('path', location.pathname + location.search + location.hash);
  out('title', document.title);
  // The same markers scripts/account-copy-check.console.js uses. If any is
  // present this page is the theme's own and a template change could reach it;
  // if none is, the markup below belongs to EasyStore and only the platform can
  // change it.
  const themeRendered = Boolean(
    document.querySelector('form[action="/account/recover"]')
    || document.querySelector('#RecoverEmail')
    || document.querySelector('#form-login')
  );
  out('theme renders page', themeRendered);
  record('probe installed on ' + location.pathname + ' (theme-rendered: ' + themeRendered + ')');

  const groups = findGroups();
  out('candidate groups', groups.length);

  if (!groups.length) {
    console.log(
      'No one-time-code fields found on this page. Run the probe on the step '
      + 'that actually shows the code boxes - it is a separate page from the '
      + 'login form.'
    );
  }

  const watched = [];

  groups.forEach((group, groupIndex) => {
    console.log('--- widget ' + (groupIndex + 1) + ' ---');
    out('cells', group.cells.length);
    out('container', describePath(group.container));

    const form = group.cells[0].closest('form');
    out('form', form ? (attr(form, 'action') || '(no action)') + ' [' + (attr(form, 'method') || 'get') + ']' : '(no surrounding form)');
    out('framework', frameworkHints(group.container).join(', ') || '(none detected)');

    console.table(group.cells.map((cell, index) => ({
      index,
      type: attr(cell, 'type') || '(none)',
      name: attr(cell, 'name') || '',
      id: cell.id || '',
      class: (cell.className || '').slice(0, 40),
      maxlength: attr(cell, 'maxlength'),
      size: attr(cell, 'size'),
      autocomplete: attr(cell, 'autocomplete'),
      inputmode: attr(cell, 'inputmode'),
      pattern: attr(cell, 'pattern'),
      placeholder: mask(attr(cell, 'placeholder') || ''),
      'aria-label': mask(attr(cell, 'aria-label') || ''),
      readonly: cell.readOnly,
      'value length': String(cell.value || '').length,
    })));

    // The shape of the wrapper matters as much as the cells: whether each cell
    // has its own <div>, whether a hidden aggregate input holds the whole code,
    // and whether a <form> wraps them at all.
    console.log('container markup (values and copy masked, structure verbatim):');
    console.log(maskedMarkup(group.container).slice(0, 2000));

    const aggregate = Array.from(document.querySelectorAll('input[type="hidden"]'))
      .filter((input) => OTP_PATTERN.test((attr(input, 'name') || '') + ' ' + (input.id || '')));
    if (aggregate.length) {
      out('hidden aggregate', aggregate.map((input) => attr(input, 'name') || input.id).join(', '));
    }

    // Chrome DevTools only. Tells us which events the widget itself listens
    // for, which is the difference between a fix that posts once and one that
    // posts twice.
    if (typeof getEventListeners === 'function') {
      const listeners = {};
      [group.container, group.cells[0], form].filter(Boolean).forEach((node) => {
        const found = getEventListeners(node);
        Object.keys(found || {}).forEach((type) => {
          const key = node.tagName.toLowerCase() + ':' + type;
          listeners[key] = found[type].length;
        });
      });
      out('listeners', JSON.stringify(listeners));
    } else {
      out('listeners', '(run in Chrome DevTools to list them)');
    }

    group.cells.forEach((cell, index) => watched.push({ cell, index, groupIndex }));
  });

  // --- passive recorders -------------------------------------------------
  // Capture phase, so the widget's own handlers are still the ones that act.
  // Nothing here calls preventDefault or stopPropagation.
  const listener = (event) => {
    const entry = watched.find((one) => one.cell === event.target);
    const where = entry
      ? 'cell ' + entry.index + ' of widget ' + (entry.groupIndex + 1)
      : (event.target && event.target.tagName ? event.target.tagName.toLowerCase() : 'document');

    const details = [
      'trusted=' + event.isTrusted,
      event.inputType ? 'inputType=' + event.inputType : '',
      event.data != null ? 'data=' + mask(event.data) : '',
      event.key ? 'key=' + mask(event.key) : '',
      entry ? 'valueLen=' + String(entry.cell.value || '').length : '',
    ].filter(Boolean).join(' ');

    record(event.type + ' on ' + where + ' ' + details);
  };

  RECORDED_EVENTS.forEach((type) => document.addEventListener(type, listener, true));

  const originalFetch = window.fetch;
  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;

  const noteRequest = (transport, method, url, body) => {
    const target = String(url || '');
    if (NOISE_PATTERN.test(target)) return;
    const size = body == null ? 0 : String(body).length;
    record(transport + ' ' + String(method || 'GET').toUpperCase() + ' ' + mask(target) + (size ? ' (body ' + size + ' bytes)' : ''));
  };

  // Wrapped, never replaced: the original is always called with the original
  // arguments and its result is returned untouched, so the widget's own request
  // behaves exactly as it would without the probe.
  window.fetch = function probedFetch(input, init) {
    try {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      const method = (init && init.method) || (input && input.method) || 'GET';
      noteRequest('fetch', method, url, init && init.body);
    } catch (error) {
      record('fetch probe failed: ' + error.message);
    }
    return originalFetch.apply(this, arguments);
  };

  XMLHttpRequest.prototype.open = function probedOpen(method, url) {
    this.__otpProbeMethod = method;
    this.__otpProbeUrl = url;
    return originalOpen.apply(this, arguments);
  };

  XMLHttpRequest.prototype.send = function probedSend(body) {
    try {
      noteRequest('xhr', this.__otpProbeMethod, this.__otpProbeUrl, body);
    } catch (error) {
      record('xhr probe failed: ' + error.message);
    }
    return originalSend.apply(this, arguments);
  };

  const report = () => {
    const posts = lines.filter((line) => / (?:fetch|xhr) POST /.test(line));
    // Read the cells rather than counting events: which cells ended up holding
    // a digit is the symptom being investigated, and it is true whether or not
    // the browser marked its autofill events as trusted.
    const filled = watched.filter((one) => String(one.cell.value || '').length > 0);
    // Only a symptom when the widget is split into cells. One wide input
    // holding the whole code is the shape that already works.
    const overfull = watched.length > 1
      ? watched.filter((one) => String(one.cell.value || '').length > 1)
      : [];

    const body = [
      '=== OTP widget probe report ===',
      'path: ' + location.pathname,
      'theme renders page: ' + themeRendered,
      'widgets: ' + groups.length + ', cells: ' + watched.length,
      '',
      '--- timeline ---',
      ...lines,
      '',
      '--- verdict ---',
      'cells holding a value: ' + filled.length + ' of ' + watched.length
        + (overfull.length
          ? ' - cell ' + overfull.map((one) => one.index).join(', ') + ' holds more than one character,'
            + ' so the whole code landed in one box'
          : ''),
      'cell lengths: ' + JSON.stringify(watched.map((one) => String(one.cell.value || '').length)),
      'verification-shaped POSTs while recording: ' + posts.length
        + (posts.length > 1 ? ' - the widget already posts more than once on its own' : ''),
    ].join('\n');

    console.log(body);
    return body;
  };

  const stop = () => {
    RECORDED_EVENTS.forEach((type) => document.removeEventListener(type, listener, true));
    window.fetch = originalFetch;
    XMLHttpRequest.prototype.open = originalOpen;
    XMLHttpRequest.prototype.send = originalSend;
    console.log('OTP probe stopped; fetch and XHR restored.');
  };

  window.__otpProbe = { report, stop, lines, groups, watched };

  console.log('--- recording ---');
  console.log(
    'Now tap the OTP autofill suggestion on the keyboard exactly as you normally '
    + 'would, then run __otpProbe.report() here. __otpProbe.stop() when done.'
  );
})();
