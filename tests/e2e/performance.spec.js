const fs = require('fs');
const path = require('path');
const { test } = require('@playwright/test');
const { configuredLimitHandles } = require('./storefront-helpers');

const OUTPUT_DIR = process.env.PERF_RESULTS_DIR
  ? path.resolve(process.env.PERF_RESULTS_DIR)
  : path.join(process.cwd(), 'performance-results');
const SAMPLE_COUNT = Math.max(1, Number.parseInt(process.env.PERF_RUNS || '3', 10) || 3);
const SETTLE_MS = Math.max(0, Number.parseInt(process.env.PERF_SETTLE_MS || '350', 10) || 350);

function median(values) {
  const numeric = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!numeric.length) return null;
  const middle = Math.floor(numeric.length / 2);
  return numeric.length % 2 ? numeric[middle] : (numeric[middle - 1] + numeric[middle]) / 2;
}

function round(value, digits = 1) {
  return Number.isFinite(value) ? Number(value.toFixed(digits)) : null;
}

function summarize(samples) {
  const successful = samples.filter(sample => !sample.error);
  const metricKeys = [
    'wallMs',
    'ttfbMs',
    'responseStartMs',
    'domContentLoadedMs',
    'loadMs',
    'lcpMs',
    'cls',
    'longTaskTotalMs',
    'maxLongTaskMs',
    'requestCount',
    'transferBytes',
    'jsTransferBytes',
    'cssTransferBytes',
  ];

  const medians = {};
  for (const key of metricKeys) {
    medians[key] = round(median(successful.map(sample => sample[key])));
  }

  return {
    sampleCount: samples.length,
    successfulSamples: successful.length,
    errorCount: samples.length - successful.length,
    statusCodes: [...new Set(successful.map(sample => sample.status).filter(Number.isFinite))],
    medians,
  };
}

async function installObservers(page) {
  await page.addInitScript(() => {
    window.__ccPerformance = {
      lcpMs: 0,
      cls: 0,
      longTaskTotalMs: 0,
      maxLongTaskMs: 0,
      longTaskCount: 0,
    };

    try {
      new PerformanceObserver(list => {
        const entries = list.getEntries();
        const last = entries[entries.length - 1];
        if (last) window.__ccPerformance.lcpMs = last.startTime;
      }).observe({ type: 'largest-contentful-paint', buffered: true });
    } catch (_) {}

    try {
      new PerformanceObserver(list => {
        for (const entry of list.getEntries()) {
          if (!entry.hadRecentInput) window.__ccPerformance.cls += entry.value;
        }
      }).observe({ type: 'layout-shift', buffered: true });
    } catch (_) {}

    try {
      new PerformanceObserver(list => {
        for (const entry of list.getEntries()) {
          window.__ccPerformance.longTaskCount += 1;
          window.__ccPerformance.longTaskTotalMs += entry.duration;
          window.__ccPerformance.maxLongTaskMs = Math.max(
            window.__ccPerformance.maxLongTaskMs,
            entry.duration
          );
        }
      }).observe({ type: 'longtask', buffered: true });
    } catch (_) {}
  });
}

