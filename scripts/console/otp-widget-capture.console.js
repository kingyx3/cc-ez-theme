/*
 * Paste into the browser console on the live OTP step to capture the platform
 * widget's real markup.
 *
 * Why this exists. The one-time-code step at /account/auth is rendered by
 * EasyStore, not by this theme, and the widget posts its own verification over
 * fetch. Autofill on Android drops all six digits into one cell instead of
 * spreading them, and the theme cannot fix that blind: PR #65 and PR #66 tried,
 * wrote into the cells, dispatched input and change events, and each synthetic
 * event drove the widget's submit path. Verification posted twice, the second
 * call came back "Customer already exists (phone)", and signup broke for every
 * new customer. b228492 reverted it and recorded what was missing - the widget's
 * real markup. This script is how that gets collected.
 *
 * It only reads. It never sets a value, never dispatches an event, never adds a
 * listener, and never removes a node. Running it during a real signup is safe.
 *
 * The one question that decides the fix is whether the cells are controlled by a
 * framework. A plain DOM widget reads input.value when you press Verify, so the
 * digits can be written with no events at all and nothing double-posts. A React
 * or Vue widget keeps its own state, ignores a written value, and is the case
 * that caused the outage. Those are opposite fixes, so the answer is printed
 * first and repeated in the verdict.
 *
 * How to run it
 *   1. On the phone that shows the problem, open the signup flow and get to the
 *      six-cell code step. Use remote debugging (chrome://inspect) so there is a
 *      console, or run it on a desktop browser at the same step.
 *   2. Paste this in and run it BEFORE touching the autofill suggestion.
 *   3. Tap the autofill suggestion, then run it a second time.
 *   4. Copy both JSON blobs it prints.
 *
 * Two runs matter because the second shows where the digits actually landed and
 * how the widget reacted, which is what tells us how to spread them.
 */
