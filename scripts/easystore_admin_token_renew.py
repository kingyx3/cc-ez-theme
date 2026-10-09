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
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote


AUTH_URL = "https://api.easystore.co/admin/v2/me/stores/auth"
VERIFY_URL = "https://api.easystore.co/admin/v2/store/themes"
SECRET_NAME = "EASYSTORE_ADMIN_TOKEN"
RENEW_BEFORE_SECONDS = 14 * 86400
MIN_NEW_LIFETIME_SECONDS = 20 * 86400


class RotationError(Exception):
    """Deliberately contains no upstream messages or credentials."""


def claims(jwt: str) -> dict:
    try:
        parts = jwt.split(".")
        if len(parts) != 3:
            raise ValueError()
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        if not isinstance(data, dict) or not isinstance(data.get("sid"), (str, int)) or not data.get("sid"):
            raise ValueError()
        if not isinstance(data.get("exp"), int) or isinstance(data["exp"], bool):
            raise ValueError()
        return data
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, binascii.Error):
        raise RotationError("Invalid store-scoped JWT; reauthenticate manually.") from None


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
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=25) as response:
            if response.status != 200:
                raise RotationError("EasyStore authentication/verification returned an unexpected status.")
            data = json.load(response)
        if not isinstance(data, (dict, list)):
            raise ValueError()
        return data
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        raise RotationError("EasyStore authentication/verification failed; check the workflow status and credentials.") from None


def rotate(token: str, store_code: str, domain: str, pod_id: str, *, force: bool = False, now: int | None = None) -> tuple[str, bool]:
    now = int(time.time()) if now is None else now
    old = claims(token)
    if old["exp"] <= now:
        raise RotationError("The admin JWT is already expired; manual reauthentication is required.")
    if old["exp"] - now > RENEW_BEFORE_SECONDS and not force:
        return token, False

    result = api_request(AUTH_URL, "POST", token, payload={"store_code": store_code})
    updated = result.get("token")
    if not isinstance(result, dict) or not isinstance(updated, str):
        raise RotationError("EasyStore did not return a replacement JWT.")
    new = claims(updated)
    if new["sid"] != old["sid"] or updated == token:
        raise RotationError("Renewal changed store identity or did not replace the token.")
    if new["exp"] <= old["exp"] or new["exp"] - now < MIN_NEW_LIFETIME_SECONDS:
        raise RotationError("Replacement JWT did not extend validity sufficiently.")

    # Server-side verification both authenticates the new JWT and verifies the
    # same store's administrative API works before any secret is overwritten.
    api_request(VERIFY_URL, "GET", updated, headers={
        "easystore-pod-id": pod_id,
        "x-easystore-infra-pod-id": pod_id,
        "x-easystore-infra-default-domain": domain,
    })
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
