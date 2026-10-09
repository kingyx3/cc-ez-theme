"""Offline tests; no live token or service calls."""
from __future__ import annotations

import base64
import contextlib
import io
import json
import subprocess
import urllib.error
import unittest
from unittest.mock import MagicMock, patch

from scripts import easystore_admin_token_renew as renewal

NOW = 1_800_000_000


def jwt(sid: str | None = "store-123", exp: int | None = NOW + 10 * 86400, iat: int = NOW - 100) -> str:
    fields = {"iat": iat}
    if exp is not None:
        fields["exp"] = exp
    if sid is not None:
        fields["sid"] = sid
    payload = base64.urlsafe_b64encode(json.dumps(fields).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class ClaimsTest(unittest.TestCase):
    def test_store_identity_and_expiry_required(self):
        self.assertEqual(renewal.claims(jwt())["sid"], "store-123")
        self.assertNotIn("sid", renewal.claims(jwt(sid=None)))
        self.assertIsNone(renewal.claims(jwt(exp=None), require_exp=False)["exp"])
        with self.assertRaisesRegex(renewal.RotationError, "replacement JWT with a valid expiry"):
            renewal.claims(jwt(exp=None))
        for invalid in ["no.jwt", "a.bad=.z", "a." + base64.urlsafe_b64encode(b'{}').decode() + ".z",
                        jwt(sid=""), jwt(exp="not-an-int"), jwt(exp=True)]:
            with self.subTest(invalid=invalid[:8]), self.assertRaises(renewal.RotationError):
                renewal.claims(invalid)

    def test_safe_validation_errors_do_not_include_credential(self):
        with self.assertRaises(renewal.RotationError) as caught:
            renewal.claims("Bearer secret-value")
        self.assertIn("three-part", str(caught.exception))
        self.assertNotIn("secret-value", str(caught.exception))

    def test_hostname_normalization_and_rejects_unsafe_url(self):
        self.assertEqual(renewal.store_hostname("https://cardboardcollectivedev-2.easy.co/"),
                         "cardboardcollectivedev-2.easy.co")
        self.assertEqual(renewal.store_hostname("DEV.easy.co"), "dev.easy.co")
        for invalid in ("http://dev.easy.co", "https://dev.easy.co/somewhere", "https://dev.easy.co?auth=1",
                        "https://user:pass@dev.easy.co", "https://dev.easy.co:1234", "https://dev.easy.co#fragment"):
            with self.subTest(value=invalid), self.assertRaises(renewal.RotationError):
                renewal.store_hostname(invalid)


class RenewTest(unittest.TestCase):
    def setUp(self):
        self.old = jwt()
        self.new = jwt(exp=NOW + 31 * 86400, iat=NOW + 20)

    def test_not_due_no_network(self):
        with patch.object(renewal, "api_request") as http:
            got, changed = renewal.rotate(jwt(exp=NOW + 20 * 86400), "code", "store.easy.co", "1007", now=NOW)
        self.assertFalse(changed)
        self.assertFalse(http.called)
        self.assertEqual(got, jwt(exp=NOW + 20 * 86400))

    def test_renewal_checks_same_store_and_verifies_admin_api(self):
        with patch.object(renewal, "api_request", side_effect=[{"token": self.new}, {"themes": []}]) as http:
            got, changed = renewal.rotate(self.old, "dev-code", "dev.easy.co", "111", now=NOW)
        self.assertTrue(changed)
        self.assertEqual(got, self.new)
        self.assertEqual(http.call_args_list[0].args, (renewal.AUTH_URL, "POST", self.old))
        self.assertEqual(http.call_args_list[0].kwargs["payload"], {"store_code": "dev-code"})
        self.assertEqual(http.call_args_list[1].args, (renewal.VERIFY_URL, "GET", self.new))
        self.assertEqual(http.call_args_list[1].kwargs["headers"]["x-easystore-infra-default-domain"], "dev.easy.co")


    def test_user_scoped_admin_token_can_bootstrap_store_token(self):
        # User-level admin JWTs are valid at login before selecting a store.
        # They must be exchanged even when the 14-day renewal threshold has not
        # been reached; after exchange the workflow persists a store-scoped JWT.
        user_token = jwt(sid=None, exp=NOW + 25 * 86400)
        with patch.object(renewal, "api_request", side_effect=[{"token": self.new}, {"themes": []}]) as http:
            updated, changed = renewal.rotate(
                user_token, "dev-store-code", "https://dev.easy.co/", "2", now=NOW
            )
        self.assertTrue(changed)
        self.assertEqual(updated, self.new)
        self.assertEqual(http.call_args_list[0].kwargs["payload"], {"store_code": "dev-store-code"})
        self.assertEqual(http.call_args_list[1].kwargs["headers"]["x-easystore-infra-default-domain"], "dev.easy.co")

    def test_existing_jwt_without_exp_is_exchanged_and_verified(self):
        # The absence of a client-visible exp must not stop an authenticated
        # exchange before the EasyStore API can validate this credential.
        legacy = jwt(sid="store-123", exp=None)
        with patch.object(renewal, "api_request", side_effect=[{"token": self.new}, {"themes": []}]) as http:
            renewed, changed = renewal.rotate(legacy, "dev", "https://dev.easy.co/", "2", now=NOW)
        self.assertTrue(changed)
        self.assertEqual(renewed, self.new)
        self.assertEqual(http.call_count, 2)

    def test_user_jwt_without_exp_is_exchanged(self):
        legacy = jwt(sid=None, exp=None)
        with patch.object(renewal, "api_request", side_effect=[{"token": self.new}, {"themes": []}]):
            self.assertEqual(renewal.rotate(legacy, "dev", "dev.easy.co", "2", now=NOW)[0], self.new)

    def test_unknown_input_exp_is_exchanged_but_output_must_have_valid_exp(self):
        for bad_exp in ("unknown", True, float("nan")):
            with self.subTest(exp=str(bad_exp)), patch.object(
                renewal, "api_request", side_effect=[{"token": self.new}, {"themes": []}]
            ) as http:
                renewed, changed = renewal.rotate(jwt(exp=bad_exp), "dev", "dev.easy.co", "2", now=NOW)
                self.assertTrue(changed)
                self.assertEqual(renewed, self.new)
                self.assertEqual(http.call_count, 2)

    def test_float_numericdate_exp_is_valid(self):
        self.assertEqual(renewal.claims(jwt(exp=float(NOW + 40 * 86400)))["exp"],
                         float(NOW + 40 * 86400))

    def test_exchange_rejects_new_jwt_without_exp_without_secret_updates(self):
        legacy = jwt(exp=None)
        with patch.object(renewal, "api_request", return_value={"token": jwt(exp=None)}) as http:
            with self.assertRaisesRegex(renewal.RotationError, "replacement JWT with a valid expiry"):
                renewal.rotate(legacy, "dev", "dev.easy.co", "2", now=NOW)
            http.assert_called_once()

    def test_bootstrap_still_rejects_non_store_replacement(self):
        user = jwt(sid=None)
        with patch.object(renewal, "api_request", return_value={"token": jwt(sid=None, exp=NOW + 31 * 86400)}):
            with self.assertRaisesRegex(renewal.RotationError, "store-scoped replacement"):
                renewal.rotate(user, "dev-code", "dev.easy.co", "2", now=NOW)

    def test_forced_renewal(self):
        with patch.object(renewal, "api_request", side_effect=[{"token": self.new}, []]):
            self.assertTrue(renewal.rotate(jwt(exp=NOW + 25 * 86400), "code", "host", "1007", force=True, now=NOW)[1])

    def test_rejects_expired_token(self):
        with self.assertRaisesRegex(renewal.RotationError, "expired"):
            renewal.rotate(jwt(exp=NOW), "code", "host", "1007", now=NOW)

    def test_invalid_replacements_never_propagate(self):
        cases = [None, "junk", self.old, jwt(sid="another", exp=NOW+31*86400),
                 jwt(exp=NOW + 11 * 86400), jwt(exp=NOW + 15 * 86400)]
        for token in cases:
            with self.subTest(token=token and token[:8]), patch.object(renewal, "api_request", return_value={"token": token}) as http:
                with self.assertRaises(renewal.RotationError):
                    renewal.rotate(self.old, "code", "host", "1007", now=NOW)
                http.assert_called_once()

    def test_upstream_error_aborts(self):
        with patch.object(renewal, "api_request", side_effect=renewal.RotationError("upstream unavailable")):
            with self.assertRaises(renewal.RotationError):
                renewal.rotate(self.old, "code", "host", "1007", now=NOW)



class HttpDiagnosticsTest(unittest.TestCase):
    def test_token_exchange_http_401_is_safe_and_precise(self):
        # Never surface the upstream reason, response body, request URL, or JWT.
        upstream = urllib.error.HTTPError(
            renewal.AUTH_URL, 401, "contains-a-secret", {"Authorization": "Bearer secret"}, None
        )
        with patch.object(renewal.urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = upstream
            with self.assertRaises(renewal.RotationError) as caught:
                renewal.api_request(renewal.AUTH_URL, "POST", "secret", payload={"store_code": "dev"})
        self.assertEqual(str(caught.exception), "EasyStore token exchange returned HTTP 401.")
        self.assertNotIn("secret", str(caught.exception))
        self.assertNotIn("dev", str(caught.exception))

    def test_admin_api_verification_http_403_identifies_stage(self):
        upstream = urllib.error.HTTPError(renewal.VERIFY_URL, 403, "secret", {}, None)
        with patch.object(renewal.urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = upstream
            with self.assertRaisesRegex(renewal.RotationError, "admin API verification returned HTTP 403"):
                renewal.api_request(renewal.VERIFY_URL, "GET", "secret")

    def test_transport_error_is_safe_and_stage_specific(self):
        with patch.object(renewal.urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = urllib.error.URLError("https://secret.invalid")
            with self.assertRaises(renewal.RotationError) as caught:
                renewal.api_request(renewal.AUTH_URL, "POST", "secret", payload={"store_code": "dev"})
        self.assertEqual(str(caught.exception), "EasyStore token exchange connection failed.")

    def test_invalid_json_does_not_echo_payload(self):
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        with patch.object(renewal.urllib.request, "build_opener") as opener, patch.object(
            renewal.json, "load", side_effect=ValueError("response had secret JWT")
        ):
            opener.return_value.open.return_value = response
            with self.assertRaises(renewal.RotationError) as caught:
                renewal.api_request(renewal.VERIFY_URL, "GET", "secret")
        self.assertEqual(str(caught.exception), "EasyStore admin API verification returned invalid JSON.")

    def test_non_200_response_reports_status_without_content(self):
        response = MagicMock(status=429)
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        with patch.object(renewal.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value = response
            with self.assertRaisesRegex(renewal.RotationError, "token exchange returned HTTP 429"):
                renewal.api_request(renewal.AUTH_URL, "POST", "secret", payload={"store_code": "dev"})


class SecretSyncTest(unittest.TestCase):
    def test_github_only_targets_selected_environment_and_hides_token(self):
        with patch.object(renewal.subprocess, "run") as run:
            renewal.sync_github("secret-token", "dev", "kingyx3/cc-ez-theme", "gh-credential")
        kwargs = run.call_args.kwargs
        self.assertEqual(run.call_args.args[0], ["gh", "secret", "set", "EASYSTORE_ADMIN_TOKEN", "--env", "dev", "--repo", "kingyx3/cc-ez-theme"])
        self.assertEqual(kwargs["input"], "secret-token")
        self.assertEqual(kwargs["env"]["GH_TOKEN"], "gh-credential")
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        self.assertNotIn("secret-token", repr(run.call_args.args[0]))

    def test_github_failure_is_generic(self):
        with patch.object(renewal.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["gh"], stderr="secret-token")):
            with self.assertRaisesRegex(renewal.RotationError, "Could not write") as failure:
                renewal.sync_github("secret-token", "prod", "repo", "pat")
        self.assertNotIn("secret-token", str(failure.exception))

    def test_worker_optional_and_requires_credentials(self):
        self.assertIsNone(renewal.sync_cloudflare("jwt", {}))
        with self.assertRaisesRegex(renewal.RotationError, "Cloudflare credentials"):
            renewal.sync_cloudflare("jwt", {"EASYSTORE_MCP_WORKER_NAME": "worker"})

    def test_worker_api_updates_only_its_named_secret(self):
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        with patch.object(renewal.urllib.request, "build_opener") as opener, patch.object(renewal.json, "load", return_value={"success": True}):
            opener.return_value.open.return_value = response
            renewal.sync_cloudflare("fresh-token", {"EASYSTORE_MCP_WORKER_NAME": "prod-worker", "CLOUDFLARE_ACCOUNT_ID": "acct", "CLOUDFLARE_API_TOKEN": "cf-token"})
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.get_method(), "PUT")
        self.assertEqual(json.loads(request.data), {"name": "EASYSTORE_ADMIN_TOKEN", "type": "secret_text", "text": "fresh-token"})
        self.assertTrue(request.full_url.endswith("/workers/scripts/prod-worker/secrets"))

    def test_worker_failure_does_not_print_remote_details(self):
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        with patch.object(renewal.urllib.request, "build_opener") as opener, patch.object(renewal.json, "load", return_value={"success": False, "secret": "jwt"}):
            opener.return_value.open.return_value = response
            with self.assertRaisesRegex(renewal.RotationError, "Cloudflare rejected"):
                renewal.sync_cloudflare("jwt", {"EASYSTORE_MCP_WORKER_NAME": "worker", "CLOUDFLARE_ACCOUNT_ID": "id", "CLOUDFLARE_API_TOKEN": "key"})


class MainTest(unittest.TestCase):
    def setUp(self):
        self.env = {"GITHUB_REF": "refs/heads/main", "GITHUB_REPOSITORY": "kingyx3/cc-ez-theme", "DEPLOYMENT_ENV": "dev", "EASYSTORE_STORE_CODE": "dev-code", "EASYSTORE_STORE_DOMAIN": "dev.easy.co", "EASYSTORE_POD_ID": "123", "EASYSTORE_ADMIN_TOKEN": jwt(), "GH_TOKEN": "pat", "DRY_RUN": "false"}

    def execute(self, env=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return renewal.main(["--environment", "dev"], self.env if env is None else env)

    def test_dry_run_does_not_write_secrets(self):
        with patch.object(renewal, "rotate", return_value=(jwt(), True)), patch.object(renewal, "sync_github") as gh, patch.object(renewal, "sync_cloudflare") as cf:
            self.assertEqual(self.execute({**self.env, "DRY_RUN": "true", "GH_TOKEN": ""}), 0)
            gh.assert_not_called()
            cf.assert_not_called()

    def test_live_writes_cloudflare_first_then_only_dev_gh_secret(self):
        calls = []
        with patch.object(renewal, "rotate", return_value=("new", True)), patch.object(renewal, "sync_cloudflare", side_effect=lambda *a: calls.append("worker")), patch.object(renewal, "sync_github", side_effect=lambda *a: calls.append(a[1])):
            self.assertEqual(self.execute(), 0)
        self.assertEqual(calls, ["worker", "dev"])

    def test_never_writes_when_not_due(self):
        with patch.object(renewal, "rotate", return_value=(jwt(), False)), patch.object(renewal, "sync_github") as gh:
            self.assertEqual(self.execute(), 0)
            gh.assert_not_called()

    def test_fails_closed_for_mismatch_and_non_main(self):
        for overlay in [{"DEPLOYMENT_ENV": "prod"}, {"GITHUB_REF": "refs/heads/some-pr"}, {"EASYSTORE_STORE_CODE": ""}, {"GH_TOKEN": ""}, {"EASYSTORE_MCP_WORKER_NAME": "worker"}]:
            with self.subTest(overlay=overlay), patch.object(renewal, "rotate") as rotate:
                self.assertEqual(self.execute({**self.env, **overlay}), 1)
                rotate.assert_not_called()

    def test_worker_failure_never_writes_github(self):
        with patch.object(renewal, "rotate", return_value=("new", True)), patch.object(renewal, "sync_cloudflare", side_effect=renewal.RotationError("Worker failed")), patch.object(renewal, "sync_github") as gh:
            self.assertEqual(self.execute(), 1)
            gh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
