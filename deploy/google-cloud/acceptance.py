#!/usr/bin/env python3
"""Public HTTPS smoke checks for the RS deployment of new-api (QuantumNous).

Run only after deploy.py bootstrap and publish. The service URL is obtained from
the selected project's Cloud Run metadata, never a caller-supplied host. Default
mode retains one ordinary internal-test account in Secret Manager, creates and
deletes one narrowly scoped test API key, and never calls an upstream or payment
API. It saves a short-lived session under ignored .local-tests/ with mode 0600.

--verify-only does not create accounts, keys or secrets (login creates sessions).
--persistence-check performs only GETs using the previously saved session and
requires a different ready revision; run within 15 minutes of the initial test.
--self-test is completely offline and makes no application or Google API calls.
"""

import argparse
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from deploy import Deployment, DeploymentError, ROOT


class AcceptanceError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise AcceptanceError(message)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # In particular, do not forward application passwords/bearers to a
        # redirect target, even if a deployed application is misconfigured.
        raise AcceptanceError("HTTP redirect refused; check the deployed service")


class FrontendAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.styles = []
        self.root = False

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if attrs.get("id") == "root":
            self.root = True
        if tag == "script" and attrs.get("src"):
            self.scripts.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet" and attrs.get("href"):
            self.styles.append(attrs["href"])


