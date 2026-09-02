const fs = require('fs');
const path = require('path');
const { test, expect } = require('@playwright/test');
const {
  createAuthenticatedStorageState,
  expectFullyAuthenticated,
  requireTestCredentials,
} = require('./auth-helpers');

const OUTPUT_DIR = process.env.AUTH_PERF_RESULTS_DIR
  ? path.resolve(process.env.AUTH_PERF_RESULTS_DIR)
  : path.join(process.cwd(), 'authenticated-performance-results');
const SAMPLE_COUNT = Math.max(1, Number.parseInt(process.env.AUTH_PERF_RUNS || '3', 10) || 3);
const SETTLE_MS = Math.max(0, Number.parseInt(process.env.AUTH_PERF_SETTLE_MS || '350', 10) || 350);

const BUDGETS = {
  ttfbP50Ms: Number(process.env.AUTH_PERF_MAX_TTFB_P50_MS || 4000),
  loadP50Ms: Number(process.env.AUTH_PERF_MAX_LOAD_P50_MS || 12000),
  lcpP50Ms: Number(process.env.AUTH_PERF_MAX_LCP_P50_MS || 8000),
  clsP95: Number(process.env.AUTH_PERF_MAX_CLS_P95 || 0.35),
  longTaskP50Ms: Number(process.env.AUTH_PERF_MAX_LONG_TASK_P50_MS || 3000),
};

function quantile(values, ratio) {
  const numeric = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!numeric.length) return null;
  const index = Math.min(numeric.length - 1, Math.ceil(ratio * numeric.length) - 1);
  return numeric[Math.max(0, index)];
}

function round(value, digits = 1) {
  return Number.isFinite(value) ? Number(value.toFixed(digits)) : null;
}

function summarize(samples) {
  const successful = samples.filter(sample => !sample.error);
  const metricKeys = [
    'wallMs',
    'ttfbMs',
    'domContentLoadedMs',
    'loadMs',
    'fcpMs',
    'lcpMs',
    'cls',
    'longTaskTotalMs',
    'maxLongTaskMs',
    'requestCount',
    'serverErrorCount',
    'transferBytes',
    'jsTransferBytes',
    'cssTransferBytes',
  ];

  const p50 = {};
  const p95 = {};
  for (const key of metricKeys) {
    const values = successful.map(sample => sample[key]);
    p50[key] = round(quantile(values, 0.5));
    p95[key] = round(quantile(values, 0.95));
  }

  return {
    sampleCount: samples.length,
    successfulSamples: successful.length,
    errorCount: samples.length - successful.length,
    statusCodes: [...new Set(successful.map(sample => sample.status).filter(Number.isFinite))],
    p50,
    p95,
  };
}

async function installObservers(page) {
  await page.addInitScript(() => {
    window.__ccAuthenticatedPerformance = {
      lcpMs: 0,
      cls: 0,
      longTaskTotalMs: 0,
      maxLongTaskMs: 0,
    };

    try {
      new PerformanceObserver(list => {
        const entries = list.getEntries();
        const last = entries[entries.length - 1];
        if (last) window.__ccAuthenticatedPerformance.lcpMs = last.startTime;
      }).observe({ type: 'largest-contentful-paint', buffered: true });
    } catch (_) {}

    try {
      new PerformanceObserver(list => {
        for (const entry of list.getEntries()) {
          if (!entry.hadRecentInput) window.__ccAuthenticatedPerformance.cls += entry.value;
        }
      }).observe({ type: 'layout-shift', buffered: true });
    } catch (_) {}

    try {
      new PerformanceObserver(list => {
        for (const entry of list.getEntries()) {
          window.__ccAuthenticatedPerformance.longTaskTotalMs += entry.duration;
          window.__ccAuthenticatedPerformance.maxLongTaskMs = Math.max(
            window.__ccAuthenticatedPerformance.maxLongTaskMs,
            entry.duration
          );
        }
      }).observe({ type: 'longtask', buffered: true });
    } catch (_) {}
  });
}

