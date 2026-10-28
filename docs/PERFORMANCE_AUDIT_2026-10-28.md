# Storefront performance audit — 2026-10-28

Repository: `kingyx3/cc-ez-theme`. Scope: EasyStore Liquid layout, sections, product/listing snippets, shared CSS/JS, and existing CI. This audit is source-level plus live-site Playwright observations. It is **not** an independent Lighthouse score and is **not** a measurement of an unpublished PR preview.

## Verified baseline

Source: GitHub Actions `Storefront performance observations`, run [40696042279](https://github.com/kingyx3/cc-ez-theme/actions/runs/40696042279), `summary.md`; sampled the **live site** `https://cardboard.sg/` with Chromium desktop, 3 cold and 3 warm samples per route, 2026-10-28 UTC.

| Route | Cold TTFB | Cold LCP | Cold CLS | Requests | Separately tracked image bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Homepage | 779 ms | 1084 ms | 0.10 | 68 | 1341 KiB / 12 images |
| Collection | 904 ms | 1440 ms | 0.00 | 77 | 3038 KiB / 22 images |
| Product | 501 ms | 840 ms | 0.00 | 81 | 711 KiB / 11 images |
| Cart | 527 ms | 1328 ms | 0.00 | 87 | 1712 KiB / 13 images |
| Account login | 498 ms | 672 ms | 0.00 | 57 | 19 KiB / 4 images |

Resource Timing's generic `transferBytes` and `jsTransferBytes` fields can undercount cross-origin resources. The Playwright suite collects **image response bytes separately** because the CDN does not expose those timing fields cross-origin. Do not add the columns together as though they are homogeneous. Hosted-runner observations are not mobile Lighthouse lab scores or real-user Core Web Vitals.

The supplied historical PageSpeed Insights report pages were not accessible through the available web browser. Never derive an estimated Lighthouse score change from this audit.

## Repo-wide findings and changes

| Priority | Area | Evidence | Action or disposition |
| --- | --- | --- | --- |
| High | Listing cards | `snippets/product-card.liquid` emitted feedback JS/CSS even when the global listing add-to-cart toggle was off; preset currently stores `0` | **Changed in PR #324:** only render those assets when controls exist, preserving the once-per-page guard |
| High | Global assets | `layout/theme.liquid` delivered account-details validation on all page types | **Changed:** load it on customer templates only. **Do not gate** global login/OTP recovery and return-redirect code; they must also work on platform-rendered authentication steps |
| High | Offscreen media | `main-product.liquid` and `featured-product.liquid` eagerly embedded every YouTube video in a gallery | **Changed:** later gallery YouTube iframes use native lazy loading, while the first visible image/video retains eager behavior. Correct selected-variant video ID binding. Native lazy loading is a browser hint, not guaranteed zero network traffic |
| High | Image weight | Homepage ~1.3 MiB, collection ~3.0 MiB image responses in the cold desktop samples | **Investigate next:** image formats/compression, unusually large product uploads, and the actual rendered DPR/sizes before changing CDN transformations |
| Medium | JavaScript critical path | The layout loads jQuery 3.7.1 and jQuery Migrate 3.6.0 synchronously before `content_for_header`, followed by EasyStore's global `storefront.js` | **Not changed:** plugin/checkout compatibility and platform load order must be audited before adding `defer` or removing jQuery |
| Medium | Shared CSS | Six CSS links are emitted by each `featured-collection` section. Five such sections appear in the current homepage preset; CSS is also shared by collection/cart surfaces | **Not changed:** browser caching means repeat tags do not necessarily mean repeat network payload; evaluate stylesheet consolidation after verifying EasyStore section scope, ordering, and merchant editor behavior |
| Medium | Header and third-party scripts | `content_for_header`, `global/head`, `global/body_start`, and other app snippets can inject scripts outside the theme's direct control | Requires a browser waterfall/coverage audit; do not assume all injected code is removable |
| Low | General images | Product cards already have `srcset`, an LCP/eager image flag, lazy secondary-image sourcing, and intrinsic width/height | Preserve existing safeguards; primary product images now also specify asynchronous decoding |

## CI safeguards

- `Package EasyStore theme PR check`: unit and theme packaging checks, including mirror parity between `theme/assets` and `theme/editor_assets`. The first PR build failed because a new customer-only script guard was inserted *before* the global login-redirect module; a pre-existing test caught it. This was corrected without changing the global module's behavior. Added actual Liquid-rendering tests for six listing toggle values and six customer/public template cases.
- `EasyStore browser E2E`: Chromium, WebKit, Firefox, Chrome mobile emulation, and Safari mobile emulation; functional and account behavior checks. These exercise the URL configured in CI, **not necessarily the unmerged candidate theme**. Passing them is not proof that an unpublished preview renders correctly.
- `Storefront performance observations`: now run separately for desktop Chromium and mobile Chrome emulation. Emulated mobile does not apply Lighthouse's exact CPU/network throttling profile. Artifacts include route, project, cold/warm LCP, CLS, requests, and image bytes. The workflow now fails when Playwright exits unsuccessfully or produces insufficient usable samples, instead of presenting a green check without valid measurements.
- `tests/theme/test_storefront_asset_budget.py` and `tests/theme/test_product_video_delivery.py` pin the new load guards and avoid silently regressing them.

## Verification before shipping

1. Require all CI workflows to pass at the proposed commit and inspect any failing step/log; do not replace assertions just to obtain green.
2. Import this candidate as a **non-live theme preview** and verify homepage, collection, product with image and video media, cart, login/OTP, account details, and checkout behaviors.
3. Use identical mobile and desktop PageSpeed Insights runs on live and the candidate preview (where available), plus repeated Chrome traces, and record LCP element, render delay, CLS source, long tasks, and request waterfall.
4. In the candidate preview, verify the disabled listing-cart toggle produces no listing-cart feedback asset requests; enable it in a separate test and verify add-to-cart and purchase-limit feedback still work.
5. Inspect downloaded product-image URLs/bytes and LCP candidate before changing the EasyStore CDN `img_url` parameter or priority. Test the 5-column collection and mobile swipe carousel.
6. Only then consider jQuery removal/defer, shared stylesheet consolidation, third-party injections, or conditional global modules in separate, reversible PRs.

**Release scope:** PR #324 is reviewable but remains **unmerged**. No production merge or deployment is authorized by this audit. CI runs the GitHub checkout for static/package tests; storefront E2E and performance tests target an existing remote website, **not automatically the PR artifact**.

## Full template and risk review

| Surface | Changed in PR | Key safeguard and residual risk |
| --- | --- | --- |
| Home / featured collections | Removed listing-cart assets when merchant setting disables all listing buttons; kept first-visible-card priority and secondary-hover deferral | Site still downloads sizeable product photographs; no image codec, CDN transformation or CLS fix yet |
| Collection / search / related listings | Shared product-card guard applies wherever snippet is used | Actual per-page asset reduction needs an EasyStore-rendered preview with the setting both on/off; responsive card widths differ between 3- and 5-column grids |
| Product | Native lazy-loading hints on non-primary YouTube iframes; primary media unchanged | Browser may still fetch near-viewport iframes; image priority and gallery interactions require preview verification |
| Featured product | Preserve visible first image/video even without a selected variant; lazy-load subsequent videos; fix selected-variant video ID | Editor-specific variants and video gallery navigation require preview verification; do not remove first image eager behavior blindly |
| Cart / checkout | No checkout or purchase-limit behavior modified | Required checkout, purchase-limit and cart validations remain release gates |
| Customer / authentication | Only account-details page receives its dedicated validator; global login redirect, OTP and recovery scripts still load on platform-rendered flows | Verify phone OTP, profile completion, redirected purchase, and customer settings in the EasyStore preview |
| Theme CSS / platform scripts | No modification to global jQuery, `storefront.js` or injected app snippets | Their execution order may be significant. Treat blocking JS and repeated CSS as separate high-risk changes backed by a waterfall and editor-preview checks |

## Why this is not a complete PageSpeed remediation

The checked-in changes address **specific verified waste and edge cases**. They do not resolve the identified multi-megabyte image traffic, server/TTFB variance, third-party script cost, or CSS deduplication. The available workflows can demonstrate test, packaging, E2E and measurement health; they cannot establish a pre/post Lighthouse score delta for a theme version that has not been imported into a preview. Do not merge on a green PR run alone without a candidate preview and comparable measurements.
