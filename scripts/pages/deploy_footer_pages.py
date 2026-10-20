#!/usr/bin/env python3
"""Publish only six existing, published EasyStore footer pages via Admin API.

Plan -> upload JSON backup artifact -> apply with optimistic content-hash checks.
Never creates pages, changes menus or publishes an unpublished page.
"""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import markdown

ROOT = Path(__file__).resolve().parents[2]
PAGE_DIR = ROOT / "policies" / "pages"
HANDLES = (
    "terms-of-service",
    "privacy-policy",
    "refund-policy",
    "shipping-policy",
    "payment",
    "contact-us",
)
API = "https://api.easystore.co/admin/v2/store/pages"
EXPECTED_DOMAIN = "cardboardcollective.easy.co"
REQUIRED_PHRASES = {
    "terms-of-service": ("15 minutes", "S$500", "HitPay", "statutory rights"),
    "privacy-policy": ("PDPA", "Data Protection Officer", "We do not sell personal data."),
    "refund-policy": ("statutory rights", "within 3 days", "14 business days"),
    "shipping-policy": ("S$500", "S$1,000", "0–5 working days"),
    "payment": ("HitPay", "PayNow only", "15 minutes"),
    "contact-us": ("202635416D", "contact@cardboard.sg", "8980 8075"),
}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def visible_text(html: str) -> str:
    parser = VisibleText()
    parser.feed(html)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def render_sources() -> dict[str, str]:
    actual = {p.stem for p in PAGE_DIR.glob("*.md")}
    if actual != set(HANDLES):
        raise ValueError(f"Footer page source handles differ: {sorted(actual ^ set(HANDLES))}")
    output = {}
    for handle in HANDLES:
        content = (PAGE_DIR / f"{handle}.md").read_text(encoding="utf-8").strip()
        if not content.startswith("## ") or content.count("\n## ") or content.count("\n### ") < (1 if handle not in ("payment", "contact-us") else 0):
            raise ValueError(f"Invalid heading hierarchy in {handle}")
        if "http://" in content or "<script" in content.lower():
            raise ValueError(f"Unsafe link or markup in {handle}")
        html = markdown.markdown(content, output_format="html5").strip()
        text = visible_text(html)
        if not all(phrase in text for phrase in REQUIRED_PHRASES[handle]):
            raise ValueError(f"Required policy facts missing from {handle}")
        if not html.startswith("<h2>") or html.count("<h2>") != 1:
            raise ValueError(f"Expected exactly one h2 in {handle}")
        output[handle] = html
    return output


def walk_objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_objects(child)


def page_list(payload) -> list[dict]:
    """Handle EasyStore's nested data/pages and pagination response shapes."""
    found = []
    seen = set()
    for obj in walk_objects(payload):
        handle = obj.get("handle")
        identifier = obj.get("id")
        if isinstance(handle, str) and handle in HANDLES and str(identifier).isdigit():
            if (handle, str(identifier)) not in seen:
                found.append(obj)
                seen.add((handle, str(identifier)))
    return found


def detail_page(payload, page_id: int) -> dict:
    candidates = [
        obj for obj in walk_objects(payload)
        if isinstance(obj.get("body_html"), str)
        and (str(obj.get("id", page_id)) == str(page_id))
    ]
    if len(candidates) != 1:
        raise ValueError(f"Could not uniquely read page body for id {page_id}")
    return candidates[0]


def is_published(page: dict, listing: dict | None = None) -> bool:
    for obj in (page, listing or {}):
        if "is_published" in obj:
            state = obj["is_published"]
            # 2 means scheduled, not currently published.
            return state is True or (type(state) is int and state == 1)
        if "published_at" in obj:
            return bool(obj["published_at"])
    return False


class Admin:
    def __init__(self) -> None:
        token = os.getenv("EASYSTORE_ADMIN_TOKEN", "").strip()
        if not token:
            raise RuntimeError("Missing EASYSTORE_ADMIN_TOKEN GitHub Actions secret")
        configured_domain = os.getenv("EASYSTORE_STORE_DOMAIN", EXPECTED_DOMAIN).strip()
        if "://" in configured_domain:
            configured_domain = urllib.parse.urlsplit(configured_domain).hostname or ""
        else:
            configured_domain = configured_domain.rstrip("/")
        if configured_domain != EXPECTED_DOMAIN:
            raise RuntimeError("Store domain mismatch; refusing to edit another store")
        pod = os.getenv("EASYSTORE_POD_ID", "1007")
        if not pod.isdecimal():
            raise RuntimeError("Invalid EASYSTORE_POD_ID")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "easystore-pod-id": pod,
            "easystore-source": "admin",
            "x-easystore-infra-default-domain": EXPECTED_DOMAIN,
            "x-easystore-infra-pod-id": pod,
            "x-easystore-infra-source": "admin",
            "User-Agent": "cc-footer-page-deploy/1",
        }

    def request(self, method: str, url: str, body: dict | None = None, key: str | None = None):
        headers = dict(self.headers)
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if key:
            headers["idempotency-key"] = f"phase1-dummy:web:{key}"
        request = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"Admin API {method} failed HTTP {response.status}")
                response_body = response.read(2_000_000).decode("utf-8")
                return json.loads(response_body) if response_body else {}
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Admin API {method} failed HTTP {exc.code}; no automatic retry") from None
        except urllib.error.URLError:
            raise RuntimeError(f"Admin API {method} network error; check state before retry") from None

    def read_page(self, page_id: int) -> dict:
        return detail_page(self.request("GET", f"{API}/{page_id}"), page_id)

    def find_six(self) -> dict[str, dict]:
        matches: dict[str, dict] = {}
        for number in range(1, 21):
            params = urllib.parse.urlencode({"page": number, "limit": 50})
            batch = page_list(self.request("GET", f"{API}?{params}"))
            for page in batch:
                handle = page["handle"]
                if handle in matches and str(matches[handle]["id"]) != str(page["id"]):
                    raise RuntimeError(f"Duplicate page handle: {handle}")
                matches[handle] = page
            if set(matches) == set(HANDLES):
                return matches
            if not batch:
                break
        raise RuntimeError(f"Expected 6 existing pages; missing: {', '.join(sorted(set(HANDLES) - set(matches)))}")


