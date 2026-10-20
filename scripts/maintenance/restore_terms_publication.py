#!/usr/bin/env python3
"""One-time recovery of Terms of Service accidentally unpublished by a page PUT.

Only permitted change is changing is_published from 0 to 1 for exact existing
terms-of-service page; preserve the current page content and metadata.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request
import urllib.error

HOST = "cardboardcollective.easy.co"
BASE = "https://api.easystore.co/admin/v2/store/pages"
HANDLE = "terms-of-service"


def walk(data):
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from walk(value)
    elif isinstance(data, list):
        for value in data:
            yield from walk(value)


class Client:
    def __init__(self):
        token = os.environ.get("EASYSTORE_ADMIN_TOKEN", "")
        pod = os.environ.get("EASYSTORE_POD_ID", "1007")
        value = os.environ.get("EASYSTORE_STORE_DOMAIN", HOST).strip()
        hostname = urllib.parse.urlsplit(value).hostname if "://" in value else value.strip("/")
        if not token or hostname != HOST or not pod.isdecimal():
            raise RuntimeError("Missing token or incorrect store configuration")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "easystore-pod-id": pod,
            "easystore-source": "admin",
            "x-easystore-infra-default-domain": HOST,
            "x-easystore-infra-pod-id": pod,
            "x-easystore-infra-source": "admin",
        }

    def call(self, method, url, body=None):
        headers = dict(self.headers)
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["idempotency-key"] = "phase1-dummy:web:recover_terms_publication_20261020"
            data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(1500000)
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Admin API {method} returned HTTP {exc.code}") from None

    def target(self):
        candidates = {}
        for page_num in range(1, 21):
            result = self.call("GET", f"{BASE}?page={page_num}&limit=50")
            matches = [d for d in walk(result) if d.get("handle") == HANDLE and str(d.get("id", "")).isdigit()]
            for match in matches:
                candidates[int(match["id"])] = match
            if len(candidates) == 1:
                break
            if not matches:
                break
        if len(candidates) != 1:
            raise RuntimeError(f"Expected precisely one Terms page ID; found {len(candidates)}")
        page_id, _ = next(iter(candidates.items()))
        detail = self.call("GET", f"{BASE}/{page_id}")
        matches = [d for d in walk(detail) if d.get("handle") == HANDLE and isinstance(d.get("body_html"), str)]
        if len(matches) != 1:
            raise RuntimeError("Page detail not unique or missing HTML")
        page = matches[0]
        if int(page.get("id", page_id)) != page_id:
            raise RuntimeError("Page ID mismatch")
        return page_id, page


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["backup", "restore"])
    p.add_argument("--snapshot", type=Path, default=Path("terms-publication-recovery.json"))
    a = p.parse_args()
    client = Client()
    page_id, page = client.target()
    published = page.get("is_published")
    html = page["body_html"]
    if not html or len(html) < 200:
        raise RuntimeError("Refusing empty or short page body")
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
    if a.command == "backup":
        if published not in (0, False):
            raise RuntimeError(f"Page publication status changed; expected unpublished, got {published!r}")
        a.snapshot.write_text(json.dumps({"id":page_id,"handle":HANDLE,"body_html":html,"sha256":digest,"is_published":published},indent=2) + "\n",encoding="utf-8")
        print(f"BACKUP Terms id={page_id}, published={published}, sha256={digest}")
        return
    prior = json.loads(a.snapshot.read_text(encoding="utf-8"))
    if prior["id"] != page_id or prior["handle"] != HANDLE or prior["sha256"] != digest:
        raise RuntimeError("Page changed since backup; refusing restore")
    if published not in (0, False):
        raise RuntimeError(f"Page publication state changed; got {published!r}")
    # Match the EasyStore admin page editor: a publish request must include
    # published_at AND its Unix timestamp, not only is_published.
    now = datetime.now(timezone.utc)
    body = {
        "id":page_id,
        "body_html":html,
        "is_published":True,
        "published_at":now.isoformat(timespec="milliseconds").replace("+00:00","Z"),
        "published_timestamp":str(int(now.timestamp())),
    }
    for prop in ("name","handle","description","navigation_handles"):
        if isinstance(page.get(prop),str):
            body[prop] = page[prop]
    client.call("PUT",f"{BASE}/{page_id}",body)
    _, updated = client.target()
    status = updated.get("is_published")
    if status not in (1, True):
        raise RuntimeError(f"Restore did not publish Terms: is_published={status!r}")
    if hashlib.sha256(updated["body_html"].encode("utf-8")).hexdigest() != digest:
        raise RuntimeError("Page HTML changed unexpectedly after publication restoration")
    print(f"RESTORED Terms id={page_id}, is_published={status!r}; body preserved")


if __name__ == "__main__":
    main()
