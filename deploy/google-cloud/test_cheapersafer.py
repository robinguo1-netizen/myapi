"""Contracts for the independent cheapersafer project and app identity."""

import contextlib
import io
import json
import unittest
from unittest.mock import Mock

import cheapersafer
from deploy import Deployment


class CheapersaferDeploymentTests(unittest.TestCase):
    def test_plan_has_independent_project_database_accounts_and_secrets(self):
        deployment = Deployment(cheapersafer.deployment_args())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            deployment.plan()
        plan = json.loads(output.getvalue())
        self.assertNotEqual(plan["project"], cheapersafer.RS_PROJECT)
        self.assertEqual(plan["database"], "cheapersafer_api")
        self.assertEqual(plan["database_user"], "cheapersafer_app")
        for key in ("runtime_service_account", "build_service_account"):
            self.assertTrue(plan[key].endswith(f"@{plan['project']}.iam.gserviceaccount.com"))
        self.assertEqual(deployment.connection, "cheapersafer-si-20261008:europe-west1:cheapersafer-pg")
        self.assertTrue(all(name.startswith("cheapersafer-") for name in plan["secrets"].values()))
        self.assertEqual(deployment.source_bucket, "cheapersafer-si-20261008-build-source")

    def test_bootstrap_sets_new_brand_and_actual_service_url_after_login(self):
        deployment = Deployment(cheapersafer.deployment_args())
        url = "https://cheapersafer-test.run.app"
        deployment.service_info = Mock(return_value={"status": {"url": url}})
        deployment.protect_bootstrap = Mock()
        deployment.app = Mock(return_value=(403, {}))
        deployment.secret = Mock(return_value=(json.dumps({"username": "csadmin", "password": "test-only"}), "1"))
        deployment.app_success = Mock(side_effect=[
            {"status": True}, {"user": {"role": 100}, "access_token": "test-token"},
            None, None, None, None, None,
        ])
        deployment.check_application = Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            deployment.bootstrap()
        options = [call.args[3] for call in deployment.app_success.call_args_list if call.args[1] == "/api/option/"]
        self.assertEqual(options, [
            {"key": "RegisterEnabled", "value": "false"},
            {"key": "PasswordRegisterEnabled", "value": "false"},
            {"key": "SystemName", "value": "cheapersafer.si"},
            {"key": "Logo", "value": "/cheapersafer-cs.svg"},
            {"key": "ServerAddress", "value": url},
        ])
        self.assertTrue(all(call.kwargs.get("admin_token") == "test-token" for call in deployment.app_success.call_args_list if call.args[1] == "/api/option/"))


if __name__ == "__main__":
    unittest.main()
