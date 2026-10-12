const AxeBuilder = require('@axe-core/playwright').default;
const { test, expect } = require('./fixtures');
const { gotoStorefront, openLimitedProduct } = require('./storefront-helpers');

// A page is either a fixed path or a helper that opens one, because which
// product carries a purchase limit is theme configuration rather than a
// literal this suite should keep in step.
const pages = [
  ['home', '/'],
  ['collection', '/collections/the-hobbit'],
  ['product', openLimitedProduct],
  ['search', '/search?q=Hobbit'],
  ['cart', '/cart'],
  ['login', '/account/login'],
];

const knownNodeTargets = {
  'html-has-lang': new Set(['html']),
  'link-name': new Set(['.p-2', '#cart-icon-bubble']),
  'button-name': new Set(['button[name="minus"]', 'button[name="plus"]']),
};

function targetKey(node) {
  return Array.isArray(node.target) ? node.target.join(' > ') : String(node.target || '');
}

function splitKnownAccessibilityBaseline(violations) {
  const known = [];
  const unexpected = [];

  for (const violation of violations) {
    const allowedTargets = knownNodeTargets[violation.id];
    if (!allowedTargets) {
      unexpected.push(violation);
      continue;
    }

    const knownNodes = violation.nodes.filter(node => allowedTargets.has(targetKey(node)));
    const unexpectedNodes = violation.nodes.filter(node => !allowedTargets.has(targetKey(node)));

    if (knownNodes.length) known.push({ ...violation, nodes: knownNodes });
    if (unexpectedNodes.length) unexpected.push({ ...violation, nodes: unexpectedNodes });
  }

  return { known, unexpected };
}

for (const [name, path] of pages) {
  test(`${name} has no unexpected serious or critical automated accessibility violations`, async ({ page }, testInfo) => {
    if (typeof path === 'function') {
      await path(page);
    } else {
      await gotoStorefront(page, path);
    }
    const results = await new AxeBuilder({ page }).analyze();
    const severe = results.violations.filter(v => v.impact === 'serious' || v.impact === 'critical');
    const { known, unexpected } = splitKnownAccessibilityBaseline(severe);

    if (known.length) {
      await testInfo.attach(`axe-known-baseline-${name}.json`, {
        body: Buffer.from(JSON.stringify(known, null, 2)),
        contentType: 'application/json',
      });
    }
    if (unexpected.length) {
      await testInfo.attach(`axe-unexpected-${name}.json`, {
        body: Buffer.from(JSON.stringify(unexpected, null, 2)),
        contentType: 'application/json',
      });
    }

    expect(unexpected).toEqual([]);
  });
}
