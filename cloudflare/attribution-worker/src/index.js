const CHANNELS = Object.freeze({
  ca: Object.freeze({ source: "carousell", medium: "marketplace" }),
  fb: Object.freeze({ source: "facebook", medium: "social" }),
  ig: Object.freeze({ source: "instagram", medium: "social" }),
  tt: Object.freeze({ source: "tiktok", medium: "social" }),
  wa: Object.freeze({ source: "whatsapp", medium: "messaging" }),
  em: Object.freeze({ source: "email", medium: "email" }),
  qr: Object.freeze({ source: "qr", medium: "offline" }),
});

const MAX_LABEL_LENGTH = 100;
const CLICK_COOKIE = "cb_click_id";
const CLICK_COOKIE_MAX_AGE = 60 * 60 * 24 * 90;
const CLICK_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CUSTOMER_ID = /^\d{1,32}$/;

const AUTOMATED_USER_AGENT =
  /bot\b|crawler|crawling|spider|slurp|fetcher|preview|facebookexternalhit|whatsapp|telegram|slackbot|twitterbot|discordbot|embedly|pinterest|linkedinbot|skypeuripreview|applebot|bingpreview|curl\/|wget\/|python-requests|go-http-client|okhttp|java\/|libwww-perl|headlesschrome|phantomjs|lighthouse|pingdom|uptimerobot|monitoring/i;

const PREFETCH_HEADERS = Object.freeze([
  Object.freeze(["sec-purpose", /prefetch|prerender/i]),
  Object.freeze(["purpose", /prefetch|preview/i]),
  Object.freeze(["x-purpose", /prefetch|preview/i]),
  Object.freeze(["x-moz", /prefetch/i]),
]);

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === "/go/health" || url.pathname === "/health") {
      return Response.json({ ok: true, worker: "cc-attribution" });
    }

    if (url.pathname === "/touch" || url.pathname === "/go/touch") {
      return handleTouch(request, env);
    }

    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method not allowed", {
        status: 405,
        headers: { Allow: "GET, HEAD" },
      });
    }

    const tracking = trackingRoute(url, env);
    if (tracking === null) {
      return new Response("Not found", { status: 404 });
    }
    if (tracking.channel === null) {
      return new Response("Unknown source", { status: 404 });
    }

    const { channel, campaign, content, to } = tracking;
    const clickId = crypto.randomUUID();
    const clickedAt = Date.now();
    const country = String(request.cf?.country || "");
    const botReason = automatedReason(request);

    if (request.method === "GET") {
      if (env.ANALYTICS) {
        env.ANALYTICS.writeDataPoint({
          indexes: [clickId],
          blobs: [
            channel.source,
            channel.medium,
            campaign,
            url.pathname,
            country,
            botReason,
          ],
          doubles: [1, botReason ? 1 : 0],
        });
      }

      if (env.DB) {
        ctx.waitUntil(
          recordClick(env.DB, {
            clickId,
            source: channel.source,
            medium: channel.medium,
            campaign,
            content,
            path: url.pathname,
            country,
            clickedAt,
            botReason,
          }).catch((error) => {
            console.error(
              JSON.stringify({
                event: "source_click_d1_write_failed",
                click_id: clickId,
                message: error instanceof Error ? error.message : String(error),
              }),
            );
          }),
        );
      }
    }

    const destination = destinationUrl(env, to);
    destination.searchParams.set("utm_source", channel.source);
    destination.searchParams.set("utm_medium", channel.medium);
    destination.searchParams.set("utm_campaign", campaign);
    destination.searchParams.set("utm_content", content);
    destination.searchParams.set("cb_click_id", clickId);

    return new Response(null, {
      status: 302,
      headers: {
        Location: destination.toString(),
        "Cache-Control": "no-store",
        "Set-Cookie": clickCookie(clickId, cookieDomain(env)),
      },
    });
  },
};

function trackingRoute(url, env) {
  const match = /^\/(?:go\/)?([^/]+)\/?$/.exec(url.pathname);
  if (!match) return null;

  const code = match[1].toLowerCase();
  const channel = CHANNELS[code];
  if (!channel) {
    return { channel: null };
  }

  return {
    channel,
    campaign: sanitizeCampaign(
      url.searchParams.get("campaign") || env.DEFAULT_CAMPAIGN || "always-on",
    ),
    content: sanitizeContent(url.searchParams.get("content"), code),
    to: safeDestinationPath(url.searchParams.get("to")),
  };
}

export function sanitizeCampaign(value) {
  return sanitizeLabel(value, "always-on");
}

export function sanitizeContent(value, fallback = "unknown") {
  return sanitizeLabel(value, fallback);
}

function sanitizeLabel(value, fallback) {
  const normalized = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, MAX_LABEL_LENGTH);
  return normalized || fallback;
}

