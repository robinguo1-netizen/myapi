#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


BASE_URL = os.environ["RS_BASE_URL"].rstrip("/")
ADMIN_USERNAME = os.environ["RS_ADMIN_USERNAME"]
ADMIN_PASSWORD = os.environ["RS_ADMIN_PASSWORD"]
USER_USERNAME = os.environ["RS_USER_USERNAME"]
USER_PASSWORD = os.environ["RS_USER_PASSWORD"]
MODEL = os.environ.get("RS_UPSTREAM_MODEL", "gpt-3.5-turbo")

parsed_base_url = urllib.parse.urlparse(BASE_URL)
if (
    parsed_base_url.scheme != "http"
    or parsed_base_url.hostname not in ("127.0.0.1", "localhost")
    or parsed_base_url.port != 3308
    or parsed_base_url.path not in ("", "/")
):
    raise RuntimeError("RS_BASE_URL must be the dedicated local loopback service http://127.0.0.1:3308")


class AcceptanceError(RuntimeError):
    pass


def request(path, method="GET", body=None, access_token=None, relay_key=None):
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    if relay_key:
        headers["Authorization"] = f"Bearer {relay_key}"
    payload = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}", data=payload, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
            if "text/event-stream" in content_type:
                return response.status, raw.decode("utf-8"), content_type
            return response.status, json.loads(raw or b"{}"), content_type
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            parsed = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            parsed = raw.decode("utf-8", errors="replace")
        return error.code, parsed, error.headers.get("Content-Type", "")


def require(condition, message):
    if not condition:
        raise AcceptanceError(message)


def require_success(response, label):
    status, payload, _ = response
    require(status == 200, f"{label}: unexpected HTTP {status}")
    require(isinstance(payload, dict) and payload.get("success") is True, f"{label}: API failure")
    return payload.get("data")


def login(username, password):
    data = require_success(
        request(
            "/api/user/login",
            method="POST",
            body={"username": username, "password": password},
        ),
        f"login {username}",
    )
    require(isinstance(data, dict) and data.get("access_token"), "login token missing")
    return data["access_token"], data["user"]


def page_items(data):
    if isinstance(data, dict):
        return data.get("items") or []
    return []


def get_user_and_token_state(access_token, token_id):
    user = require_success(request("/api/user/self", access_token=access_token), "read user quota")
    tokens = page_items(
        require_success(
            request("/api/token/?p=0&page_size=100", access_token=access_token),
            "read token quota",
        )
    )
    token = next(item for item in tokens if int(item["id"]) == token_id)
    return int(user["quota"]), token


def get_consumption_logs(access_token):
    logs = page_items(
        require_success(
            request("/api/log/self?p=0&page_size=100", access_token=access_token),
            "read usage logs",
        )
    )
    return [
        log
        for log in logs
        if log.get("model_name") == MODEL and int(log.get("quota", 0)) > 0
    ]


def wait_for_new_consumption_logs(access_token, previous_ids, expected_count):
    for _ in range(40):
        logs = get_consumption_logs(access_token)
        new_logs = [log for log in logs if int(log["id"]) not in previous_ids]
        if len(new_logs) >= expected_count:
            return new_logs
        time.sleep(0.25)
    raise AcceptanceError("timed out waiting for billed usage logs")


def wait_for_user_quota(access_token, predicate, label):
    for _ in range(40):
        user = require_success(request("/api/user/self", access_token=access_token), label)
        quota = int(user["quota"])
        if predicate(quota):
            return quota
        time.sleep(0.25)
    raise AcceptanceError(f"timed out waiting for {label}")


def wait_for_model_route(access_token):
    for _ in range(40):
        status, payload, _ = request("/api/user/models", access_token=access_token)
        if status == 200 and isinstance(payload, dict) and payload.get("success") is True:
            if MODEL in json.dumps(payload.get("data"), ensure_ascii=False):
                return
        time.sleep(0.25)
    raise AcceptanceError("timed out waiting for the new channel to enter the model route cache")


def require_no_new_consumption(access_token, previous_ids, label):
    logs = get_consumption_logs(access_token)
    new_logs = [log for log in logs if int(log["id"]) not in previous_ids]
    require(not new_logs, f"{label}: rejected request created a billed usage log")