async function readMetrics(page, response, wallMs, serverErrorCount) {
  return page.evaluate(({ status, measuredWallMs, measuredServerErrors }) => {
    const navigation = performance.getEntriesByType('navigation')[0];
    const resources = performance.getEntriesByType('resource');
    const fcp = performance.getEntriesByName('first-contentful-paint')[0];
    const observed = window.__ccAuthenticatedPerformance || {};

    const transferBytes = resources.reduce((sum, entry) => sum + (entry.transferSize || 0), 0);
    const jsTransferBytes = resources
      .filter(entry => entry.initiatorType === 'script' || /\.m?js(?:[?#]|$)/i.test(entry.name))
      .reduce((sum, entry) => sum + (entry.transferSize || 0), 0);
    const cssTransferBytes = resources
      .filter(entry => entry.initiatorType === 'css' || /\.css(?:[?#]|$)/i.test(entry.name))
      .reduce((sum, entry) => sum + (entry.transferSize || 0), 0);

    return {
      route: location.pathname,
      status,
      wallMs: measuredWallMs,
      ttfbMs: navigation ? navigation.responseStart - navigation.requestStart : null,
      domContentLoadedMs: navigation
        ? navigation.domContentLoadedEventEnd - navigation.startTime
        : null,
      loadMs: navigation ? navigation.loadEventEnd - navigation.startTime : null,
      fcpMs: fcp?.startTime || null,
      lcpMs: observed.lcpMs || null,
      cls: observed.cls || 0,
      longTaskTotalMs: observed.longTaskTotalMs || 0,
      maxLongTaskMs: observed.maxLongTaskMs || 0,
      requestCount: resources.length + 1,
      serverErrorCount: measuredServerErrors,
      transferBytes: transferBytes + (navigation?.transferSize || 0),
      jsTransferBytes,
      cssTransferBytes,
    };
  }, {
    status: response?.status() ?? null,
    measuredWallMs: wallMs,
    measuredServerErrors: serverErrorCount,
  });
}

async function measureNavigation(page, route) {
  let serverErrorCount = 0;
  const onResponse = response => {
    if (response.status() >= 500) serverErrorCount += 1;
  };
  page.on('response', onResponse);

  try {
    const started = Date.now();
    const response = await page.goto(route, { waitUntil: 'load', timeout: 30_000 });
    const wallMs = Date.now() - started;
    expect(response, `${route} should return a navigation response`).not.toBeNull();
    expect(response.status(), `${route} should not return an HTTP error`).toBeLessThan(400);
    if (SETTLE_MS) await page.waitForTimeout(SETTLE_MS);
    await expectFullyAuthenticated(page, route);
    return readMetrics(page, response, wallMs, serverErrorCount);
  } finally {
    page.off('response', onResponse);
  }
}

async function coldSamples(browser, baseURL, storageState, route) {
  const samples = [];
  for (let index = 0; index < SAMPLE_COUNT; index += 1) {
    const context = await browser.newContext({ baseURL, storageState });
    const page = await context.newPage();
    await installObservers(page);
    try {
      samples.push(await measureNavigation(page, route));
    } catch (error) {
      samples.push({ route, error: error instanceof Error ? error.message : String(error) });
    } finally {
      await context.close();
    }
  }
  return samples;
}

async function warmSamples(browser, baseURL, storageState, route) {
  const context = await browser.newContext({ baseURL, storageState });
  const page = await context.newPage();
  await installObservers(page);
  const samples = [];

  try {
    // Prime the isolated authenticated context once; recorded navigations after
    // this point can reuse the browser HTTP cache but not another test's cache.
    await measureNavigation(page, route);
    for (let index = 0; index < SAMPLE_COUNT; index += 1) {
      try {
        samples.push(await measureNavigation(page, route));
      } catch (error) {
        samples.push({ route, error: error instanceof Error ? error.message : String(error) });
      }
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    while (samples.length < SAMPLE_COUNT) samples.push({ route, error: message });
  } finally {
    await context.close();
  }

  return samples;
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

function budgetStatus(summary) {
  if (summary.errorCount) return 'FAIL (sample error)';
  const failures = [];
  if (Number.isFinite(summary.p50.ttfbMs) && summary.p50.ttfbMs > BUDGETS.ttfbP50Ms) failures.push('TTFB');
  if (Number.isFinite(summary.p50.loadMs) && summary.p50.loadMs > BUDGETS.loadP50Ms) failures.push('Load');
  if (Number.isFinite(summary.p50.lcpMs) && summary.p50.lcpMs > BUDGETS.lcpP50Ms) failures.push('LCP');
  if (Number.isFinite(summary.p95.cls) && summary.p95.cls > BUDGETS.clsP95) failures.push('CLS');
  if (Number.isFinite(summary.p50.longTaskTotalMs) && summary.p50.longTaskTotalMs > BUDGETS.longTaskP50Ms) failures.push('Long tasks');
  return failures.length ? `FAIL (${failures.join(', ')})` : 'PASS';
}

function markdownSummary(report) {
  const lines = [
    '# Authenticated account performance',
    '',
    `Target: \`${report.baseURL}\`  `,
    `Recorded: ${report.recordedAt}  `,
    `Commit: \`${report.git.sha || 'local'}\`  `,
    `Samples: ${report.sampleCount} cold + ${report.sampleCount} warm per protected route`,
    '',
    '> Authentication state is held in memory only. This artifact contains route names and numeric measurements, never cookies, passwords, or account content.',
    '',
    '| Route | Cache | Result | Success | TTFB p50 | Load p50 | FCP p50 | LCP p50 | CLS p95 | Long tasks p50 | Requests p50 | Transfer p50 |',
    '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |',
  ];

  for (const scenario of report.scenarios) {
    for (const cache of ['cold', 'warm']) {
      const summary = scenario[cache].summary;
      const p50 = summary.p50;
      lines.push(
        `| ${scenario.route} | ${cache} | ${budgetStatus(summary)} | ${summary.successfulSamples}/${summary.sampleCount} | ` +
        `${formatMs(p50.ttfbMs)} | ${formatMs(p50.loadMs)} | ${formatMs(p50.fcpMs)} | ` +
        `${formatMs(p50.lcpMs)} | ${formatNumber(summary.p95.cls)} | ` +
        `${formatMs(p50.longTaskTotalMs)} | ${Number.isFinite(p50.requestCount) ? Math.round(p50.requestCount) : '—'} | ` +
        `${formatKiB(p50.transferBytes)} |`
      );
    }
  }

  lines.push(
    '',
    'Guardrails (environment variables can override these defaults):',
    `- TTFB p50 ≤ ${BUDGETS.ttfbP50Ms} ms`,
    `- Load p50 ≤ ${BUDGETS.loadP50Ms} ms`,
    `- LCP p50 ≤ ${BUDGETS.lcpP50Ms} ms`,
    `- CLS p95 ≤ ${BUDGETS.clsP95}`,
    `- Long-task total p50 ≤ ${BUDGETS.longTaskP50Ms} ms`,
    '- Every sample must remain authenticated, return <400, and complete without a 5xx navigation.',
    ''
  );

  return `${lines.join('\n')}\n`;
}

function assertSummaryWithinBudgets(route, cache, summary) {
  expect(summary.errorCount, `${route} ${cache} should have no failed authenticated samples`).toBe(0);
  expect(summary.successfulSamples, `${route} ${cache} should record every configured sample`).toBe(SAMPLE_COUNT);
  expect(summary.p50.serverErrorCount || 0, `${route} ${cache} should not observe 5xx resources`).toBe(0);

  if (Number.isFinite(summary.p50.ttfbMs)) {
    expect(summary.p50.ttfbMs, `${route} ${cache} TTFB p50 budget`).toBeLessThanOrEqual(BUDGETS.ttfbP50Ms);
  }
  if (Number.isFinite(summary.p50.loadMs)) {
    expect(summary.p50.loadMs, `${route} ${cache} load p50 budget`).toBeLessThanOrEqual(BUDGETS.loadP50Ms);
  }
  if (Number.isFinite(summary.p50.lcpMs)) {
    expect(summary.p50.lcpMs, `${route} ${cache} LCP p50 budget`).toBeLessThanOrEqual(BUDGETS.lcpP50Ms);
  }
  if (Number.isFinite(summary.p95.cls)) {
    expect(summary.p95.cls, `${route} ${cache} CLS p95 budget`).toBeLessThanOrEqual(BUDGETS.clsP95);
  }
  if (Number.isFinite(summary.p50.longTaskTotalMs)) {
    expect(summary.p50.longTaskTotalMs, `${route} ${cache} long-task p50 budget`).toBeLessThanOrEqual(BUDGETS.longTaskP50Ms);
  }
}

test.describe('authenticated account performance', () => {
  test('records cold and warm protected-page metrics with guardrails', async ({ browser, baseURL, browserName }) => {
    test.skip(browserName !== 'chromium', 'Authenticated performance is normalized on Chromium.');
    test.setTimeout(300_000);
    requireTestCredentials();

    const normalizedBaseURL = new URL(baseURL || 'https://cardboard.sg').href;
    const storageState = await createAuthenticatedStorageState(browser, normalizedBaseURL);
    const routes = ['/account', '/account/orders', '/account/details', '/account/addresses'];
    const scenarios = [];

    for (const route of routes) {
      const cold = await coldSamples(browser, normalizedBaseURL, storageState, route);
      const warm = await warmSamples(browser, normalizedBaseURL, storageState, route);
      scenarios.push({
        route,
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
      budgets: BUDGETS,
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
    fs.writeFileSync(path.join(OUTPUT_DIR, 'metrics.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8');
    fs.writeFileSync(path.join(OUTPUT_DIR, 'summary.md'), markdownSummary(report), 'utf8');
    console.log(markdownSummary(report));

    // Write the complete observation first so a budget failure still leaves a
    // useful artifact showing exactly which route/cache mode regressed.
    for (const scenario of scenarios) {
      assertSummaryWithinBudgets(scenario.route, 'cold', scenario.cold.summary);
      assertSummaryWithinBudgets(scenario.route, 'warm', scenario.warm.summary);
    }
  });
});
