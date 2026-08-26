/**
 * Behavioural tests for the attribution Worker.
 *
 * `npm run check` only parses the file. What matters in production is what the
 * Worker does with a request: which redirect it issues, what it writes to D1,
 * whether the click id reaches the browser in a form that survives navigation,
 * and whether a link-preview crawler is recorded as a shopper. Those are
 * asserted here, against the real exported handler, with fake bindings.
 */

import assert from "node:assert/strict";
import test from "node:test";

import worker, {
  automatedReason,
  captureAdClickIdentifiers,
  clickCookie,
  cookieDomain,
  sanitizeCampaign,
} from "../src/index.js";

const ENV = Object.freeze({
  STORE_URL: "https://cardboard.sg/",
  DEFAULT_CAMPAIGN: "always-on",
});

/** A D1 binding that records the statements and bindings it was given. */
function fakeDatabase({ fail = false } = {}) {
  const writes = [];
  return {
    writes,
    prepare(sql) {
      return {
        bind(...values) {
          return {
            async run() {
              if (fail) {
                throw new Error("D1 unavailable");
              }
              writes.push({ sql, values });
              return { success: true };
            },
          };
        },
      };
    },
  };
}

function fakeAnalytics() {
  const points = [];
  return { points, writeDataPoint: (point) => points.push(point) };
}

/**
 * Build a request the Worker can read.
 *
 * `Request` will not carry Cloudflare's `cf` object outside the runtime, so the
 * handler is given the same shape it actually uses: method, url, headers, cf.
 */
function makeRequest(path, { method = "GET", headers = {}, cf = {} } = {}) {
  return {
    method,
    url: new URL(path, "https://go.cardboard.sg").toString(),
    headers: new Headers({ "user-agent": BROWSER_USER_AGENT, ...headers }),
    cf: { country: "SG", ...cf },
  };
}

const BROWSER_USER_AGENT =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 " +
  "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";

/** Await every promise the handler handed to `waitUntil`. */
function context() {
  const pending = [];
  return { pending, waitUntil: (promise) => pending.push(promise) };
}

async function invoke(request, { db, analytics, env = ENV } = {}) {
  const ctx = context();
  const bindings = { ...env };
  if (db) bindings.DB = db;
  if (analytics) bindings.ANALYTICS = analytics;

  const response = await worker.fetch(request, bindings, ctx);
  await Promise.all(ctx.pending);
  return response;
}

function d1Row(write) {
  const [
    clickId,
    source,
    medium,
    campaign,
    path,
    country,
    clickedAt,
    bot,
    botReason,
  ] = write.values;
  return {
    clickId,
    source,
    medium,
    campaign,
    path,
    country,
    clickedAt,
    bot,
    botReason,
  };
}

function sourceWrite(db) {
  return db.writes.find((write) => write.sql.includes("INSERT INTO source_clicks"));
}

function identifierWrites(db) {
  return db.writes.filter((write) =>
    write.sql.includes("INSERT INTO source_click_identifiers"),
  );
}

test("a tracked click redirects to the store with UTMs and the click id", async () => {
  const response = await invoke(makeRequest("/go/fb"));

  assert.equal(response.status, 302);
  const location = new URL(response.headers.get("location"));
  assert.equal(location.origin + location.pathname, "https://cardboard.sg/");
  assert.equal(location.searchParams.get("utm_source"), "facebook");
  assert.equal(location.searchParams.get("utm_medium"), "social");
  assert.equal(location.searchParams.get("utm_campaign"), "always-on");
  assert.equal(location.searchParams.get("utm_content"), "fb");
  assert.match(
    location.searchParams.get("cb_click_id"),
    /^[0-9a-f-]{36}$/,
  );
  assert.equal(response.headers.get("cache-control"), "no-store");
});

