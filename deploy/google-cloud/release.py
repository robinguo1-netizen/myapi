#!/usr/bin/env python3
"""One-command RS test release: verified GitHub push, then Cloud Run rollout."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error

from deploy import Deployment, DeploymentError, ROOT


BRANCH = "rs-api-delivery-20260927"
GITHUB = "https://github.com/robinguo1-netizen/myapi.git"


def git(*args, credential=False):
    command = ["git"]
    if credential and shutil.which("gh"):
        command += ["-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential"]
    command += list(args)
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        # Git output can include credential-helper details; do not print it.
        raise DeploymentError(f"Git command failed: {args[0]}; inspect Git authentication or remote state locally")
    return result.stdout.strip()


def check_source():
    if Path(git("rev-parse", "--show-toplevel")).resolve() != ROOT:
        raise DeploymentError("Run this release from the reviewed RS API repository")
    if git("branch", "--show-current") != BRANCH:
        raise DeploymentError(f"Checkout {BRANCH} before releasing")
    if git("remote", "get-url", "github") != GITHUB:
        raise DeploymentError("The github remote is not the reviewed destination")
    if git("status", "--porcelain=v1", "--untracked-files=all"):
        raise DeploymentError("Working tree is not clean; review and commit changes before releasing")
    return git("rev-parse", "HEAD")


def run_tests():
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "deploy/google-cloud", "-p", "test_*.py"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode:
        raise DeploymentError("Local deployment tests failed; run the unittest command in README for details. Nothing was pushed or deployed")
    print("Local deployment tests passed.")


def sync_github(commit):
    git("fetch", "github", f"refs/heads/{BRANCH}", credential=True)
    remote = git("rev-parse", "FETCH_HEAD")
    if remote != commit:
        git("merge-base", "--is-ancestor", remote, commit)
        git("push", "github", f"HEAD:refs/heads/{BRANCH}", credential=True)
    published = git("ls-remote", "github", f"refs/heads/{BRANCH}", credential=True).split("\t", 1)[0]
    if published != commit:
        raise DeploymentError("GitHub branch SHA does not match local HEAD; cloud deployment was not started")
    return published


def sole_live_revision(service):
    traffic = service.get("status", {}).get("traffic", [])
    live = [item for item in traffic if item.get("percent") == 100 and item.get("revisionName")]
    if len(live) != 1 or any(item.get("percent", 0) not in (0, 100) for item in traffic):
        raise DeploymentError("Cloud Run traffic is not a single resolved 100% revision; inspect before releasing")
    return live[0]["revisionName"]


def wait_for(deployment, predicate, description, seconds=180):
    deadline = time.monotonic() + seconds
    while True:
        service = deployment.service_info()
        if service and predicate(service):
            return service
        if time.monotonic() >= deadline:
            raise DeploymentError(f"Timed out waiting for {description}; inspect Cloud Run before retrying")
        time.sleep(5)


def ready_revision(service, image, old_revision):
    status = service.get("status", {})
    template = service.get("spec", {}).get("template", {}).get("spec", {})
    containers = template.get("containers", [])
    revision = status.get("latestCreatedRevisionName")
    if (revision and revision != old_revision and status.get("latestReadyRevisionName") == revision
            and containers and containers[0].get("image") == image):
        return revision
    return None


def traffic_is(service, revision):
    try:
        return sole_live_revision(service) == revision
    except DeploymentError:
        return False


def update_cloud(deployment, image):
    before = deployment.service_info()
    if not before:
        raise DeploymentError("Cloud Run service does not exist; use the first-time deployment flow")
    old_revision = sole_live_revision(before)
    deployment.verify()  # Public HTTPS, disabled signup, and app authorization must hold before rollout.
    print(f"Current Cloud Run revision: {old_revision}")

    try:
        deployment.gc("run", "deploy", deployment.service, f"--region={deployment.region}",
                      f"--image={image}", "--no-traffic")
    except DeploymentError:
        # gcloud can exit nonzero after the server-side operation succeeds. Reconcile state below.
        print("Deploy command did not confirm success; checking Cloud Run state before deciding.", file=sys.stderr)
    staged = wait_for(deployment, lambda item: ready_revision(item, image, old_revision), "new revision readiness")
    new_revision = ready_revision(staged, image, old_revision)
    if not traffic_is(staged, old_revision):
        raise DeploymentError("Traffic changed while staging; inspect the service before switching")
    print(f"New revision ready without traffic: {new_revision}")

    switched = False
    try:
        try:
            deployment.gc("run", "services", "update-traffic", deployment.service,
                          f"--region={deployment.region}", f"--to-revisions={new_revision}=100")
        except DeploymentError:
            print("Traffic command did not confirm success; checking actual traffic state.", file=sys.stderr)
        wait_for(deployment, lambda item: traffic_is(item, new_revision), "new revision traffic")
        switched = True
        deployment.verify()
        final = deployment.service_info()
        if not traffic_is(final, new_revision):
            raise DeploymentError("Traffic changed during post-release verification")
        return {"url": final["status"]["url"], "revision": new_revision, "previous_revision": old_revision}
    except Exception:
        # Only roll back if this release actually moved traffic to its new revision.
        current = deployment.service_info()
        if switched or traffic_is(current, new_revision):
            try:
                deployment.gc("run", "services", "update-traffic", deployment.service,
                              f"--region={deployment.region}", f"--to-revisions={old_revision}=100")
            except DeploymentError:
                pass
            try:
                wait_for(deployment, lambda item: traffic_is(item, old_revision), "rollback traffic", seconds=90)
                print(f"Rolled traffic back to {old_revision}.", file=sys.stderr)
            except DeploymentError:
                print("WARNING: Automatic traffic rollback could not be verified; inspect Cloud Run immediately.", file=sys.stderr)
        raise


def release(deployment, *, check_only=False):
    commit = check_source()
    run_tests()
    if check_only:
        print(json.dumps({"ready_to_release": True, "commit": commit, "branch": BRANCH}, indent=2))
        return
    print("1/3 Syncing GitHub...")
    sync_github(commit)
    print(f"GitHub verified at {commit}")
    print("2/3 Building the verified commit...")
    build = deployment.build()
    if build["source_commit"] != commit:
        raise DeploymentError("Cloud Build source commit differs from verified GitHub SHA")
    if git("ls-remote", "github", f"refs/heads/{BRANCH}", credential=True).split("\t", 1)[0] != commit:
        raise DeploymentError("GitHub branch changed during build; Cloud Run was not changed")
    print("3/3 Updating Cloud Run...")
    result = update_cloud(deployment, build["image"])
    print(json.dumps({"github_commit": commit, "build_id": build["build_id"], **result}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check clean branch and local deployment tests only")
    parser.add_argument("--gcloud", default="gcloud", help="Google Cloud CLI executable")
    args = parser.parse_args()
    config = argparse.Namespace(project="project-0338f2b7-06cf-4c5a-989", region="europe-west1",
                                service="superapi", sql_instance="superapi-test-pg", repository="rs-test",
                                gcloud=args.gcloud, image=None)
    try:
        release(Deployment(config), check_only=args.check)
    except (DeploymentError, FileNotFoundError, urllib.error.URLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