class Acceptance:
    def __init__(self, args, deployment=None):
        self.args = args
        self.deployment = deployment or Deployment(args)
        self.checks = []
        self.opener = urllib.request.build_opener(NoRedirect())
        self.url = None
        self.revision = None
        self.state_path = ROOT / ".local-tests" / "google-cloud" / "acceptance-state.json"

    def passed(self, name):
        self.checks.append({"check": name, "status": "passed"})

    def service_target(self):
        info = self.deployment.service_info()
        require(isinstance(info, dict), "Cloud Run service is missing")
        require(info.get("metadata", {}).get("name") == self.args.service,
                "Cloud Run metadata returned a different service")
        require(any(item.get("type") == "Ready" and item.get("status") == "True"
                    for item in info.get("status", {}).get("conditions", [])),
                "Cloud Run service is not ready")
        self.url = info.get("status", {}).get("url", "")
        parsed = urllib.parse.urlsplit(self.url)
        require(parsed.scheme == "https" and parsed.hostname
                and parsed.hostname.endswith(".run.app")
                and parsed.netloc == parsed.hostname and not parsed.path
                and not parsed.query and not parsed.fragment,
                "Refusing a non-canonical Cloud Run HTTPS URL")
        self.revision = info["status"].get("latestReadyRevisionName")
        require(self.revision, "Cloud Run ready revision is missing")
        traffic = info["status"].get("traffic", [])
        require(sum(int(item.get("percent", 0)) for item in traffic) == 100
                and sum(int(item.get("percent", 0)) for item in traffic
                        if item.get("revisionName") == self.revision) == 100,
                "Ready revision is not receiving all public traffic; refusing a misleading persistence test")
        self.passed("exact project/service HTTPS target obtained from Cloud Run")

    def request(self, path, method="GET", body=None, token=None, *, raw=False):
        parsed = urllib.parse.urlsplit(path)
        require(path.startswith("/") and not path.startswith("//")
                and not parsed.scheme and not parsed.netloc and not parsed.fragment,
                "Refusing an external or malformed application path")
        headers = {"Accept": "application/json", "Origin": self.url}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.url + path, method=method, headers=headers,
            data=None if body is None else json.dumps(body).encode(),
        )
        try:
            response = self.opener.open(request, timeout=180)
        except urllib.error.HTTPError as error:
            response = error
        except (urllib.error.URLError, TimeoutError, OSError):
            raise AcceptanceError("Application request failed; network details suppressed") from None
        with response:
            data = response.read(16 * 1024 * 1024 + 1)
            require(len(data) <= 16 * 1024 * 1024, "Application response exceeds test limit")
            code = response.code
            kind = response.headers.get("Content-Type", "").lower()
        if raw:
            return code, data, kind
        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None
        return code, payload, kind

    def success(self, path, method="GET", body=None, token=None):
        code, payload, _ = self.request(path, method, body, token)
        require(code == 200 and isinstance(payload, dict) and payload.get("success") is True,
                f"Application API failed: {method} {path.split('?')[0]} (HTTP {code}); response suppressed")
        return payload.get("data")

    def rejected(self, path, token=None):
        code, payload, _ = self.request(path, token=token)
        require(code in (401, 403) or (code == 200 and isinstance(payload, dict)
                                      and payload.get("success") is False),
                f"Expected authorization rejection: {path.split('?')[0]} (HTTP {code})")

    def login(self, credentials, expected_role):
        require(isinstance(credentials, dict) and isinstance(credentials.get("username"), str)
                and isinstance(credentials.get("password"), str), "Credential secret has invalid structure")
        data = self.success("/api/user/login", "POST", {
            "username": credentials["username"], "password": credentials["password"],
        })
        require(isinstance(data, dict) and isinstance(data.get("access_token"), str)
                and data["access_token"] and data.get("user", {}).get("role") == expected_role,
                "Login did not return the expected role and session")
        return data["access_token"], data["user"]

    def public_checks(self):
        setup = self.success("/api/setup")
        status = self.success("/api/status")
        require(isinstance(setup, dict) and setup.get("status") is True,
                "Application is not initialized; refusing account tests")
        require(isinstance(status, dict) and status.get("register_enabled") is False
                and status.get("password_register_enabled") is False,
                "Public registration must remain disabled")
        self.passed("public HTTPS status, completed setup and disabled public registration")
        for path in ("/api/user/self", "/api/channel/?p=1&page_size=1", "/v1/models"):
            self.rejected(path)
        self.passed("anonymous user, administrator and relay APIs rejected")
        code, html, kind = self.request("/", raw=True)
        require(code == 200 and "text/html" in kind, "Homepage HTML unavailable")
        assets = FrontendAssets()
        assets.feed(html.decode("utf-8"))
        require(assets.root and assets.scripts and assets.styles
                and len(assets.scripts) <= 12 and len(assets.styles) <= 12,
                "Homepage does not contain the production frontend shell and assets")
        for href, expected_types in [
            *[(src, ("javascript", "ecmascript")) for src in assets.scripts],
            *[(src, ("text/css",)) for src in assets.styles],
        ]:
            url = urllib.parse.urlsplit(urllib.parse.urljoin(self.url + "/", href))
            require(f"{url.scheme}://{url.netloc}" == self.url and not url.fragment,
                    "Frontend asset is not on the verified Cloud Run origin")
            asset_path = url.path + ("?" + url.query if url.query else "")
            code, data, kind = self.request(asset_path, raw=True)
            require(code == 200 and data and any(item in kind for item in expected_types),
                    "Production frontend JavaScript/CSS asset unavailable or wrong content type")
        self.passed("production homepage and same-origin JavaScript/CSS assets")

    def ordinary_session(self, admin_token):
        name = f"{self.args.service}-test-login"
        users = self.success("/api/user/search?keyword=rstest&p=1&page_size=100", token=admin_token)
        require(isinstance(users, dict) and isinstance(users.get("items"), list),
                "Administrator user search returned an invalid result")
        matches = [user for user in users["items"] if user.get("username") == "rstest"]
        require(len(matches) <= 1, "Multiple internal-test users found; stop for review")
        existing = matches[0] if matches else None
        secret_exists = any(item["name"].rsplit("/", 1)[-1] == name
                            for item in self.deployment.gc("secrets", "list"))
        require(not existing or secret_exists,
                "rstest already exists without its credential secret; refusing to reset its password")
        require(not self.args.verify_only or (existing and secret_exists),
                "Read-only verification requires the previously created internal-test account and secret")
        if not secret_exists:
            credentials, _ = self.deployment.secret(name, lambda: json.dumps({
                "username": "rstest", "password": secrets.token_urlsafe(15),
            }))
        else:
            credentials, _ = self.deployment.secret(name)
        credentials = json.loads(credentials)
        require(credentials.get("username") == "rstest" and isinstance(credentials.get("password"), str)
                and len(credentials["password"]) == 20, "Internal-test credential secret is not the expected account")
        if existing:
            require(existing.get("role") == 1 and existing.get("status") == 1,
                    "Existing rstest is not an enabled ordinary account; refusing to change it")
        else:
            self.success("/api/user/", "POST", {**credentials, "display_name": "RS internal test", "role": 1}, admin_token)
        # A failed login intentionally stops: no password reset or account replacement.
        token, user = self.login(credentials, 1)
        require(user.get("username") == "rstest" and (not existing or user["id"] == existing["id"]),
                "Internal-test login identity mismatch")
        self.passed("retained internal-test ordinary account and real login (no public registration)")
        return token, user

    def snapshot(self, token):
        user = self.success("/api/user/self", token=token)
        logs = self.success("/api/log/self?type=2&p=1&page_size=100", token=token)
        require(isinstance(user, dict) and isinstance(logs, dict) and isinstance(logs.get("items"), list),
                "Balance/consumption snapshot is incomplete")
        return {
            "user_id": int(user["id"]), "quota": int(user["quota"]),
            "used_quota": int(user["used_quota"]), "request_count": int(user["request_count"]),
            "consumption_count": int(logs["total"]),
            "consumption_ids": sorted(int(item["id"]) for item in logs["items"]),
        }

    def ordinary_checks(self, token):
        for path in ("/api/channel/?p=1&page_size=1", "/api/user/?p=1&page_size=1", "/api/option/"):
            self.rejected(path, token)
        self.passed("ordinary user denied administrator channel/user/settings APIs")
        end = int(time.time())
        period = f"start_timestamp={end - 86400}&end_timestamp={end}"
        for path in (
            "/api/user/self", "/api/user/models", "/api/token/?p=1&page_size=10",
            f"/api/data/self?{period}", f"/api/data/flow/self?{period}",
            "/api/log/self?p=1&page_size=10", f"/api/log/self/stat?{period}",
            "/api/user/topup/info", "/api/user/topup/self?p=1&page_size=10",
        ):
            self.success(path, token=token)
        self.passed("ordinary overview, model list, API key list, usage and wallet read APIs")

    def key_checks(self, token):
        name = "rs-cloud-smoke-" + secrets.token_hex(6)
        self.success("/api/token/", "POST", {
            "name": name, "expired_time": int(time.time()) + 900,
            "remain_quota": 1, "unlimited_quota": False, "group": "default",
            "model_limits_enabled": True, "model_limits": "rs-smoke-no-upstream",
        }, token)
        data = self.success("/api/token/search?" + urllib.parse.urlencode({
            "keyword": name, "p": 1, "page_size": 100,
        }), token=token)
        require(isinstance(data, dict) and isinstance(data.get("items"), list), "Created-key lookup failed")
        found = [item for item in data["items"] if item.get("name") == name]
        require(len(found) == 1, "Created-key identity is not unique; refusing broad cleanup")
        token_id = int(found[0]["id"])
        deleted = False
        try:
            key_data = self.success(f"/api/token/{token_id}/key", "POST", token=token)
            require(isinstance(key_data, dict) and isinstance(key_data.get("key"), str)
                    and len(key_data["key"]) >= 32, "Created API key is invalid")
            raw_key = key_data["key"]
            relay_key = raw_key if raw_key.startswith("sk-") else "sk-" + raw_key
            code, payload, _ = self.request("/api/usage/token/", token=relay_key)
            require(code == 200 and isinstance(payload, dict) and payload.get("code") is True
                    and payload.get("data", {}).get("name") == name
                    and payload["data"].get("total_used") == 0,
                    "Created API key did not authenticate its read-only usage API")
            self.passed("bounded short-lived API key creation, key reveal and read-only authentication")
            self.success("/api/token/?status_only=1", "PUT", {"id": token_id, "status": 2}, token)
            record = self.success(f"/api/token/{token_id}", token=token)
            require(record.get("status") == 2, "API key revocation did not persist")
            code, _, _ = self.request("/api/usage/token/", token=relay_key)
            require(code in (401, 403), "Revoked API key was not rejected")
            self.passed("API key revocation persists and denies read-only API authentication")
            self.success(f"/api/token/{token_id}", "DELETE", token=token)
            deleted = True
            code, _, _ = self.request("/api/usage/token/", token=relay_key)
            require(code in (401, 403), "Deleted API key was not rejected")
            self.passed("temporary API key deletion and subsequent authentication rejection")
        finally:
            if not deleted:
                self.success(f"/api/token/{token_id}", "DELETE", token=token)
                self.passed("temporary API key cleanup after incomplete smoke check")

    def save_state(self, token, snapshot):
        directory = self.state_path.parent
        require(not directory.is_symlink() and not self.state_path.is_symlink(),
                "Refusing symlinked session-state destination")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        record = {"project": self.args.project, "service": self.args.service, "region": self.args.region,
                  "url": self.url, "revision": self.revision, "saved_at": int(time.time()),
                  "access_token": token, "snapshot": snapshot}
        descriptor, temporary = tempfile.mkstemp(prefix="acceptance-", dir=directory)
        try:
            with os.fdopen(descriptor, "w") as output:
                json.dump(record, output)
            os.replace(temporary, self.state_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.passed("short-lived ordinary session snapshot saved privately for restart verification")

    def persistence_check(self):
        require(self.state_path.is_file() and not self.state_path.is_symlink(),
                "Previous private session snapshot is missing")
        require(stat.S_IMODE(self.state_path.stat().st_mode) == 0o600,
                "Session snapshot permissions must be 0600")
        state = json.loads(self.state_path.read_text())
        for key, expected in (("project", self.args.project), ("service", self.args.service),
                              ("region", self.args.region), ("url", self.url)):
            require(state.get(key) == expected, "Persistence snapshot belongs to a different service")
        require(state.get("revision") != self.revision, "Ready revision has not changed; restart persistence is not yet testable")
        require(0 <= time.time() - state["saved_at"] < 840,
                "Saved session is too old; repeat the smoke check before changing the revision")
        require(self.snapshot(state["access_token"]) == state["snapshot"],
                "Existing session, account balance or consumption logs changed across revisions")
        self.passed("pre-revision session still authenticates after a different ready revision")
        self.passed("ordinary account identity, balance and consumption logs persist across revisions")
        self.ordinary_checks(state["access_token"])

    def run(self):
        self.service_target()
        self.public_checks()
        if self.args.persistence_check:
            self.persistence_check()
            return
        credentials, _ = self.deployment.secret(self.deployment.secret_names["admin"])
        admin_token, _ = self.login(json.loads(credentials), 100)
        self.success("/api/channel/?p=1&page_size=1", token=admin_token)
        self.passed("real root login and administrator API authorization")
        user_token, _ = self.ordinary_session(admin_token)
        before = self.snapshot(user_token)
        self.ordinary_checks(user_token)
        if not self.args.verify_only:
            self.key_checks(user_token)
        after = self.snapshot(user_token)
        require(after == before, "Smoke checks changed balance or produced consumption records")
        self.passed("no balance deductions, billed requests or new consumption records")
        self.save_state(user_token, after)
        self.checks.append({"check": "real provider relay, streaming, payments and bill reconciliation",
                            "status": "not_run", "reason": "No upstream or payment calls are made by this smoke test"})


def offline_tests(args):
    import unittest.mock

    fixture = {"metadata": {"name": args.service}, "status": {
        "url": "https://superapi-example-ew.a.run.app", "latestReadyRevisionName": "superapi-00001-a",
        "conditions": [{"type": "Ready", "status": "True"}],
        "traffic": [{"revisionName": "superapi-00001-a", "percent": 100}],
    }}
    cloud = unittest.mock.Mock()
    cloud.service_info.return_value = fixture
    runner = Acceptance(args, cloud)
    runner.service_target()
    for bad in ("http://localhost:3308", "https://evil.example", "https://good.run.app@evil.example",
                "https://good.run.app/path", "https://good.run.app?x=1"):
        fixture["status"]["url"] = bad
        try:
            runner.service_target()
        except AcceptanceError:
            pass
        else:
            raise AcceptanceError("Offline host-guard test failed")
    runner.url = "https://superapi-example-ew.a.run.app"
    for bad in ("https://evil.example/path", "//evil.example/path", "path", "/path#fragment"):
        try:
            runner.request(bad, token="not-a-real-token")
        except AcceptanceError:
            pass
        else:
            raise AcceptanceError("Offline request-path guard test failed")
    for response in ((500, {"success": False}, ""), (200, {"success": True}, "")):
        with unittest.mock.patch.object(runner, "request", return_value=response):
            try:
                runner.rejected("/api/user/self")
            except AcceptanceError:
                pass
            else:
                raise AcceptanceError("Offline rejection status test failed")
    with unittest.mock.patch.object(runner, "request", return_value=(403, {}, "")):
        runner.rejected("/api/user/self")
    with unittest.mock.patch.object(runner, "success", return_value={
        "items": [{"username": "rstest", "id": 2, "role": 1, "status": 1}],
    }), unittest.mock.patch.object(cloud, "gc", return_value=[]):
        try:
            runner.ordinary_session("not-a-real-token")
        except AcceptanceError:
            pass
        else:
            raise AcceptanceError("Offline existing-account protection test failed")
        cloud.secret.assert_not_called()
    try:
        NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example")
    except AcceptanceError:
        pass
    else:
        raise AcceptanceError("Offline credential redirect protection test failed")
    parsed = FrontendAssets()
    parsed.feed('<div id="root"></div><script src="/assets/index.js"></script><link rel="stylesheet" href="/assets/index.css">')
    require(parsed.root and parsed.scripts == ["/assets/index.js"] and parsed.styles == ["/assets/index.css"],
            "Offline production asset parsing test failed")
    print(json.dumps({"checks": [{"check": "offline host/path, redirect, rejection status, existing-account protection and frontend parser guards", "status": "passed"}]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="project-0338f2b7-06cf-4c5a-989")
    parser.add_argument("--region", default="europe-west1")
    parser.add_argument("--service", default="superapi")
    parser.add_argument("--sql-instance", default="superapi-test-pg")
    parser.add_argument("--repository", default="rs-test")
    parser.add_argument("--gcloud", default=os.environ.get("RS_GCLOUD", "gcloud"))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--verify-only", action="store_true", help="Do not create account, secret or temporary API key; login still creates sessions")
    modes.add_argument("--persistence-check", action="store_true", help="Only GETs; use saved session after a new ready revision within 15 minutes")
    modes.add_argument("--self-test", action="store_true", help="Offline guard tests; no cloud/application calls")
    args = parser.parse_args()
    for name in ("project", "region", "service", "sql_instance", "repository"):
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", getattr(args, name)):
            parser.error(f"Invalid {name}")
    runner = Acceptance(args)
    try:
        if args.self_test:
            offline_tests(args)
        else:
            runner.run()
            print(json.dumps({"checks": runner.checks}, ensure_ascii=False, indent=2))
        return 0
    except (AcceptanceError, DeploymentError) as error:
        runner.checks.append({"check": "acceptance stopped", "status": "failed", "reason": str(error)})
    except Exception:
        # Arbitrary exception text can include bodies, credentials or API keys.
        runner.checks.append({"check": "acceptance stopped", "status": "failed", "reason": "Unexpected error; request/response details suppressed"})
    print(json.dumps({"checks": runner.checks}, ensure_ascii=False, indent=2), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
