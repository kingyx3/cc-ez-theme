const AxeBuilder = require('@axe-core/playwright').default;
const { test, expect } = require('./fixtures');
const { gotoStorefront, limitedProductPath } = require('./storefront-helpers');

const pages = [
  ['home', '/'],
  ['collection', '/collections/the-hobbit'],
  ['product', limitedProductPath],
  ['search', '/search?q=Hobbit'],
  ['cart', '/cart'],
  ['login', '/account/login'],
];

for (const [name, path] of pages) {
  test(`${name} has no serious or critical automated accessibility violations`, async ({ page }, testInfo) => {
    await gotoStorefront(page, path);
    const results = await new AxeBuilder({ page }).analyze();
    const severe = results.violations.filter(v => v.impact === 'serious' || v.impact === 'critical');

    if (severe.length) {
      await testInfo.attach(`axe-${name}.json`, {
        body: Buffer.from(JSON.stringify(severe, null, 2)),
        contentType: 'application/json',
      });
    }

    expect(severe).toEqual([]);
  });
}
