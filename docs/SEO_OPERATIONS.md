# SEO operations runbook

This runbook covers the SEO work that lives outside the EasyStore theme repository.
The storefront brand is **Cardboard Collective**. It is an **online-only Singapore retailer** and is not a physical shop.

## 1. EasyStore: make the brand identity unambiguous

### Store name

1. Open **EasyStore Admin**.
2. Go to **Settings**.
3. Click the **pencil/edit icon** beside the store details.
4. Set **Store Name** to exactly:

   `Cardboard Collective`

5. Save.

Do not use `Cardboard Collective | Sealed Magic: The Gathering Singapore` as the Store Name. Keep search keywords in page copy and meta descriptions, not in the business/entity name.

### Store description

Go to **Settings > General** and set the Store Description to:

> Cardboard Collective is a Singapore-based online store for authentic sealed Magic: The Gathering products, booster boxes, bundles and preorders.

### Homepage meta description

1. Go to **Channels > Online Store > Pages > Home**.
2. Scroll to **Edit website SEO**.
3. Set the meta description to:

> Shop authentic sealed Magic: The Gathering products, booster boxes, bundles and preorders online in Singapore at Cardboard Collective.

4. Save.

### About Us page

Go to **Channels > Online Store > Pages > About Us** and make the first paragraph explicit:

> Cardboard Collective is a Singapore-based online collectibles retailer operated by Cardboard Collective Pte. Ltd. We specialise in authentic sealed Magic: The Gathering products, including booster boxes, bundles and preorders for upcoming sets. We sell online at cardboard.sg and do not operate a retail storefront.

Because the similarly named Orchard Gateway business is causing real customer/search confusion, add this short clarification near the bottom of the About page or in a small FAQ:

> Cardboard Collective is an independent online retailer and is not affiliated with Cardboard Collectible or the Orchard Gateway store.

Do not repeat the other business name across the homepage, product pages or site-wide footer.

## 2. EasyStore: optimize the current MTG set collections

For each collection, open **Products > Collections > [collection]**. Add useful visible description copy, then scroll to **Edit website SEO** and set a unique meta description.

Keep the existing clean collection handles unless there is a strong reason to migrate them; changing URLs creates avoidable redirect/canonical work.

### Reality Fracture

Collection: `/collections/reality-fracture`

Lead the visible description with:

> Shop Magic: The Gathering Reality Fracture sealed products and preorders online in Singapore from Cardboard Collective. Browse Collector Boosters, Play Boosters, Bundles, Prerelease Kits, Commander products and other sealed releases, with product availability and expected arrival information shown on each listing.

Meta description:

> Preorder MTG Reality Fracture sealed products in Singapore at Cardboard Collective, including Collector Boosters, Play Boosters, Bundles and kits.

### The Hobbit

Collection: `/collections/the-hobbit`

Lead the visible description with:

> Shop Magic: The Gathering The Hobbit sealed products online in Singapore from Cardboard Collective. Browse Collector Boosters, Play Boosters, Bundles, Scene Boxes, Prerelease Kits and other sealed The Hobbit releases.

Meta description:

> Shop MTG The Hobbit sealed products in Singapore at Cardboard Collective, including Collector Boosters, Play Boosters, Bundles and Scene Boxes.

### Marvel Super Heroes

Collection: `/collections/marvel-super-heroes`

Lead the visible description with:

> Shop Magic: The Gathering Marvel Super Heroes sealed products online in Singapore from Cardboard Collective. Browse booster boxes, bundles, prerelease products, Scene Boxes and other sealed Marvel Super Heroes releases.

Meta description:

> Shop MTG Marvel Super Heroes sealed products in Singapore at Cardboard Collective, including booster boxes, bundles, prerelease kits and Scene Boxes.

### Navigation

Make sure each current set collection is linked with a normal crawlable navigation link.

1. Go to **Channels > Online Store > Navigations**.
2. Edit the **Main Menu** / **Sets** navigation.
3. Add or confirm links for **Reality Fracture**, **The Hobbit**, and **Marvel Super Heroes**.
4. Save.

## 3. EasyStore: improve product data for search and Merchant Center

For important products in each current set:

