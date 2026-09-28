"""Offline safety tests for the repeatable GitHub-first Cloud Run release."""

import copy
import unittest
from unittest.mock import Mock, patch

import deploy
import release


OLD = "superapi-00006-dpl"
NEW = "superapi-00007-tst"
IMAGE = "europe-west1-docker.pkg.dev/project-0338f2b7-06cf-4c5a-989/rs-test/new-api@sha256:" + "a" * 64


class FakeCloud:
    service = "superapi"
    region = "europe-west1"

    def __init__(self, *, fail_deploy=False, fail_switch=False, fail_verify=False):
        self.calls = []
        self.fail_deploy = fail_deploy
        self.fail_switch = fail_switch
        self.fail_verify = fail_verify
        self.traffic = OLD
        self.created = OLD
        self.image = "old-image"

    def service_info(self):
        return {"metadata": {"name": self.service},
                "spec": {"template": {"spec": {"containers": [{"image": self.image}]}}},
                "status": {"url": "https://test.run.app", "latestCreatedRevisionName": self.created,
                           "latestReadyRevisionName": self.created,
                           "traffic": [{"revisionName": self.traffic, "percent": 100}]}}

    def gc(self, *args):
        self.calls.append(args)
        if args[:2] == ("run", "deploy"):
            self.created = NEW
            self.image = IMAGE
            if self.fail_deploy:
                raise deploy.DeploymentError("transient deploy CLI failure")
        elif args[:3] == ("run", "services", "update-traffic"):
            self.traffic = NEW if f"--to-revisions={NEW}=100" in args else OLD
            if self.fail_switch and self.traffic == NEW:
                raise deploy.DeploymentError("transient traffic CLI failure")

    def verify(self):
        self.calls.append(("verify", self.traffic))
        if self.fail_verify and self.traffic == NEW:
            raise deploy.DeploymentError("smoke check failed")


class ReleaseTests(unittest.TestCase):
    def test_check_source_rejects_dirty_tree(self):
        values = iter([str(deploy.ROOT), release.BRANCH, release.GITHUB, " M web/App.tsx"])
        with patch.object(release, "git", side_effect=lambda *a, **kw: next(values)):
            with self.assertRaisesRegex(deploy.DeploymentError, "not clean"):
                release.check_source()

    def test_github_failure_prevents_build_and_cloud(self):
        cloud = Mock()
        with patch.object(release, "check_source", return_value="a" * 40), \
             patch.object(release, "run_tests"), \
             patch.object(release, "sync_github", side_effect=deploy.DeploymentError("push failed")), \
             patch.object(release, "update_cloud") as update:
            with self.assertRaises(deploy.DeploymentError):
                release.release(cloud)
        cloud.build.assert_not_called()
        update.assert_not_called()

    def test_build_mismatch_prevents_cloud_rollout(self):
        cloud = Mock()
        cloud.build.return_value = {"source_commit": "b" * 40, "image": IMAGE, "build_id": "test"}
        with patch.object(release, "check_source", return_value="a" * 40), \
             patch.object(release, "run_tests"), \
             patch.object(release, "sync_github", return_value="a" * 40), \
             patch.object(release, "update_cloud") as update:
            with self.assertRaisesRegex(deploy.DeploymentError, "differs"):
                release.release(cloud)
        update.assert_not_called()

    def test_cloud_stages_without_traffic_then_switches_and_verifies(self):
        cloud = FakeCloud(fail_deploy=True, fail_switch=True)
        with patch.object(release, "wait_for", wraps=release.wait_for):
            result = release.update_cloud(cloud, IMAGE)
        self.assertEqual(result["revision"], NEW)
        self.assertEqual(cloud.traffic, NEW)
        self.assertEqual(cloud.calls[0], ("verify", OLD))
        self.assertIn("--no-traffic", cloud.calls[1])
        self.assertEqual(cloud.calls[-1], ("verify", NEW))

    def test_failed_smoke_test_restores_old_traffic(self):
        cloud = FakeCloud(fail_verify=True)
        with self.assertRaisesRegex(deploy.DeploymentError, "smoke check failed"):
            release.update_cloud(cloud, IMAGE)
        self.assertEqual(cloud.traffic, OLD)
        self.assertIn(f"--to-revisions={OLD}=100", cloud.calls[-1])

    def test_ambiguous_traffic_is_rejected_before_deploy(self):
        cloud = FakeCloud()
        original = cloud.service_info
        def split_traffic():
            item = copy.deepcopy(original())
            item["status"]["traffic"] = [{"revisionName": OLD, "percent": 50}, {"revisionName": "other", "percent": 50}]
            return item
        cloud.service_info = split_traffic
        with self.assertRaisesRegex(deploy.DeploymentError, "single resolved"):
            release.update_cloud(cloud, IMAGE)
        self.assertEqual(cloud.calls, [])


if __name__ == "__main__":
    unittest.main()
