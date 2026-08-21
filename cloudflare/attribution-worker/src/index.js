const CHANNELS = Object.freeze({
  ca: Object.freeze({ source: "carousell", medium: "marketplace" }),
  fb: Object.freeze({ source: "facebook", medium: "social" }),
  wa: Object.freeze({ source: "whatsapp", medium: "messaging" }),
  qr: Object.freeze({ source: "qr", medium: "offline" }),
});

const MAX_CAMPAIGN_LENGTH = 100;

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
    const referrer = request.headers.get("Referer") || "";

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
          ],
          doubles: [1],
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
            referrer,
            clickedAt,
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
      },
    });
  },
};

function sanitizeCampaign(value) {
  const normalized = String(value)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, MAX_CAMPAIGN_LENGTH);

  return normalized || "always-on";
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
        referrer,
        clicked_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(click_id) DO NOTHING`,
    )
    .bind(
      click.clickId,
      click.source,
      click.medium,
      click.campaign,
      click.path,
      click.country,
      click.referrer,
      click.clickedAt,
    )
    .run();
}