1. Keep the product title specific: set name + product type + language/variant where useful.
2. Put the exact set name and product type in the first sentence of the product description.
3. Set **Brand** to `Magic: The Gathering` for MTG products.
4. Add the barcode/GTIN when the product has one.
5. Add a unique SEO meta description under **Search engine optimization**.
6. Avoid copy-pasting the same description between Bundle, Collector Booster, Play Booster, Prerelease and Commander products.

Example product meta description:

> Preorder the MTG Reality Fracture Collector Booster Box in Singapore from Cardboard Collective. Authentic sealed English product with local fulfilment.

## 4. Google Search Console

If `cardboard.sg` is not already verified:

1. Open **Google Search Console** and choose **Add property**.
2. Select **Domain** and enter `cardboard.sg`.
3. Copy the Google TXT verification record.
4. In EasyStore go to **Channels > Online Store > Domains**.
5. Open the registered `cardboard.sg` domain.
6. Choose **Add DNS record**.
7. Add a **TXT** record, leave the name/host blank if EasyStore requires the root, and paste the Google verification value.
8. Return to Search Console and click **Verify**.

Then:

1. Open **Sitemaps**.
2. Submit `sitemap.xml` once.
3. Open **URL Inspection** and request indexing for these URLs after the SEO/theme changes are live:
   - `https://cardboard.sg/`
   - `https://cardboard.sg/pages/about-us`
   - `https://cardboard.sg/collections/reality-fracture`
   - `https://cardboard.sg/collections/the-hobbit`
   - `https://cardboard.sg/collections/marvel-super-heroes`
4. In **Performance > Search results**, compare the last 28 days against the previous period and watch queries containing:
   - `cardboard collective`
   - `reality fracture`
   - `the hobbit`
   - `marvel super heroes`
   - `mtg singapore`

Do not repeatedly request indexing for unchanged URLs; use it after material page changes.

## 5. Google Merchant Center / free listings

For an online-only store, use online product listings and do not configure local-store inventory.

1. In EasyStore open **Channels > Google Shopping**.
2. Sign in with the Google account that owns the Merchant Center account.
3. In Merchant Center set the website to `https://cardboard.sg/` and complete **Verify/Claim website** if needed.
4. Return to EasyStore Google Shopping and use **Fetch Now** to send the product feed.
5. In Merchant Center confirm **Free listings** are enabled under the available marketing methods.
6. Review **Products / Needs attention** and fix missing GTIN, brand, image, availability, shipping or policy issues.
7. Confirm the business/display name is exactly **Cardboard Collective**.
8. Do not enable local inventory/free local listings while the business has no customer-facing retail location.

## 6. Bing Webmaster Tools

The fastest setup is to import the already verified Google Search Console property.

1. Sign in to **Bing Webmaster Tools**.
2. Choose **Import from Google Search Console**.
3. Authorize the same Google account and import `cardboard.sg`; Bing can import the verified property and known sitemaps.
4. Open **Sitemaps** and confirm the sitemap is present and processed. If it is not, submit `https://cardboard.sg/sitemap.xml`.
5. Open **URL Inspection** for the homepage, About page and the three current set collection pages.
6. Use **Request indexing** after the changes go live.
7. Run **Site Scan** once and fix high-priority crawl, canonical, title, description and markup errors before low-priority notices.

### IndexNow

Bing recommends IndexNow for fast notification of new/updated product and collection URLs. EasyStore does not expose a reliable root-file deployment path through this theme repository, so do not add a fake IndexNow key file to the theme.

For now, use Bing URL Inspection / URL Submission after important release-page updates. If `cardboard.sg` later has a controllable edge/proxy that can serve an IndexNow key file at the domain root, implement IndexNow there and verify submissions in Bing Webmaster Tools.

## 7. Social and marketplace identity

Keep the same entity name on every profile that represents the store:

- Display name: **Cardboard Collective**
- Website: `https://cardboard.sg/`
- Description: Singapore-based online MTG / collectibles retailer

The theme currently declares the official Facebook and Carousell profiles in Organization structured data. Add other profiles to structured data only after they are official, public, consistently branded profiles.

## 8. What not to do

- Do not create a Google Business Profile for a nonexistent customer-facing storefront.
- Do not associate Cardboard Collective with the Orchard Gateway address.
- Do not report the unrelated Cardboard Collectible listing as fake solely because the names are similar.
- Do not keyword-stuff the Store Name or Organization name.
- Do not change established collection/product URLs just to insert keywords.
- Do not create thin duplicate landing pages when a strong collection page already targets the same set/search intent.
