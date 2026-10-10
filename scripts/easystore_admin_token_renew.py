#!/usr/bin/env python3
"""Renew a store-scoped EasyStore admin JWT, scoped to one GitHub environment.

No third-party Python packages required. Secrets stay in memory: no token files,
step outputs, request bodies, exception details or CLI output are logged.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit


AUTH_URL = "https://api.easystore.co/admin/v2/me/stores/auth"
VERIFY_URL = "https://api.easystore.co/admin/v2/store/themes"
SECRET_NAME = "EASYSTORE_ADMIN_TOKEN"
RENEW_BEFORE_SECONDS = 14 * 86400
MIN_NEW_LIFETIME_SECONDS = 20 * 86400


class RotationError(Exception):
    """Deliberately contains no upstream messages or credentials."""


def claims(jwt: str, *, require_exp: bool = True) -> dict:
    # Report only the reason a credential cannot be used, never its contents.
    parts = jwt.split(".")
    if len(parts) != 3:
        raise RotationError("EASYSTORE_ADMIN_TOKEN is not a three-part JWT (do not include 'Bearer '); seed this environment with its EasyStore admin session token.")
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error):
        raise RotationError("EASYSTORE_ADMIN_TOKEN contains an unreadable JWT payload.") from None
    if not isinstance(data, dict):
        raise RotationError("EASYSTORE_ADMIN_TOKEN does not contain JWT claims.")
    # Some existing administrator credentials may lack a standard exp claim.
    # Treat these as bootstrap-only credentials: attempt a single authenticated
    # exchange and require a well-formed, sufficiently long-lived replacement.
    exp = data.get("exp")
    # JWT NumericDate permits integer or floating-point seconds. Credentials
    # with absent or non-numeric expiration have *unknown* client-side
    # lifetime and must go through the authenticated EasyStore exchange.
    valid_exp = (type(exp) in (int, float) and
                 (type(exp) is int or math.isfinite(exp)))
    if not valid_exp:
        if require_exp:
            raise RotationError("EasyStore did not issue a replacement JWT with a valid expiry.")
        data["exp"] = None
    # Account-level admin JWTs have no 'sid'. EasyStore can exchange one for
    # the selected store's JWT via /me/stores/auth, verified before persistence.
    if "sid" in data and (not isinstance(data["sid"], (str, int)) or isinstance(data["sid"], bool) or not data["sid"]):
        raise RotationError("EASYSTORE_ADMIN_TOKEN has an invalid store identifier.")
    return data


def store_hostname(value: str) -> str:
    # GitHub vars may be hostnames or URLs (e.g. https://dev.easy.co/).
    # EasyStore's x-easystore-infra-default-domain header requires a hostname.
    try:
        parsed = urlsplit(value if "://" in value else "https://" + value)
        host = parsed.hostname
        if (parsed.scheme != "https" or not host or parsed.port or parsed.username
                or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError()
        if not all(label and label.replace("-", "").isalnum() for label in host.split(".")):
            raise ValueError()
        return host.lower()
    except ValueError:
        raise RotationError("EASYSTORE_STORE_DOMAIN must be an HTTPS store URL or bare hostname.") from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api_request(url: str, method: str, token: str, *, payload: dict | None = None, headers: dict | None = None) -> object:
    request_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "easystore-source": "admin",
        "x-easystore-infra-source": "admin",
        "easystore-browser": "{}",
        **(headers or {}),
    }
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    # Only report the fixed operation name and numeric HTTP status. In
    # particular, never print HTTPError.reason, bodies, headers or URLs:
    # upstream diagnostics may contain tokens or confidential store details.
    stage = "token exchange" if url == AUTH_URL else "admin API verification"
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=25) as response:
            if response.status != 200:
                raise RotationError(f"EasyStore {stage} returned HTTP {response.status}.")
            data = json.load(response)
        if not isinstance(data, (dict, list)):
            raise ValueError()
        return data
    except urllib.error.HTTPError as error:
        raise RotationError(f"EasyStore {stage} returned HTTP {error.code}.") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise RotationError(f"EasyStore {stage} connection failed.") from None
    except ValueError:
        raise RotationError(f"EasyStore {stage} returned invalid JSON.") from None


def rotate(token: str, store_code: str, domain: str, pod_id: str, *, force: bool = False, now: int | None = None) -> tuple[str, bool]:
    now = int(time.time()) if now is None else now
    old = claims(token, require_exp=False)
    old_expiry = old.get("exp")
    if old_expiry is not None and old_expiry <= now:
        raise RotationError("The admin JWT is already expired; manual reauthentication is required.")
    if old.get("sid") and old_expiry is not None and old_expiry - now > RENEW_BEFORE_SECONDS and not force:
        return token, False

    # The actual EasyStore admin frontend includes store routing headers on
    # *all* admin HTTP requests, including /me/stores/auth. Previously this
    # script omitted them from the exchange (but sent them on verification),
    # which can route a valid store JWT through the wrong API context.
    routing_headers = {
        "easystore-pod-id": pod_id,
        "x-easystore-infra-pod-id": pod_id,
        "x-easystore-infra-default-domain": store_hostname(domain),
    }
    result = api_request(AUTH_URL, "POST", token,
                         payload={"store_code": store_code}, headers=routing_headers)
    updated = result.get("token") if isinstance(result, dict) else None
    if not isinstance(updated, str):
        raise RotationError("EasyStore did not return a replacement JWT.")
    new = claims(updated)
    if not new.get("sid"):
        raise RotationError("EasyStore did not issue a store-scoped replacement JWT.")
    if (old.get("sid") and new["sid"] != old["sid"]) or updated == token:
        raise RotationError("Renewal changed store identity or did not replace the token.")
    if (old_expiry is not None and new["exp"] <= old_expiry) or new["exp"] - now < MIN_NEW_LIFETIME_SECONDS:
        raise RotationError("Replacement JWT did not extend validity sufficiently.")

    # Server-side verification both authenticates the new JWT and verifies the
    # same store's administrative API works before any secret is overwritten.
    api_request(VERIFY_URL, "GET", updated, headers=routing_headers)
    return updated, True


def sync_cloudflare(token: str, env: dict[str, str]) -> None:
    worker = env.get("EASYSTORE_MCP_WORKER_NAME", "")
    if not worker:
        return
    account, secret = env.get("CLOUDFLARE_ACCOUNT_ID", ""), env.get("CLOUDFLARE_API_TOKEN", "")
    if not account or not secret:
        raise RotationError("Cloudflare Worker synchronization configured without Cloudflare credentials.")
    url = (f"https://api.cloudflare.com/client/v4/accounts/{quote(account, safe='')}"
           f"/workers/scripts/{quote(worker, safe='')}/secrets")
    request = urllib.request.Request(url, method="PUT", headers={
        "Authorization": f"Bearer {secret}", "Content-Type": "application/json"
    }, data=json.dumps({"name": SECRET_NAME, "type": "secret_text", "text": token}).encode("utf-8"))
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            result = json.load(response)
            if response.status != 200 or not result.get("success"):
                raise RotationError("Cloudflare rejected the updated Worker secret.")
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        raise RotationError("Cloudflare Worker secret update failed.") from None


def sync_github(token: str, deployment_env: str, repo: str, gh_token: str) -> None:
    if not gh_token:
        raise RotationError("EASYSTORE_ROTATION_GH_TOKEN is missing for this environment.")
    try:
        subprocess.run(
            ["gh", "secret", "set", SECRET_NAME, "--env", deployment_env, "--repo", repo],
            input=token, text=True, env={**os.environ, "GH_TOKEN": gh_token},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=30, check=True,
        )
    except (subprocess.SubprocessError, OSError):
        raise RotationError("Could not write the selected GitHub environment secret.") from None


def main(argv: list[str] | None = None, environ: dict[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("dev", "prod"), required=True)
    args = parser.parse_args(argv)
    env = dict(os.environ if environ is None else environ)
    target = args.environment
    dry_run = env.get("DRY_RUN", "false").lower() == "true"
    force = env.get("FORCE_RENEWAL", "false").lower() == "true"
    try:
        if env.get("GITHUB_REF") != "refs/heads/main":
            raise RotationError("Rotation is permitted from main only.")
        required = ("EASYSTORE_ADMIN_TOKEN", "EASYSTORE_STORE_CODE", "EASYSTORE_STORE_DOMAIN", "EASYSTORE_POD_ID", "GITHUB_REPOSITORY")
        if any(not env.get(key) for key in required):
            raise RotationError("Missing required environment-specific EasyStore/GitHub configuration.")
        if target != env.get("DEPLOYMENT_ENV"):
            raise RotationError("Selected GitHub job environment does not match the renewal target.")
        worker = env.get("EASYSTORE_MCP_WORKER_NAME")
        if not dry_run and (not env.get("GH_TOKEN") or (worker and (not env.get("CLOUDFLARE_ACCOUNT_ID") or not env.get("CLOUDFLARE_API_TOKEN")))):
            raise RotationError("Missing GitHub rotation credential or configured Cloudflare Worker credential.")
        renewed, changed = rotate(env["EASYSTORE_ADMIN_TOKEN"], env["EASYSTORE_STORE_CODE"],
                                  env["EASYSTORE_STORE_DOMAIN"], env["EASYSTORE_POD_ID"], force=force)
        if not changed:
            print(f"{target}: healthy; renewal not yet due.")
        elif dry_run:
            print(f"{target}: renewal and read-only API verification passed (dry-run; no secrets updated).")
        else:
            # Worker first so a failed GitHub write leaves the older GitHub
            # credential due for renewal on the next scheduled retry.
            sync_cloudflare(renewed, env)
            sync_github(renewed, target, env["GITHUB_REPOSITORY"], env["GH_TOKEN"])
            print(f"{target}: renewed and synchronized environment secret" + (" and Worker." if worker else "."))
        return 0
    except RotationError as exc:
        print(f"::error::{target}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