(() => {
  const out = (label, value) => console.log(String(label).padEnd(28), value);
  const text = (element) => ((element && element.textContent) || '').replace(/\s+/g, ' ').trim();

  // A run of short single-character inputs is the widget, whether or not a form
  // wraps it. Matching on structure avoids guessing at names the platform may
  // change, and the deny list keeps ordinary short fields out.
  const DENY = /(country|postal|zip|discount|coupon|search|quantity|qty)/i;

  const isCandidate = (input) => {
    const type = (input.getAttribute('type') || 'text').toLowerCase();
    if (['hidden', 'submit', 'button', 'checkbox', 'radio', 'file'].includes(type)) return false;
    if (input.disabled) return false;
    const name = (input.getAttribute('name') || '') + ' ' + (input.id || '');
    if (DENY.test(name)) return false;
    const max = Number(input.getAttribute('maxlength'));
    // Either a genuine one-character cell, or a cell wide enough for a whole
    // code - the second is what an autofill-into-one-cell widget looks like.
    return (max >= 1 && max <= 8) || input.getAttribute('autocomplete') === 'one-time-code';
  };

  // Framework-controlled nodes carry their internals as own properties. React
  // uses a hashed suffix, so the keys are matched by prefix.
  const frameworkOf = (node) => {
    const keys = Object.keys(node);
    const react = keys.filter((key) => key.startsWith('__react'));
    if (react.length) return { name: 'react', keys: react };
    if (node.__vue__ || node.__vue_app__ || node.__vnode) return { name: 'vue', keys: ['__vue__'] };
    if (node.__svelte_meta) return { name: 'svelte', keys: ['__svelte_meta'] };
    const ng = keys.filter((key) => key.startsWith('__ng'));
    if (ng.length) return { name: 'angular', keys: ng };
    return { name: 'none', keys: [] };
  };

  // A stable way to point at the container later, without depending on classes
  // the platform may regenerate on every build.
  const pathOf = (node) => {
    const parts = [];
    for (let cursor = node; cursor && cursor.nodeType === 1 && parts.length < 6; cursor = cursor.parentElement) {
      let part = cursor.tagName.toLowerCase();
      if (cursor.id) {
        parts.unshift(part + '#' + cursor.id);
        break;
      }
      const cls = (cursor.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 2);
      if (cls.length) part += '.' + cls.join('.');
      parts.unshift(part);
    }
    return parts.join(' > ');
  };

  const describe = (input, index) => {
    const framework = frameworkOf(input);
    return {
      index,
      tag: input.tagName.toLowerCase(),
      type: input.getAttribute('type') || '(none)',
      name: input.getAttribute('name') || '(none)',
      id: input.id || '(none)',
      className: input.getAttribute('class') || '(none)',
      maxlength: input.getAttribute('maxlength') || '(none)',
      inputmode: input.getAttribute('inputmode') || '(none)',
      autocomplete: input.getAttribute('autocomplete') || '(none)',
      pattern: input.getAttribute('pattern') || '(none)',
      readOnly: input.readOnly,
      // The value itself is a live secret, so only its shape is reported.
      valueLength: input.value.length,
      valueIsDigits: /^\d*$/.test(input.value),
      focused: document.activeElement === input,
      framework: framework.name,
      frameworkKeys: framework.keys,
    };
  };

  console.log('--- page ---');
  out('path', location.pathname + location.hash);
  out('title', document.title);

  const candidates = Array.from(document.querySelectorAll('input')).filter(isCandidate);

  if (candidates.length < 2) {
    console.log(
      'NO CELL RUN FOUND: this does not look like the six-cell code step. Get to '
      + 'the screen that shows the code boxes and run this again.'
    );
    out('inputs on page', document.querySelectorAll('input').length);
    return;
  }

  // Cells that belong together share a parent. Group by it and take the largest
  // group, so an unrelated short field elsewhere cannot pad the count.
  const groups = new Map();
  candidates.forEach((input) => {
    const parent = input.parentElement && input.parentElement.parentElement === null
      ? input.parentElement
      : (input.parentElement || document.body);
    // Climb one level when each cell sits in its own wrapper, which is common.
    const key = candidates.filter((other) => other.parentElement === parent).length > 1
      ? parent
      : (parent.parentElement || parent);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(input);
  });

  let container = null;
  let cells = [];
  groups.forEach((members, key) => {
    if (members.length > cells.length) {
      cells = members;
      container = key;
    }
  });

  const form = cells[0].closest('form');
  const containerFramework = frameworkOf(container);

  console.log('--- the decisive question ---');
  const cellFrameworks = Array.from(new Set(cells.map((cell) => frameworkOf(cell).name)));
  out('cells controlled by', cellFrameworks.join(', '));
  out('container controlled by', containerFramework.name);

  console.log('--- cells ---');
  out('count', cells.length);
  out('container path', pathOf(container));
  out('inside a form', form ? 'yes — action ' + (form.getAttribute('action') || '(none)') : 'no');
  const rows = cells.map(describe);
  console.table(rows);

  console.log('--- submit control ---');
  const buttons = Array.from((form || container.parentElement || document).querySelectorAll(
    'button, input[type="submit"], [role="button"]'
  )).filter((node) => node.offsetParent !== null);
  if (!buttons.length) out('visible buttons', '(none — the widget likely auto-submits)');
  buttons.slice(0, 6).forEach((node) => out(
    node.tagName.toLowerCase() + (node.getAttribute('type') ? '[' + node.getAttribute('type') + ']' : ''),
    JSON.stringify(text(node) || node.value || '(no label)')
  ));

  // The widget's own bundle is where the distribution behaviour lives. Naming
  // the files lets the handler be read directly instead of inferred.
  console.log('--- scripts on the page ---');
  const scripts = Array.from(document.querySelectorAll('script[src]'))
    .map((node) => node.src)
    .filter((src) => !/googletagmanager|google-analytics|facebook|hotjar|tiktok|clarity/i.test(src));
  scripts.forEach((src) => out('script', src));

  console.log('--- theme scripts present ---');
  const html = document.documentElement.outerHTML;
  out('account-otp-copy.js', /account-otp-copy\.js/.test(html));
  // If this is ever true the outage has been re-introduced.
  out('otp-cell-autofill.js', /otp-cell-autofill\.js/.test(html)
    ? 'PRESENT — this is the reverted module, it must not be deployed'
    : false);

  console.log('--- verdict ---');
  const filled = rows.filter((row) => row.valueLength > 0);
  const overfilled = rows.filter((row) => row.valueLength > 1);
  if (overfilled.length) {
    console.log(
      'AUTOFILL LANDED IN ONE CELL: cell ' + overfilled[0].index + ' holds '
      + overfilled[0].valueLength + ' characters while ' + (cells.length - filled.length)
      + ' cells are still empty. That is the reported bug, captured.'
    );
  } else if (filled.length === cells.length) {
    console.log('ALL CELLS FILLED: autofill spread correctly on this run.');
  } else {
    console.log(
      'CELLS EMPTY: this is the before-autofill run. Tap the autofill suggestion '
      + 'and run this again to capture where the digits land.'
    );
  }

  if (cellFrameworks.some((name) => name !== 'none')) {
    console.log(
      'FRAMEWORK-CONTROLLED (' + cellFrameworks.join(', ') + '): the widget keeps its own '
      + 'state, so a written value alone is ignored and events are required to make '
      + 'it stick. Events are exactly what double-posted the verification in PR #66. '
      + 'Do not write a theme-side fix on this evidence — the handler in the bundle '
      + 'above has to be read first, or the fix belongs with EasyStore support.'
    );
  } else {
    console.log(
      'PLAIN DOM CELLS: no framework state is attached, so the widget reads '
      + 'input.value when it posts. Spreading the digits by assignment with NO '
      + 'dispatched events would then be visible to the widget without driving '
      + 'its submit path, which is the mechanism that broke signup. Confirm '
      + 'against the bundle above before shipping anything.'
    );
  }

  const report = {
    capturedPath: location.pathname,
    cellCount: cells.length,
    containerPath: pathOf(container),
    insideForm: Boolean(form),
    formAction: form ? form.getAttribute('action') : null,
    cellFrameworks,
    containerFramework: containerFramework.name,
    cells: rows,
    buttons: buttons.slice(0, 6).map((node) => text(node) || node.value || ''),
    scripts,
  };
  console.log('--- copy everything below this line ---');
  console.log(JSON.stringify(report, null, 2));
})();
