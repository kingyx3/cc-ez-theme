# Footer pages

The six files under `pages/` are the source of truth for Cardboard Collective's footer-linked EasyStore pages. They are rendered as HTML by `scripts/pages/deploy_footer_pages.py` and updated through the EasyStore **Admin API**, not through the theme ZIP. Avoid manual changes in the EasyStore page editor: the next content deployment will replace the page body.

Keep one `##` page title, `###` section headings, short paragraphs, unordered lists and descriptive links. Prefer Singapore English, explicit SGD thresholds and the same contact details on all pages. Preserve legal protections and statutory rights; seek legal review before changing substantive rights or remedies.

The admin deployer must find exactly these six *existing published* page handles. It does not create pages, change their navigation, unpublish pages or deploy the theme. It captures an API backup, checks all six existing pages before writing, uses the existing published status, and verifies each read-back. If it cannot determine status or a target is missing, it stops.

Relevant current terms: PayNow via HitPay at checkout; approximately 15-minute checkout expiry; S$10 delivery below S$500, free delivery from S$500, and an optional arranged meet-up from S$1,000. Recheck those operational facts with the store before changing them.