export function safeDestinationPath(value) {
  const text = String(value || "").trim();
  if (!text) return "/";
  if (!text.startsWith("/") || text.startsWith("//") || text.includes("\\")) {
    return "/";
  }
  return text;
}

function destinationUrl(env, path) {
  const base = new URL(env.STORE_URL || "https://cardboard.sg/");
  return new URL(safeDestinationPath(path), base);
}

async function handleTouch(request, env) {
  const origin = request.headers?.get("origin") || "";
  const cors = touchCorsHeaders(origin, env);

  if (request.method === "OPTIONS") {
    return new Response(null, { status: cors ? 204 : 403, headers: cors || {} });
  }
  if (request.method !== "POST") {
    return new Response("Method not allowed", {
      status: 405,
      headers: { ...(cors || {}), Allow: "POST, OPTIONS" },
    });
  }
  if (!cors) {
    return new Response("Forbidden", { status: 403 });
  }
  if (!env.DB) {
    return Response.json(
      { ok: false, error: "touch storage unavailable" },
      { status: 503, headers: cors },
    );
  }

  let payload;
  try {
    payload = await request.json();
  } catch (error) {
    return Response.json(
      { ok: false, error: "invalid json" },
      { status: 400, headers: cors },
    );
  }

  const customerId = String(payload?.customer_id || "").trim();
  const clickId = String(payload?.click_id || "").trim().toLowerCase();
  if (!CUSTOMER_ID.test(customerId) || !CLICK_ID.test(clickId)) {
    return Response.json(
      { ok: false, error: "invalid touch" },
      { status: 400, headers: cors },
    );
  }

  // INSERT ... SELECT guarantees that arbitrary UUIDs never become touches: the
  // click must already exist in source_clicks and must be human traffic. The
  // primary key preserves the first binding timestamp on retries.
  const result = await env.DB
    .prepare(
      `INSERT INTO customer_touches (customer_id, click_id, bound_at)
       SELECT ?, click_id, ? FROM source_clicks
       WHERE click_id = ? AND COALESCE(bot, 0) = 0
       ON CONFLICT(customer_id, click_id) DO NOTHING`,
    )
    .bind(customerId, Date.now(), clickId)
    .run();

  const changes = Number(result?.meta?.changes ?? result?.changes ?? 0);
  return Response.json(
    { ok: true, recorded: changes > 0 },
    { status: 200, headers: { ...cors, "Cache-Control": "no-store" } },
  );
}

function touchCorsHeaders(origin, env) {
  if (!origin) return null;
  const allowed = new Set();
  try {
    const store = new URL(env.STORE_URL || "https://cardboard.sg/");
    allowed.add(store.origin);
    const hostname = store.hostname.replace(/^www\./i, "");
    allowed.add(`${store.protocol}//${hostname}`);
    allowed.add(`${store.protocol}//www.${hostname}`);
  } catch (error) {
    allowed.add("https://cardboard.sg");
    allowed.add("https://www.cardboard.sg");
  }
  for (const value of String(env.ALLOWED_TOUCH_ORIGINS || "").split(",")) {
    if (value.trim()) allowed.add(value.trim());
  }
  if (!allowed.has(origin)) return null;
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Credentials": "true",
    Vary: "Origin",
  };
}

export function automatedReason(request) {
  if (request.cf?.botManagement?.verifiedBot === true) {
    return "verified-bot";
  }

  for (const [header, pattern] of PREFETCH_HEADERS) {
    const value = request.headers?.get(header);
    if (value && pattern.test(value)) {
      return "prefetch";
    }
  }

  const userAgent = request.headers?.get("user-agent");
  if (!userAgent || !userAgent.trim()) {
    return "no-user-agent";
  }
  if (AUTOMATED_USER_AGENT.test(userAgent)) {
    return "user-agent";
  }
  return "";
}

export function cookieDomain(env) {
  const configured = String(env?.COOKIE_DOMAIN || "").trim();
  if (configured) return configured;

  try {
    const host = new URL(env?.STORE_URL || "https://cardboard.sg/").hostname;
    return host.replace(/^www\./i, "");
  } catch (error) {
    return "cardboard.sg";
  }
}

export function clickCookie(clickId, domain) {
  return (
    `${CLICK_COOKIE}=${clickId}; Domain=${domain}; Path=/; ` +
    `Max-Age=${CLICK_COOKIE_MAX_AGE}; SameSite=Lax; Secure`
  );
}

async function recordClick(db, click) {
  await db
    .prepare(
      `INSERT INTO source_clicks (
        click_id,
        source,
        medium,
        campaign,
        path,
        country,
        clicked_at,
        bot,
        bot_reason,
        content
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(click_id) DO NOTHING`,
    )
    .bind(
      click.clickId,
      click.source,
      click.medium,
      click.campaign,
      click.path,
      click.country,
      click.clickedAt,
      click.botReason ? 1 : 0,
      click.botReason,
      click.content,
    )
    .run();
}