def update_token_quota(access_token, token, quota):
    require_success(
        request(
            "/api/token/",
            method="PUT",
            access_token=access_token,
            body={
                "id": int(token["id"]),
                "name": token["name"],
                "expired_time": int(token["expired_time"]),
                "remain_quota": quota,
                "unlimited_quota": False,
                "model_limits_enabled": True,
                "model_limits": MODEL,
                "allow_ips": token.get("allow_ips", ""),
                "group": "default",
            },
        ),
        f"set token quota to {quota}",
    )


def main():
    checks = []

    setup = require_success(request("/api/setup"), "read setup")
    if not setup.get("status"):
        require_success(
            request(
                "/api/setup",
                method="POST",
                body={
                    "username": ADMIN_USERNAME,
                    "password": ADMIN_PASSWORD,
                    "confirmPassword": ADMIN_PASSWORD,
                    "SelfUseModeEnabled": False,
                    "DemoSiteEnabled": False,
                },
            ),
            "initialize application",
        )
    checks.append("fresh PostgreSQL initialization")

    admin_token, admin_user = login(ADMIN_USERNAME, ADMIN_PASSWORD)
    require(admin_user.get("role") == 100, "root role was not issued")
    require_success(request("/api/channel/?p=0&page_size=10", access_token=admin_token), "admin permission")
    checks.append("root login and administrator authorization")

    register_status, register_payload, _ = request(
        "/api/user/register",
        method="POST",
        body={"username": USER_USERNAME, "password": USER_PASSWORD},
    )
    if not (register_status == 200 and register_payload.get("success") is True):
        require("存在" in str(register_payload) or "exist" in str(register_payload).lower(), "user registration failed")
    user_token, user = login(USER_USERNAME, USER_PASSWORD)
    require(user.get("role") == 1, "ordinary user role was not issued")
    user_id = int(user["id"])
    checks.append("ordinary registration and login")

    ordinary_admin_status, ordinary_admin_payload, _ = request(
        "/api/channel/?p=0&page_size=10", access_token=user_token
    )
    ordinary_admin_allowed = (
        ordinary_admin_status == 200
        and isinstance(ordinary_admin_payload, dict)
        and ordinary_admin_payload.get("success") is True
    )
    require(not ordinary_admin_allowed, "ordinary user accessed an administrator endpoint")
    checks.append("ordinary-user administrator-route rejection")

    require_success(
        request(
            "/api/user/manage",
            method="POST",
            access_token=admin_token,
            body={"id": user_id, "action": "add_quota", "mode": "add", "value": 200000},
        ),
        "assign test quota",
    )
    wait_for_user_quota(user_token, lambda quota: quota > 100000, "positive simulated balance")
    checks.append("administrator-assigned simulated balance")

    channels = page_items(
        require_success(
            request("/api/channel/?p=0&page_size=100", access_token=admin_token),
            "list channels",
        )
    )
    if not any(channel.get("name") == "RS local fake upstream" for channel in channels):
        require_success(
            request(
                "/api/channel/",
                method="POST",
                access_token=admin_token,
                body={
                    "mode": "single",
                    "channel": {
                        "type": 1,
                        "key": os.environ["RS_UPSTREAM_KEY"],
                        "status": 1,
                        "name": "RS local fake upstream",
                        "weight": 100,
                        "base_url": "http://fake-upstream:8080",
                        "models": MODEL,
                        "group": "default",
                    },
                },
            ),
            "create fake-upstream channel",
        )
    wait_for_model_route(user_token)
    checks.append("real channel management path to local fake upstream")

    token_name = "rs-local-acceptance"
    tokens = page_items(
        require_success(request("/api/token/?p=0&page_size=100", access_token=user_token), "list keys")
    )
    existing = next((token for token in tokens if token.get("name") == token_name), None)
    if existing is None:
        require_success(
            request(
                "/api/token/",
                method="POST",
                access_token=user_token,
                body={
                    "name": token_name,
                    "expired_time": -1,
                    "remain_quota": 100000,
                    "unlimited_quota": False,
                    "model_limits_enabled": True,
                    "model_limits": MODEL,
                    "group": "default",
                },
            ),
            "create API key",
        )
        tokens = page_items(
            require_success(request("/api/token/?p=0&page_size=100", access_token=user_token), "reload keys")
        )
        existing = next((token for token in tokens if token.get("name") == token_name), None)
    require(existing is not None, "created key was not returned")
    token_id = int(existing["id"])
    key_data = require_success(
        request(f"/api/token/{token_id}/key", method="POST", access_token=user_token),
        "read created API key",
    )
    raw_relay_key = key_data["key"]
    require(isinstance(raw_relay_key, str) and len(raw_relay_key) >= 32, "relay key format is invalid")
    relay_key = f"sk-{raw_relay_key}"
    checks.append("API key creation and bounded quota")

    before_user_quota, before_token = get_user_and_token_state(user_token, token_id)
    before_logs = get_consumption_logs(user_token)
    before_log_ids = {int(log["id"]) for log in before_logs}

    nonstream_status, nonstream, _ = request(
        "/v1/chat/completions",
        method="POST",
        relay_key=relay_key,
        body={
            "model": MODEL,
            "messages": [{"role": "user", "content": "non-stream acceptance"}],
            "stream": False,
        },
    )
    require(nonstream_status == 200, f"non-stream relay returned {nonstream_status}")
    content = nonstream["choices"][0]["message"]["content"]
    require(content == "RS fake upstream response: non-stream acceptance", "non-stream upstream marker missing")
    checks.append("non-stream request forwarding")

    stream_status, stream_body, stream_type = request(
        "/v1/chat/completions",
        method="POST",
        relay_key=relay_key,
        body={
            "model": MODEL,
            "messages": [{"role": "user", "content": "stream acceptance"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        },
    )
    require(stream_status == 200, f"stream relay returned {stream_status}")
    require("text/event-stream" in stream_type, "stream content type missing")
    require("RS fake upstream" in stream_body and "[DONE]" in stream_body, "stream payload incomplete")
    checks.append("streaming request forwarding")

    new_logs = wait_for_new_consumption_logs(user_token, before_log_ids, 2)
    billed_quota = sum(int(log["quota"]) for log in new_logs)
    after_user_quota = before_user_quota
    after_token = before_token
    for _ in range(40):
        after_user_quota, after_token = get_user_and_token_state(user_token, token_id)
        user_deduction = before_user_quota - after_user_quota
        token_deduction = int(before_token["remain_quota"]) - int(after_token["remain_quota"])
        if user_deduction == billed_quota and token_deduction == billed_quota:
            break
        time.sleep(0.25)
    user_deduction = before_user_quota - after_user_quota
    token_deduction = int(before_token["remain_quota"]) - int(after_token["remain_quota"])
    require(user_deduction > 0, "user quota was not deducted")
    require(token_deduction > 0, "token quota was not deducted")
    require(int(after_token["used_quota"]) > int(before_token.get("used_quota", 0)), "token usage was not recorded")
    require(
        user_deduction == billed_quota,
        f"user deduction {user_deduction} does not equal new billed logs {billed_quota}",
    )
    require(
        token_deduction == billed_quota,
        f"token deduction {token_deduction} does not equal new billed logs {billed_quota}",
    )
    checks.append("exact user/key deduction equals new billed usage logs")

    success_log_ids = before_log_ids | {int(log["id"]) for log in new_logs}
    post_success_user_quota = after_user_quota
    post_success_token_quota = int(after_token["remain_quota"])

    require_success(
        request(
            "/api/token/?status_only=1",
            method="PUT",
            access_token=user_token,
            body={"id": token_id, "status": 2},
        ),
        "revoke API key",
    )
    revoked_status, _, _ = request(
        "/v1/chat/completions",
        method="POST",
        relay_key=relay_key,
        body={"model": MODEL, "messages": [{"role": "user", "content": "revoked"}]},
    )
    require(revoked_status in (401, 403), "revoked key was accepted")
    revoked_user_quota, revoked_token = get_user_and_token_state(user_token, token_id)
    require(revoked_user_quota == post_success_user_quota, "revoked request changed user quota")
    require(int(revoked_token["remain_quota"]) == post_success_token_quota, "revoked request changed token quota")
    require_no_new_consumption(user_token, success_log_ids, "revoked key")
    checks.append("API key revocation rejection without billing")

    require_success(
        request(
            "/api/token/?status_only=1",
            method="PUT",
            access_token=user_token,
            body={"id": token_id, "status": 1},
        ),
        "re-enable API key",
    )

    _, reenabled_token = get_user_and_token_state(user_token, token_id)
    update_token_quota(user_token, reenabled_token, 1)
    exhausted_user_before, exhausted_token_before = get_user_and_token_state(user_token, token_id)
    exhausted_logs = get_consumption_logs(user_token)
    exhausted_log_ids = {int(log["id"]) for log in exhausted_logs}
    exhausted_status, _, _ = request(
        "/v1/chat/completions",
        method="POST",
        relay_key=relay_key,
        body={
            "model": MODEL,
            "messages": [{"role": "user", "content": "token exhausted"}],
            "max_tokens": 1024,
        },
    )
    require(exhausted_status in (402, 403), "exhausted token quota was accepted")
    exhausted_user_after, exhausted_token_after = get_user_and_token_state(user_token, token_id)
    require(exhausted_user_after == exhausted_user_before, "token-quota rejection changed user quota")
    require(int(exhausted_token_after["remain_quota"]) == int(exhausted_token_before["remain_quota"]), "token-quota rejection changed token quota")
    require_no_new_consumption(user_token, exhausted_log_ids, "exhausted token quota")
    checks.append("token-quota exhaustion rejection while account balance remains")

    update_token_quota(user_token, exhausted_token_after, 100000)
    balance_to_remove, _ = get_user_and_token_state(user_token, token_id)
    require(balance_to_remove > 0, "test balance was not positive before insufficient-balance check")
    require_success(
        request(
            "/api/user/manage",
            method="POST",
            access_token=admin_token,
            body={
                "id": user_id,
                "action": "add_quota",
                "mode": "subtract",
                "value": balance_to_remove,
            },
        ),
        "zero test balance",
    )
    wait_for_user_quota(user_token, lambda quota: quota == 0, "zero simulated balance")
    insufficient_status, _, _ = request(
        "/v1/chat/completions",
        method="POST",
        relay_key=relay_key,
        body={
            "model": MODEL,
            "messages": [{"role": "user", "content": "no balance"}],
            "max_tokens": 1024,
        },
    )
    require(insufficient_status in (402, 403), "insufficient balance was accepted")
    insufficient_user_after, insufficient_token_after = get_user_and_token_state(user_token, token_id)
    insufficient_logs = get_consumption_logs(user_token)
    insufficient_log_ids = {int(log["id"]) for log in insufficient_logs}
    require(insufficient_user_after == 0, "insufficient request changed zero account balance")
    require(int(insufficient_token_after["remain_quota"]) == 100000, "insufficient request changed token quota")
    require_no_new_consumption(user_token, exhausted_log_ids, "insufficient balance")
    checks.append("insufficient-balance rejection without billing")

    invalid_status, _, _ = request(
        "/v1/chat/completions",
        method="POST",
        relay_key="sk-invalid-local-only",
        body={"model": MODEL, "messages": [{"role": "user", "content": "invalid"}]},
    )
    require(invalid_status in (401, 403), "invalid API key was accepted")
    invalid_user_after, invalid_token_after = get_user_and_token_state(user_token, token_id)
    require(invalid_user_after == insufficient_user_after, "invalid-key request changed user quota")
    require(int(invalid_token_after["remain_quota"]) == int(insufficient_token_after["remain_quota"]), "invalid-key request changed token quota")
    require_no_new_consumption(user_token, insufficient_log_ids, "invalid key")
    checks.append("invalid-key rejection without billing")

    require_success(
        request(f"/api/token/{token_id}", method="DELETE", access_token=user_token),
        "delete API key",
    )
    deleted_status, _, _ = request(
        "/v1/chat/completions",
        method="POST",
        relay_key=relay_key,
        body={"model": MODEL, "messages": [{"role": "user", "content": "deleted"}]},
    )
    require(deleted_status in (401, 403), "deleted API key was accepted")
    deleted_user = require_success(request("/api/user/self", access_token=user_token), "read quota after deletion")
    require(int(deleted_user["quota"]) == invalid_user_after, "deleted-key request changed user quota")
    require_no_new_consumption(user_token, insufficient_log_ids, "deleted key")
    checks.append("API key deletion rejection without billing")

    print(json.dumps({"success": True, "checks": checks}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"success": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise
