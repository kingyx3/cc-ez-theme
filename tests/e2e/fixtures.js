const { test: base, expect } = require('@playwright/test');

const guardedResourceTypes = new Set(['stylesheet', 'script', 'image', 'font']);

function errorTouchesOrigin(error, origin) {
  const urls = (error.stack || '').match(/https?:\/\/[^\s)]+/g) || [];
  if (!urls.length) return true;

  return urls.some(value => {
    try {
      return new URL(value).origin === origin;
    } catch {
      return true;
    }
  });
}

function currentPath(currentUrl) {
  try {
    return new URL(currentUrl).pathname;
  } catch {
    return '';
  }
}

function isCheckoutOrAuthPath(pathname) {
  return pathname === '/cart'
    || pathname.startsWith('/checkout')
    || pathname.startsWith('/account/login');
}

function isKnownBrowserTransitionError(error, currentUrl, origin, browserName) {
  const message = error.message || '';
  const pathname = currentPath(currentUrl);

  if (browserName === 'webkit') {
    if (
      /accessing a frame with origin/i.test(message)
      && /Protocols, domains, and ports must match/i.test(message)
    ) {
      const messageUrls = message.match(/https?:\/\/[^"'\s)]+/g) || [];
      const hasExternalOrigin = messageUrls.some(value => {
        try {
          return new URL(value).origin !== origin;
        } catch {
          return false;
        }
      });
      if (hasExternalOrigin) return true;
    }

    if (message === 'TypeError: Load failed' && isCheckoutOrAuthPath(pathname)) {
      return true;
    }
  }

  if (
    browserName === 'firefox'
    && message === 'NetworkError when attempting to fetch resource.'
    && isCheckoutOrAuthPath(pathname)
  ) {
    return true;
  }

  return false;
}

function isKnownPlatformPageError(error, currentUrl, origin) {
  const pathname = currentPath(currentUrl);
  if (pathname !== '/cart') return false;

  if (error.message === 'cookies is not defined') {
    return true;
  }

  if (error.message !== "Cannot read properties of null (reading 'items')") return false;

  const stack = error.stack || '';
  const escapedOrigin = origin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const getCartFrame = new RegExp(`at getCart \\(${escapedOrigin}/cart:\\d+:\\d+\\)`);
  const onCartViewFrame = new RegExp(`at async onCartView \\(${escapedOrigin}/cart:\\d+:\\d+\\)`);
  return getCartFrame.test(stack) && onCartViewFrame.test(stack);
}

const test = base.extend({
  page: async ({ page, baseURL, browserName }, use, testInfo) => {
    const pageErrors = [];
    const knownPlatformErrors = [];
    const badSameOriginResources = [];
    const origin = new URL(baseURL).origin;

    page.on('pageerror', error => {
      if (isKnownBrowserTransitionError(error, page.url(), origin, browserName)) {
        knownPlatformErrors.push(error.message);
        return;
      }
      if (!errorTouchesOrigin(error, origin)) return;
      if (isKnownPlatformPageError(error, page.url(), origin)) {
        knownPlatformErrors.push(error.message);
        return;
      }
      pageErrors.push(error.message);
    });
    page.on('response', response => {
      const request = response.request();
      if (!guardedResourceTypes.has(request.resourceType())) return;
      if (response.status() < 400) return;
      try {
        if (new URL(response.url()).origin !== origin) return;
      } catch {
        return;
      }
      badSameOriginResources.push(`${response.status()} ${request.resourceType()} ${response.url()}`);
    });

    await use(page);

    if (knownPlatformErrors.length) {
      await testInfo.attach('known-platform-page-errors.txt', {
        body: Buffer.from(knownPlatformErrors.join('\n')),
        contentType: 'text/plain',
      });
    }
    if (pageErrors.length) {
      await testInfo.attach('page-errors.txt', {
        body: Buffer.from(pageErrors.join('\n')),
        contentType: 'text/plain',
      });
    }
    if (badSameOriginResources.length) {
      await testInfo.attach('bad-resources.txt', {
        body: Buffer.from(badSameOriginResources.join('\n')),
        contentType: 'text/plain',
      });
    }

    expect.soft(pageErrors, 'uncaught same-origin browser errors').toEqual([]);
    expect.soft(badSameOriginResources, 'same-origin resources returning HTTP 4xx/5xx').toEqual([]);
  },
});

module.exports = { test, expect };
