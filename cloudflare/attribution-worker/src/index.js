const CHANNELS = Object.freeze({
  ca: Object.freeze({ source: "carousell", medium: "marketplace" }),
  fb: Object.freeze({ source: "facebook", medium: "social" }),
  wa: Object.freeze({ source: "whatsapp", medium: "messaging" }),
  qr: Object.freeze({ source: "qr", medium: "offline" }),
});

const MAX_CAMPAIGN_LENGTH = 100;

// The click id has to outlive the landing page. A shopper arrives from a
// Carousell listing, browses, leaves, and comes back an hour later to register:
// the URL parameter is long gone by then, so the redirect also hands the browser
// a first-party cookie that the storefront reads whenever it needs the value.
//
// Ninety days is the window an offline QR code plausibly spans. It is not
// HttpOnly on purpose - the storefront's own script has to read it to fill the
// EasyStore customer attribute that carries the id into the CRM - and that is
// safe here because the value is an opaque random id holding no personal data
// and granting no access. SameSite=Lax still travels on the top-level
// navigation that a social or marketplace link performs.
const CLICK_COOKIE = "cb_click_id";
const CLICK_COOKIE_MAX_AGE = 60 * 60 * 24 * 90;

// Link-preview crawlers hit these URLs constantly: pasting a /go/fb link into
// WhatsApp fetches it once to draw the card, and Facebook re-fetches it for
// every impression of the post. Those are not shoppers, and counting them as
// clicks inflates exactly the number this Worker exists to report.
//
// They are recorded rather than dropped, with the reason they were judged
// automated, so the raw row count stays complete and a channel report can
// subtract them - and so a mistake in this list is visible in the data instead
// of silently deleting real traffic.
const AUTOMATED_USER_AGENT =
  /bot\b|crawler|crawling|spider|slurp|fetcher|preview|facebookexternalhit|whatsapp|telegram|slackbot|twitterbot|discordbot|embedly|pinterest|linkedinbot|skypeuripreview|applebot|bingpreview|curl\/|wget\/|python-requests|go-http-client|okhttp|java\/|libwww-perl|headlesschrome|phantomjs|lighthouse|pingdom|uptimerobot|monitoring/i;

// A browser that speculatively loads a link the shopper has not clicked yet
// announces it. Chrome and Safari send Sec-Purpose, older Chrome sent Purpose,
// Firefox sends X-Moz, and Safari's link preview sends X-Purpose.
const PREFETCH_HEADERS = Object.freeze([
  Object.freeze(["sec-purpose", /prefetch|prerender/i]),
  Object.freeze(["purpose", /prefetch|preview/i]),
  Object.freeze(["x-purpose", /prefetch|preview/i]),
  Object.freeze(["x-moz", /prefetch/i]),
]);

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === "/go/health") {
      return Response.json({ ok: true, worker: "cc-attribution" });
    }

    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method not allowed", {
        status: 405,
        headers: { Allow: "GET, HEAD" },
      });
    }

    const match = /^\/go\/([^/]+)\/?$/.exec(url.pathname);
    if (!match) {
      return new Response("Not found", { status: 404 });
    }

    const code = match[1].toLowerCase();
    const channel = CHANNELS[code];
    if (!channel) {
      return new Response("Unknown source", { status: 404 });
    }

    const clickId = crypto.randomUUID();
    const campaign = sanitizeCampaign(
      url.searchParams.get("campaign") || env.DEFAULT_CAMPAIGN || "always-on",
    );
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

    const destination = new URL(env.STORE_URL || "https://cardboard.sg/");
    destination.searchParams.set("utm_source", channel.source);
    destination.searchParams.set("utm_medium", channel.medium);
    destination.searchParams.set("utm_campaign", campaign);
    destination.searchParams.set("utm_content", code);
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

export function sanitizeCampaign(value) {
  const normalized = String(value)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, MAX_CAMPAIGN_LENGTH);

  return normalized || "always-on";
}

/**
 * Return why a request looks automated, or an empty string for a real click.
 *
 * The reason travels with the row, so "how many of last week's Facebook clicks
 * were link previews?" is answerable from the data rather than from a guess.
 */
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

/**
 * Return the cookie domain, so a store served from www still gets the value.
 *
 * A host-only cookie set by `cardboard.sg/go/fb` is not sent to
 * `www.cardboard.sg`, which would lose the click id for exactly the shoppers
 * whose browser or link normalizes to the www host. Naming the registrable
 * domain covers the apex and its subdomains alike.
 */
export function cookieDomain(env) {
  const configured = String(env?.COOKIE_DOMAIN || "").trim();
  if (configured) {
    return configured;
  }

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
        bot_reason
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    )
    .run();
}