async function readPageMetrics(page, response, wallMs) {
  return page.evaluate(({ status, measuredWallMs }) => {
    const navigation = performance.getEntriesByType('navigation')[0];
    const resources = performance.getEntriesByType('resource');
    const observed = window.__ccPerformance || {};

    const transferBytes = resources.reduce((sum, entry) => sum + (entry.transferSize || 0), 0);
    const jsTransferBytes = resources
      .filter(entry => entry.initiatorType === 'script' || /\.m?js(?:[?#]|$)/i.test(entry.name))
      .reduce((sum, entry) => sum + (entry.transferSize || 0), 0);
    const cssTransferBytes = resources
      .filter(entry => entry.initiatorType === 'css' || /\.css(?:[?#]|$)/i.test(entry.name))
      .reduce((sum, entry) => sum + (entry.transferSize || 0), 0);

    return {
      url: location.href,
      status,
      wallMs: measuredWallMs,
      ttfbMs: navigation ? navigation.responseStart - navigation.requestStart : null,
      responseStartMs: navigation ? navigation.responseStart - navigation.startTime : null,
      domContentLoadedMs: navigation
        ? navigation.domContentLoadedEventEnd - navigation.startTime
        : null,
      loadMs: navigation ? navigation.loadEventEnd - navigation.startTime : null,
      documentTransferBytes: navigation?.transferSize || 0,
      lcpMs: observed.lcpMs || null,
      cls: observed.cls || 0,
      longTaskTotalMs: observed.longTaskTotalMs || 0,
      maxLongTaskMs: observed.maxLongTaskMs || 0,
      longTaskCount: observed.longTaskCount || 0,
      requestCount: resources.length + 1,
      transferBytes: transferBytes + (navigation?.transferSize || 0),
      jsTransferBytes,
      cssTransferBytes,
    };
  }, { status: response?.status() ?? null, measuredWallMs: wallMs });
}

async function measureNavigation(page, target) {
  const start = Date.now();
  const response = await page.goto(target, { waitUntil: 'load', timeout: 30_000 });
  const wallMs = Date.now() - start;
  if (SETTLE_MS) await page.waitForTimeout(SETTLE_MS);
  return readPageMetrics(page, response, wallMs);
}

async function coldSample(browser, target) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await installObservers(page);

  try {
    return await measureNavigation(page, target);
  } catch (error) {
    return { url: target, error: error instanceof Error ? error.message : String(error) };
  } finally {
    await context.close();
  }
}

async function warmSamples(browser, target) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await installObservers(page);
  const samples = [];

  try {
    // Prime this isolated context once so subsequent navigations can reuse the
    // browser HTTP cache. The priming load is intentionally not recorded.
    await measureNavigation(page, target);

    for (let index = 0; index < SAMPLE_COUNT; index += 1) {
      try {
        samples.push(await measureNavigation(page, target));
      } catch (error) {
        samples.push({ url: target, error: error instanceof Error ? error.message : String(error) });
      }
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    while (samples.length < SAMPLE_COUNT) samples.push({ url: target, error: message });
  } finally {
    await context.close();
  }

  return samples;
}

async function discoverProductPath(browser, baseURL) {
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    await page.goto(new URL('/collections/the-hobbit', baseURL).href, {
      waitUntil: 'domcontentloaded',
      timeout: 30_000,
    });
    const href = await page.locator('a[href*="/products/"]').evaluateAll(nodes => {
      const match = nodes
        .map(node => node.getAttribute('href'))
        .find(value => typeof value === 'string' && value.includes('/products/'));
      return match || null;
    });
    if (href) {
      const productURL = new URL(href, baseURL);
      return productURL.pathname + productURL.search;
    }
  } catch (_) {
    // Fall back to the theme's first configured limited-product handle below.
  } finally {
    await context.close();
  }

  const configured = configuredLimitHandles();
  return configured.length ? `/products/${configured[0]}` : null;
}

function formatMs(value) {
  return Number.isFinite(value) ? `${Math.round(value)} ms` : '—';
}

function formatNumber(value, digits = 2) {
  return Number.isFinite(value) ? value.toFixed(digits) : '—';
}

function formatKiB(value) {
  return Number.isFinite(value) ? `${Math.round(value / 1024)} KiB` : '—';
}

function markdownSummary(report) {
  const lines = [
    '# Storefront performance observations',
    '',
    `Target: \`${report.baseURL}\`  `,
    `Recorded: ${report.recordedAt}  `,
    `Commit: \`${report.git.sha || 'local'}\`  `,
    `Samples: ${report.sampleCount} cold + ${report.sampleCount} warm per scenario`,
    '',
    '> These are observational CI measurements, not pass/fail budgets. Compare medians across runs to spot trends; hosted-runner and network variance are expected.',
    '',
    '| Scenario | Cache | Success | TTFB | DCL | Load | LCP | CLS | Long tasks | Requests | Transfer | JS | CSS |',
    '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |',
  ];

  for (const scenario of report.scenarios) {
    for (const cache of ['cold', 'warm']) {
      const summary = scenario[cache].summary;
      const metrics = summary.medians;
      lines.push(
        `| ${scenario.name} | ${cache} | ${summary.successfulSamples}/${summary.sampleCount} | ` +
        `${formatMs(metrics.ttfbMs)} | ${formatMs(metrics.domContentLoadedMs)} | ` +
        `${formatMs(metrics.loadMs)} | ${formatMs(metrics.lcpMs)} | ` +
        `${formatNumber(metrics.cls)} | ${formatMs(metrics.longTaskTotalMs)} | ` +
        `${Number.isFinite(metrics.requestCount) ? Math.round(metrics.requestCount) : '—'} | ` +
        `${formatKiB(metrics.transferBytes)} | ${formatKiB(metrics.jsTransferBytes)} | ` +
        `${formatKiB(metrics.cssTransferBytes)} |`
      );
    }
  }

  lines.push(
    '',
    'Useful comparisons:',
    '- TTFB: server/rendering wait before the initial response begins.',
    '- LCP: when the largest visible content paints.',
    '- Long tasks: main-thread JavaScript work over 50 ms.',
    '- Transfer/JS/CSS: payload growth or reduction between revisions.',
    '- Cold vs warm: impact of browser caching on repeat navigation.',
    ''
  );

  return `${lines.join('\n')}\n`;
}

test.describe('storefront performance observations', () => {
  test('records non-blocking cold and warm navigation metrics', async ({ browser, baseURL, browserName }) => {
    test.skip(browserName !== 'chromium', 'Performance observations are normalized on Chromium.');
    test.setTimeout(240_000);

    const normalizedBaseURL = new URL(baseURL || 'https://cardboard.sg').href;
    const productPath = await discoverProductPath(browser, normalizedBaseURL);
    const scenarioPaths = [
      ['homepage', '/'],
      ['collection', '/collections/the-hobbit'],
      ...(productPath ? [['product', productPath]] : []),
      ['cart', '/cart'],
      ['account-login', '/account/login'],
    ];

    const scenarios = [];
    for (const [name, route] of scenarioPaths) {
      const target = new URL(route, normalizedBaseURL).href;
      const cold = [];
      for (let index = 0; index < SAMPLE_COUNT; index += 1) {
        cold.push(await coldSample(browser, target));
      }
      const warm = await warmSamples(browser, target);

      scenarios.push({
        name,
        route,
        target,
        cold: { samples: cold, summary: summarize(cold) },
        warm: { samples: warm, summary: summarize(warm) },
      });
    }

    const report = {
      schemaVersion: 1,
      recordedAt: new Date().toISOString(),
      baseURL: normalizedBaseURL,
      sampleCount: SAMPLE_COUNT,
      settleMs: SETTLE_MS,
      git: {
        sha: process.env.GITHUB_SHA || null,
        ref: process.env.GITHUB_REF_NAME || null,
        event: process.env.GITHUB_EVENT_NAME || null,
        runId: process.env.GITHUB_RUN_ID || null,
        runAttempt: process.env.GITHUB_RUN_ATTEMPT || null,
      },
      scenarios,
    };

    fs.mkdirSync(OUTPUT_DIR, { recursive: true });
    fs.writeFileSync(
      path.join(OUTPUT_DIR, 'metrics.json'),
      `${JSON.stringify(report, null, 2)}\n`,
      'utf8'
    );
    fs.writeFileSync(path.join(OUTPUT_DIR, 'summary.md'), markdownSummary(report), 'utf8');

    console.log(markdownSummary(report));
  });
});