def read_targets(admin: Admin) -> dict[str, dict]:
    listing = admin.find_six()
    target = {}
    for handle in HANDLES:
        page_id = int(listing[handle]["id"])
        page = admin.read_page(page_id)
        if page.get("handle", handle) != handle:
            raise RuntimeError(f"Handle mismatch on {handle}")
        if not is_published(page, listing[handle]):
            raise RuntimeError(f"{handle} is not currently published; refusing to change its state")
        if not page.get("body_html") or not visible_text(page["body_html"]):
            raise RuntimeError(f"Missing existing content in {handle}; refusing overwrite")
        target[handle] = page
    return target


def snapshot(admin: Admin, target_html: dict[str, str], path: Path) -> None:
    pages = read_targets(admin)  # Entire six-page preflight before any writes.
    backup = {
        "version": 1,
        "store": EXPECTED_DOMAIN,
        "pages": [{
            "handle": handle,
            "id": int(pages[handle]["id"]),
            "name": pages[handle].get("name"),
            "is_published": pages[handle].get("is_published", 1),
            "body_html": pages[handle]["body_html"],
            "before_sha256": digest(pages[handle]["body_html"]),
            "after_sha256": digest(target_html[handle]),
        } for handle in HANDLES],
    }
    path.write_text(json.dumps(backup, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for entry in backup["pages"]:
        diff = "unchanged" if entry["before_sha256"] == entry["after_sha256"] else "update"
        print(f"PLAN {entry['handle']}: {diff}")


def apply(admin: Admin, target_html: dict[str, str], path: Path) -> None:
    backup = json.loads(path.read_text(encoding="utf-8"))
    if backup.get("store") != EXPECTED_DOMAIN or backup.get("version") != 1:
        raise RuntimeError("Invalid backup store/version")
    entries = backup["pages"]
    if [item["handle"] for item in entries] != list(HANDLES):
        raise RuntimeError("Backup does not contain exactly the six intended footer pages")
    current = read_targets(admin)
    # All optimistic checks before the first mutation. Never overwrite admin edits.
    for item in entries:
        handle = item["handle"]
        page = current[handle]
        if int(page["id"]) != item["id"] or digest(page["body_html"]) != item["before_sha256"]:
            raise RuntimeError(f"{handle} changed since backup; no writes performed")
        if digest(target_html[handle]) != item["after_sha256"]:
            raise RuntimeError(f"{handle} source changed since backup; no writes performed")
    for item in entries:
        handle = item["handle"]
        page = current[handle]
        if item["before_sha256"] == item["after_sha256"]:
            print(f"SKIP {handle}: unchanged")
            continue
        # Preserve metadata; only change body HTML. Keep the published flag true.
        body = {"id": item["id"], "body_html": target_html[handle], "is_published": True}
        for prop in ("name", "handle", "description", "navigation_handles"):
            if isinstance(page.get(prop), str):
                body[prop] = page[prop]
        key = "footer_pages_" + digest(f"{handle}:{item['after_sha256']}")[:24]
        admin.request("PUT", f"{API}/{item['id']}", body, key=key)
        actual = admin.read_page(item["id"])
        if not is_published(actual) or visible_text(actual["body_html"]) != visible_text(target_html[handle]):
            raise RuntimeError(f"Read-back failed for {handle}; investigate before retry")
        print(f"DEPLOYED {handle}: verified")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["validate", "plan", "apply"])
    parser.add_argument("--snapshot", type=Path, default=Path("footer-pages-backup.json"))
    args = parser.parse_args()
    target = render_sources()
    if args.mode == "validate":
        for handle, html in target.items():
            print(f"VALID {handle}: {len(html)} bytes HTML")
        return 0
    admin = Admin()
    if args.mode == "plan":
        snapshot(admin, target, args.snapshot)
    elif args.mode == "apply":
        apply(admin, target, args.snapshot)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
