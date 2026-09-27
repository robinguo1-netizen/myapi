"""Offline contract tests: no credentials, subprocesses or cloud access required."""

import argparse
import contextlib
import copy
import io
import json
import unittest
from unittest.mock import Mock, patch

import deploy


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(project="project-0338f2b7-06cf-4c5a-989", region="europe-west1",
            service="superapi", sql_instance="superapi-test-pg", repository="rs-test", gcloud="gcloud", image=None)
        self.d = deploy.Deployment(self.args)
        self.output = io.StringIO()
        self.capture = contextlib.redirect_stdout(self.output)
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)
        self.profile = {"name": self.d.instance, "region": self.d.region, "databaseVersion": "POSTGRES_16",
            "settings": {"tier": "db-f1-micro", "availabilityType": "ZONAL", "edition": "ENTERPRISE",
                "dataDiskType": "PD_SSD", "dataDiskSizeGb": "10", "storageAutoResize": False,
                "connectorEnforcement": "REQUIRED", "ipConfiguration": {"ipv4Enabled": True, "sslMode": "ENCRYPTED_ONLY", "authorizedNetworks": []},
                "backupConfiguration": {"enabled": True, "pointInTimeRecoveryEnabled": False, "backupRetentionSettings": {"retainedBackups": 3}}}}
        self.service = {"metadata": {"name": "superapi"}, "status": {"url": "https://test.run.app", "latestReadyRevisionName": "superapi-00001"}}

    def test_plan_is_offline_and_bounded(self):
        self.d.gc = Mock(side_effect=AssertionError("plan must not call gcloud"))
        self.d.plan()
        plan = json.loads(self.output.getvalue())
        self.assertEqual(plan["cloud_run"]["service_max"], 1)
        self.assertFalse(plan["cloud_run"]["cpu_throttling"])
        self.assertFalse(plan["cloud_sql"]["point_in_time_recovery"])

    def test_inspect_never_prints_arbitrary_annotations_or_env_values(self):
        self.d.project_info = Mock(return_value={"projectNumber": "123"})
        service = copy.deepcopy(self.service)
        service["metadata"]["annotations"] = {"run.googleapis.com/ingress": "all", "kubectl.kubernetes.io/last-applied-configuration": "DO_NOT_PRINT"}
        service["spec"] = {"template": {"metadata": {"annotations": {"arbitrary": "DO_NOT_PRINT"}}, "spec": {"containers": [{"env": [{"name": "SECRET", "value": "DO_NOT_PRINT"}]}]}}}
        self.d.service_info = Mock(return_value=service)
        self.d.gc = Mock(side_effect=[{"billingEnabled": True}, [{"config": {"name": "run.googleapis.com"}}]])
        self.d.inspect()
        self.assertNotIn("DO_NOT_PRINT", self.output.getvalue())
        self.assertIn('"SECRET"', self.output.getvalue())

    def test_iam_verb_positions_and_idempotence(self):
        for scope, command in ((["projects", "test"], ["projects"]),
                (["secrets", "dsn"], ["secrets"]),
                (["artifacts", "repositories", "rs-test", "--location=europe-west1"], ["artifacts", "repositories"]),
                (["storage", "buckets", "gs://test"], ["storage", "buckets"])):
            with self.subTest(scope=scope):
                self.d.gc = Mock(return_value={"bindings": []})
                self.d.grant(scope, "serviceAccount:test", "roles/test")
                calls = self.d.gc.call_args_list
                self.assertEqual(calls[0].args[:len(command)+1], tuple(command + ["get-iam-policy"]))
                self.assertEqual(calls[1].args[:len(command)+1], tuple(command + ["add-iam-policy-binding"]))
        self.d.gc = Mock(return_value={"bindings": [{"role": "roles/test", "members": ["serviceAccount:test"]}]})
        self.d.grant(["projects", "test"], "serviceAccount:test", "roles/test")
        self.assertEqual(self.d.gc.call_count, 1)

    def test_budget_uses_project_number(self):
        self.d.project_info = Mock(return_value={"projectNumber": "123456"})
        self.d.gc = Mock(side_effect=[{"billingEnabled": True, "billingAccountName": "billingAccounts/abc"}, [{"config": {"name": "billingbudgets.googleapis.com"}}], [], {}])
        self.d.budget()
        self.assertIn("--filter-projects=projects/123456", self.d.gc.call_args.args)

    def test_sql_profile_rejects_pitr_public_network_or_oversizing(self):
        self.d.check_sql_profile(self.profile)
        for key, value in (("tier", "db-custom-8-32768"), ("dataDiskSizeGb", "100"), ("storageAutoResize", True)):
            profile = copy.deepcopy(self.profile)
            profile["settings"][key] = value
            with self.assertRaises(deploy.DeploymentError):
                self.d.check_sql_profile(profile)
        for section, key, value in (("ipConfiguration", "authorizedNetworks", [{"value": "0.0.0.0/0"}]), ("backupConfiguration", "pointInTimeRecoveryEnabled", True)):
            profile = copy.deepcopy(self.profile)
            profile["settings"][section][key] = value
            with self.assertRaises(deploy.DeploymentError):
                self.d.check_sql_profile(profile)

    def test_provision_contract_and_admin_password(self):
        calls = []
        stored = {}
        def gc(*args, **kwargs):
            calls.append(args)
            if args[:3] == ("billing", "projects", "describe"):
                return {"billingEnabled": True}
            if args[:2] == ("services", "list"):
                return [{"config": {"name": api}} for api in deploy.APIS]
            if args[:3] == ("sql", "instances", "describe"):
                return self.profile
            if "list" in args:
                return []
            return {}
        def secret(name, initial=None):
            if name not in stored:
                stored[name] = initial() if callable(initial) else initial
            return stored[name], "1"
        self.d.gc = gc
        self.d.secret = secret
        self.d.grant = Mock()
        self.d.api = Mock(return_value={"name": "sql-op"})
        self.d.provision()
        sql_create = next(call for call in calls if call[:3] == ("sql", "instances", "create"))
        self.assertIn("--tier=db-f1-micro", sql_create)
        self.assertIn("--no-storage-auto-increase", sql_create)
        self.assertIn("--connector-enforcement=REQUIRED", sql_create)
        self.assertEqual(len(json.loads(stored[self.d.secret_names["admin"]])["password"]), 20)
        self.assertTrue(stored[self.d.secret_names["dsn"]].startswith("postgresql://rs_app:"))
        self.assertNotIn(stored[self.d.secret_names["password"]], repr(calls))
        self.assertNotIn(stored[self.d.secret_names["password"]], self.output.getvalue())
        user_call = next(call for call in self.d.api.call_args_list if call.args[0].endswith("/users"))
        self.assertEqual(user_call.args[0], f"https://sqladmin.googleapis.com/v1/projects/{self.d.project}/instances/{self.d.instance}/users")

    def test_build_exact_head_and_digest(self):
        revision = "a" * 40
        image = f"{self.d.region}-docker.pkg.dev/{self.d.project}/{self.d.repository}/new-api:{revision[:12]}"
        self.d.gc = Mock(return_value={"status": "SUCCESS", "id": "build-id", "results": {"images": [{"name": image, "digest": "sha256:" + "b" * 64}]}})
        with patch.object(deploy, "execute", side_effect=["", "deploy/google-cloud/test_deploy.py\0", revision, ""]), patch.object(deploy.subprocess, "run", return_value=Mock(stdout=b"mock-archive")) as process:
            self.d.build()
        self.assertEqual(process.call_args.args[0], ["git", "archive", "--format=tar", "HEAD"])
        self.assertTrue(json.loads(self.output.getvalue())["image"].endswith("@sha256:" + "b" * 64))

    def test_build_rejects_uncommitted_untracked_app_changes(self):
        with patch.object(deploy, "execute", side_effect=["", "web/new-file.tsx\0"]):
            with self.assertRaises(deploy.DeploymentError):
                self.d.build()

    def test_deploy_profile_and_secret_version_pinning(self):
        self.args.image = f"{self.d.region}-docker.pkg.dev/{self.d.project}/{self.d.repository}/new-api@sha256:" + "a" * 64
        self.d.project_info = Mock(return_value={"projectNumber": "123"})
        self.d.service_info = Mock(return_value=self.service)
        self.d.protect_bootstrap = Mock()
        self.d.secret = Mock(return_value=("not-printed", "7"))
        self.d.gc = Mock(return_value={})
        self.d.deploy()
        command = next(call.args for call in self.d.gc.call_args_list if call.args[:2] == ("run", "deploy"))
        for flag in ("--min=0", "--max=1", "--max-instances=1", "--no-cpu-throttling", "--no-cpu-boost", "--invoker-iam-check", "--no-allow-unauthenticated"):
            self.assertIn(flag, command)
        env = next(arg for arg in command if arg.startswith("--set-env-vars="))
        self.assertIn("BATCH_UPDATE_ENABLED=false", env)
        self.assertNotIn("REDIS_CONN_STRING", env)
        self.assertIn("--set-secrets=SQL_DSN=superapi-database-dsn:7,SESSION_SECRET=superapi-session-secret:7", command)

    def test_bootstrap_blocks_credentials_when_setup_is_public(self):
        self.d.service_info = Mock(return_value=self.service)
        self.d.protect_bootstrap = Mock()
        self.d.app = Mock(return_value=(200, {}))
        self.d.secret = Mock()
        with self.assertRaises(deploy.DeploymentError):
            self.d.bootstrap()
        self.d.secret.assert_not_called()

    def test_bootstrap_creates_root_and_disables_both_registration_options(self):
        self.d.service_info = Mock(return_value=self.service)
        self.d.protect_bootstrap = Mock()
        self.d.app = Mock(return_value=(403, {}))
        self.d.secret = Mock(return_value=(json.dumps({"username": "rsadmin", "password": "test-only-password"}), "1"))
        self.d.app_success = Mock(side_effect=[{"status": False, "root_init": False}, None, {"user": {"role": 100}, "access_token": "fake-app-token"}, None, None])
        self.d.check_application = Mock()
        self.d.bootstrap()
        option_calls = [call for call in self.d.app_success.call_args_list if call.args[1] == "/api/option/"]
        self.assertEqual([call.args[3] for call in option_calls], [{"key": "RegisterEnabled", "value": "false"}, {"key": "PasswordRegisterEnabled", "value": "false"}])

    def test_application_auth_rejects_arbitrary_500_with_success_false(self):
        self.d.app_success = Mock(side_effect=[{"status": True}, {"register_enabled": False, "password_register_enabled": False}])
        self.d.app = Mock(return_value=(500, {"success": False}))
        with self.assertRaises(deploy.DeploymentError):
            self.d.check_application("https://test.run.app")

    def test_publish_checks_before_opening(self):
        order = []
        self.d.service_info = Mock(return_value=self.service)
        self.d.check_application = Mock(side_effect=lambda *a, **kw: order.append("check"))
        self.d.gc = Mock(side_effect=lambda *a, **kw: order.append("publish"))
        self.d.verify = Mock(side_effect=lambda: order.append("verify"))
        self.d.publish()
        self.assertEqual(order, ["check", "publish", "verify"])
        self.assertIn("--no-invoker-iam-check", self.d.gc.call_args.args)

    def test_verify_is_truly_anonymous(self):
        self.d.service_info = Mock(return_value=self.service)
        def app(url, path, *args, **kwargs):
            self.assertIs(kwargs.get("google_auth"), False)
            if path == "/api/status":
                return 200, {"success": True, "data": {"register_enabled": False, "password_register_enabled": False}}
            if path == "/api/setup":
                return 200, {"success": True, "data": {"status": True}}
            return 401, {}
        self.d.app = app
        self.d.verify()
        self.assertTrue(json.loads(self.output.getvalue())["public_https"])


if __name__ == "__main__":
    unittest.main()
