(() => {
  'use strict';

  if (
    typeof window.fetch !== 'function'
    || typeof DOMParser !== 'function'
    || typeof Response !== 'function'
  ) return;

  const nativeFetch = window.fetch.bind(window);
  const HISTORY_PATH = '/account/orders';
  const HISTORY_PAYLOAD_ID = 'customer-order-limit-history';
  const MAX_DETAIL_REQUESTS = 24;
  let detailRequests = 0;

  const quantity = (value, fallback = 0) => {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
  };

  const requestUrl = (input) => {
    try {
      const value = input && typeof input === 'object' && 'url' in input
        ? input.url
        : input;
      return new URL(String(value || ''), window.location.href);
    } catch (_error) {
      return null;
    }
  };

  const isHistoryListRequest = (input) => {
    const url = requestUrl(input);
    return Boolean(
      url
      && url.origin === window.location.origin
      && url.pathname === HISTORY_PATH
    );
  };

  const productHandleFromUrl = (value) => {
    const match = String(value || '').match(/\/products\/([^/?#]+)/i);
    if (!match) return '';
    try {
      return decodeURIComponent(match[1]).trim().toLowerCase();
    } catch (_error) {
      return match[1].trim().toLowerCase();
    }
  };

  const responseWithBody = (response, body) => new Response(body, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });

  const orderDetailLines = async (url, fallbackEpoch) => {
    const response = await nativeFetch(url, {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { Accept: 'text/html' },
    });
    if (!response.ok) return [];

    const html = await response.text();
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    if (parsed.querySelector('.label-tag-alert')) return [];

    const dateText = parsed.querySelector('.order-date')?.textContent?.trim() || '';
    const parsedDate = Date.parse(dateText);
    const epoch = Number.isFinite(parsedDate)
      ? Math.floor(parsedDate / 1000)
      : fallbackEpoch;
    const detailUrl = requestUrl(url);
    const token = detailUrl
      ? detailUrl.pathname.split('/').filter(Boolean).pop() || ''
      : '';

    return Array.from(parsed.querySelectorAll('.product-qty-badge'))
      .map((badge, index) => {
        const row = badge.closest('.flex-table-tr');
        const productLink = badge.closest('a[href*="/products/"]')
          || row?.querySelector('a[href*="/products/"]');
        const handle = productHandleFromUrl(productLink?.getAttribute('href'));
        const units = quantity(badge.textContent, 0);
        if (!handle || units < 1) return null;

        // A stable synthetic variant id keeps two same-product lines in one
        // order distinct while still deduplicating the same order across tabs.
        return [
          handle,
          '',
          epoch,
          units,
          token,
          '',
          `detail:${token}:${index}`,
        ];
      })
      .filter(Boolean);
  };

  const visibleOrderUrls = (parsed) => {
    const urls = [];
    parsed.querySelectorAll('article.flex-table-tr').forEach((article) => {
      // EasyStore marks cancelled orders with the alert status label. Their
      // detail pages must never be used to consume purchase allowance.
      if (article.querySelector('.order-status .label-tag-alert')) return;
      const link = article.querySelector(
        'a.h3[href^="/account/orders/"], a[href^="/account/orders/"]'
      );
      const href = link?.getAttribute('href') || '';
      if (href && !urls.includes(href)) urls.push(href);
    });
    return urls;
  };

  const enrichHistoryResponse = async (response) => {
    if (!response.ok) return response;

    let html;
    try {
      html = await response.clone().text();
    } catch (_error) {
      return response;
    }

    const parsed = new DOMParser().parseFromString(html, 'text/html');
    const payloadElement = parsed.getElementById(HISTORY_PAYLOAD_ID);
    if (!payloadElement) return response;

    let payload;
    try {
      payload = JSON.parse(payloadElement.textContent || '{}');
    } catch (_error) {
      return response;
    }

    const existingLines = Array.isArray(payload.lines) ? payload.lines : [];
    const diagnostics = payload.diagnostics || {};
    if (existingLines.length || quantity(diagnostics.ordersSeen, 0) < 1) {
      return response;
    }

    const orderUrls = visibleOrderUrls(parsed);
    const remainingBudget = Math.max(0, MAX_DETAIL_REQUESTS - detailRequests);
    const candidates = orderUrls.slice(0, remainingBudget);
    if (!candidates.length) return response;
    detailRequests += candidates.length;

    const fallbackEpoch = quantity(payload.renderedAt, Math.floor(Date.now() / 1000));
    const detailResults = await Promise.all(
      candidates.map((url) => orderDetailLines(url, fallbackEpoch).catch(() => []))
    );
    const lines = detailResults.flat();
    if (!lines.length) return response;

    payload.lines = lines;
    payload.truncated = Boolean(payload.truncated)
      || candidates.length < orderUrls.length
      || detailRequests >= MAX_DETAIL_REQUESTS;
    payload.diagnostics = {
      ...diagnostics,
      lineItemsSeen: lines.length,
      detailPagesSeen: detailResults.filter((result) => result.length > 0).length,
    };
    payloadElement.textContent = JSON.stringify(payload);

    return responseWithBody(
      response,
      `<!doctype html>\n${parsed.documentElement.outerHTML}`
    );
  };

  // The purchase-limit loader already fetches /account/orders. Only those
  // responses are enriched; every other storefront request uses the native
  // fetch unchanged.
  window.fetch = (input, init) => {
    if (!isHistoryListRequest(input)) return nativeFetch(input, init);
    return nativeFetch(input, init).then((response) => (
      enrichHistoryResponse(response).catch(() => response)
    ));
  };
})();