test("the redirect hands the browser the same click id as a first-party cookie", async () => {
  const response = await invoke(makeRequest("/go/ca"));

  const location = new URL(response.headers.get("location"));
  const cookie = response.headers.get("set-cookie");

  // The URL parameter is gone as soon as the shopper navigates; the cookie is
  // what a later registration reads, so the two must agree.
  assert.ok(
    cookie.startsWith(`cb_click_id=${location.searchParams.get("cb_click_id")};`),
    `cookie ${cookie} does not carry the redirect's click id`,
  );
  assert.match(cookie, /Domain=cardboard\.sg/);
  assert.match(cookie, /Path=\//);
  assert.match(cookie, /Max-Age=7776000/);
  assert.match(cookie, /SameSite=Lax/);
  assert.match(cookie, /Secure/);
  // The storefront script has to read it, so HttpOnly would break the join.
  assert.doesNotMatch(cookie, /HttpOnly/i);
});

test("each channel code maps to its own source and medium", async () => {
  const expected = {
    ca: ["carousell", "marketplace"],
    fb: ["facebook", "social"],
    gg: ["google", "cpc"],
    ig: ["instagram", "social"],
    li: ["linkedin", "social"],
    tt: ["tiktok", "social"],
    wa: ["whatsapp", "messaging"],
    qr: ["qr", "offline"],
  };

  for (const [code, [source, medium]] of Object.entries(expected)) {
    const db = fakeDatabase();
    await invoke(makeRequest(`/go/${code}`), { db });
    const row = d1Row(sourceWrite(db));
    assert.equal(row.source, source);
    assert.equal(row.medium, medium);
    assert.equal(row.path, `/go/${code}`);
  }
});

test("an uppercase channel code and a trailing slash still resolve", async () => {
  const response = await invoke(makeRequest("/go/FB/"));

  assert.equal(response.status, 302);
  assert.equal(
    new URL(response.headers.get("location")).searchParams.get("utm_source"),
    "facebook",
  );
});

test("native ad click ids are preserved, forwarded, and stored separately", async () => {
  const db = fakeDatabase();
  const response = await invoke(
    makeRequest(
      "/gg?campaign=search&content=brand&to=/collections/test" +
        "&gclid=Google-AbC_123&gbraid=GBRAID-CaSe&wbraid=WBRAID-CaSe",
    ),
    { db },
  );

  const location = new URL(response.headers.get("location"));
  assert.equal(location.pathname, "/collections/test");
  assert.equal(location.searchParams.get("gclid"), "Google-AbC_123");
  assert.equal(location.searchParams.get("gbraid"), "GBRAID-CaSe");
  assert.equal(location.searchParams.get("wbraid"), "WBRAID-CaSe");

  const writes = identifierWrites(db);
  assert.equal(writes.length, 3);
  const byParameter = Object.fromEntries(
    writes.map((write) => [write.values[2], write.values]),
  );
  assert.equal(byParameter.gclid[1], "google");
  assert.equal(byParameter.gclid[3], "Google-AbC_123");
  assert.equal(byParameter.gbraid[3], "GBRAID-CaSe");
  assert.equal(byParameter.wbraid[3], "WBRAID-CaSe");
  assert.equal(byParameter.gclid[0], d1Row(sourceWrite(db)).clickId);
});

test("facebook tiktok and linkedin click ids pass through unchanged", async () => {
  const db = fakeDatabase();
  const response = await invoke(
    makeRequest(
      "/fb?fbclid=FB.Case&ttclid=TT.Case&li_fat_id=LI.Case&campaign=mixed",
    ),
    { db },
  );
  const location = new URL(response.headers.get("location"));
  assert.equal(location.searchParams.get("fbclid"), "FB.Case");
  assert.equal(location.searchParams.get("ttclid"), "TT.Case");
  assert.equal(location.searchParams.get("li_fat_id"), "LI.Case");

  const networkByParameter = Object.fromEntries(
    identifierWrites(db).map((write) => [write.values[2], write.values[1]]),
  );
  assert.deepEqual(networkByParameter, {
    fbclid: "facebook",
    ttclid: "tiktok",
    li_fat_id: "linkedin",
  });
});

test("invalid ad click identifiers are ignored rather than truncated", () => {
  const url = new URL("https://go.cardboard.sg/gg");
  url.searchParams.set("gclid", "x".repeat(1025));
  url.searchParams.set("fbclid", "bad\u0001value");
  url.searchParams.set("ttclid", "TikTok-OK");

  assert.deepEqual(captureAdClickIdentifiers(url), [
    { network: "tiktok", parameter: "ttclid", identifier: "TikTok-OK" },
  ]);
});

test("a real click is written to D1 as human traffic", async () => {
  const db = fakeDatabase();
  await invoke(makeRequest("/go/fb?campaign=Ju1y%20Sale!"), { db });

  assert.equal(db.writes.length, 1);
  const row = d1Row(sourceWrite(db));
  assert.equal(row.campaign, "ju1y-sale");
  assert.equal(row.country, "SG");
  assert.equal(row.bot, 0);
  assert.equal(row.botReason, "");
  assert.ok(Number.isInteger(row.clickedAt));
});

test("a WhatsApp link preview is recorded, flagged, and still redirected", async () => {
  const db = fakeDatabase();
  const response = await invoke(
    makeRequest("/go/wa", { headers: { "user-agent": "WhatsApp/2.23.20" } }),
    { db },
  );

  // The crawler needs the destination to draw its card, so it is not refused.
  assert.equal(response.status, 302);
  // And the row survives, so the raw count stays complete and auditable.
  const row = d1Row(sourceWrite(db));
  assert.equal(row.bot, 1);
  assert.equal(row.botReason, "user-agent");
});

test("a browser prefetch is flagged by its own announcement", async () => {
  const db = fakeDatabase();
  await invoke(
    makeRequest("/go/fb", { headers: { "sec-purpose": "prefetch;anonymous-client-ip" } }),
    { db },
  );

  assert.equal(d1Row(sourceWrite(db)).botReason, "prefetch");
});

test("a Cloudflare verified bot is flagged even with a browser user agent", async () => {
  const db = fakeDatabase();
  await invoke(
    makeRequest("/go/fb", { cf: { botManagement: { verifiedBot: true } } }),
    { db },
  );

  assert.equal(d1Row(sourceWrite(db)).botReason, "verified-bot");
});

test("analytics engine gets the same facts including the bot dimension", async () => {
  const analytics = fakeAnalytics();
  await invoke(
    makeRequest("/go/qr?campaign=expo", {
      headers: { "user-agent": "facebookexternalhit/1.1" },
    }),
    { analytics },
  );

  assert.equal(analytics.points.length, 1);
  const [point] = analytics.points;
  assert.deepEqual(point.blobs, [
    "qr",
    "offline",
    "expo",
    "/go/qr",
    "SG",
    "user-agent",
  ]);
  assert.deepEqual(point.doubles, [1, 1]);
  assert.equal(point.indexes.length, 1);
});

test("a D1 outage still redirects the shopper", async () => {
  const errors = [];
  const original = console.error;
  console.error = (message) => errors.push(message);
  try {
    const response = await invoke(makeRequest("/go/fb"), {
      db: fakeDatabase({ fail: true }),
    });
    assert.equal(response.status, 302);
  } finally {
    console.error = original;
  }

  assert.equal(errors.length, 1);
  assert.equal(JSON.parse(errors[0]).event, "source_click_d1_write_failed");
});

test("a HEAD request redirects without recording a click", async () => {
  const db = fakeDatabase();
  const analytics = fakeAnalytics();
  const response = await invoke(makeRequest("/go/fb", { method: "HEAD" }), {
    db,
    analytics,
  });

  assert.equal(response.status, 302);
  assert.equal(db.writes.length, 0);
  assert.equal(analytics.points.length, 0);
});

test("the Worker runs without either binding configured", async () => {
  const response = await invoke(makeRequest("/go/fb"));
  assert.equal(response.status, 302);
});

test("health, unknown channels, non-/go paths and writes are refused correctly", async () => {
  const health = await invoke(makeRequest("/go/health"));
  assert.equal(health.status, 200);
  assert.deepEqual(await health.json(), { ok: true, worker: "cc-attribution" });

  const unknown = await invoke(makeRequest("/go/tiktok"));
  assert.equal(unknown.status, 404);
  assert.equal(await unknown.text(), "Unknown source");

  const nested = await invoke(makeRequest("/go/fb/extra"));
  assert.equal(nested.status, 404);
  assert.equal(await nested.text(), "Not found");

  const post = await invoke(makeRequest("/go/fb", { method: "POST" }));
  assert.equal(post.status, 405);
  assert.equal(post.headers.get("allow"), "GET, HEAD");
});

test("a health check is answered before the method guard", async () => {
  const response = await invoke(makeRequest("/go/health", { method: "POST" }));
  assert.equal(response.status, 200);
});

test("campaign sanitisation keeps a usable label and never an empty one", () => {
  assert.equal(sanitizeCampaign(" July Sale 2026 "), "july-sale-2026");
  assert.equal(sanitizeCampaign("promo_A.1-b"), "promo_a.1-b");
  assert.equal(sanitizeCampaign("---"), "always-on");
  assert.equal(sanitizeCampaign(""), "always-on");
  assert.equal(sanitizeCampaign("!!!"), "always-on");
  assert.equal(sanitizeCampaign("a".repeat(200)).length, 100);
});

test("a blank campaign parameter falls back to the configured default", async () => {
  const db = fakeDatabase();
  await invoke(makeRequest("/go/fb?campaign="), { db });
  assert.equal(d1Row(sourceWrite(db)).campaign, "always-on");

  const configured = fakeDatabase();
  await invoke(makeRequest("/go/fb"), {
    db: configured,
    env: { STORE_URL: "https://cardboard.sg/", DEFAULT_CAMPAIGN: "spring" },
  });
  assert.equal(d1Row(sourceWrite(configured)).campaign, "spring");
});

test("a missing STORE_URL and DEFAULT_CAMPAIGN fall back to production values", async () => {
  const response = await invoke(makeRequest("/go/fb"), { env: {} });
  const location = new URL(response.headers.get("location"));

  assert.equal(location.host, "cardboard.sg");
  assert.equal(location.searchParams.get("utm_campaign"), "always-on");
});

test("automatedReason reads a real browser as a shopper", () => {
  const request = makeRequest("/go/fb");
  assert.equal(automatedReason(request), "");
});

test("a request with no user agent at all is flagged", () => {
  const request = { headers: new Headers(), cf: {} };
  assert.equal(automatedReason(request), "no-user-agent");

  const blank = { headers: new Headers({ "user-agent": "   " }), cf: {} };
  assert.equal(automatedReason(blank), "no-user-agent");
});

test("known automated clients are recognised", () => {
  const agents = [
    "facebookexternalhit/1.1",
    "WhatsApp/2.23",
    "TelegramBot (like TwitterBot)",
    "Slackbot-LinkExpanding 1.0",
    "curl/8.4.0",
    "python-requests/2.31.0",
    "Mozilla/5.0 HeadlessChrome/120.0.0.0",
    "Googlebot/2.1",
  ];
  for (const agent of agents) {
    const request = { headers: new Headers({ "user-agent": agent }), cf: {} };
    assert.equal(automatedReason(request), "user-agent", agent);
  }
});

test("the cookie domain follows the store URL and drops a www prefix", () => {
  assert.equal(cookieDomain({ STORE_URL: "https://cardboard.sg/" }), "cardboard.sg");
  assert.equal(cookieDomain({ STORE_URL: "https://www.cardboard.sg/" }), "cardboard.sg");
  assert.equal(cookieDomain({ STORE_URL: "https://shop.example.com/" }), "shop.example.com");
  assert.equal(cookieDomain({ COOKIE_DOMAIN: "override.test" }), "override.test");
  assert.equal(cookieDomain({ STORE_URL: "not a url" }), "cardboard.sg");
  assert.equal(cookieDomain(undefined), "cardboard.sg");
});

test("clickCookie is built from the id and the domain it was given", () => {
  assert.equal(
    clickCookie("abc", "cardboard.sg"),
    "cb_click_id=abc; Domain=cardboard.sg; Path=/; Max-Age=7776000; SameSite=Lax; Secure",
  );
});
