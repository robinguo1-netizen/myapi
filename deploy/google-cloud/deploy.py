#!/usr/bin/env python3
"""Explicit, resumable Cloud Run test deployment for the new-api based RS app.

Only `plan` is the default. Other stages make the changes named in --help.
Secrets stay in memory or Secret Manager, never command arguments or source files.
"""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
APIS = (
    "run.googleapis.com", "sqladmin.googleapis.com", "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com", "cloudbuild.googleapis.com", "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com", "logging.googleapis.com", "storage.googleapis.com",
)
SAFE_RUN_ANNOTATIONS = {
    "run.googleapis.com/ingress", "run.googleapis.com/ingress-status",
    "run.googleapis.com/invoker-iam-disabled", "run.googleapis.com/minScale",
    "run.googleapis.com/maxScale", "run.googleapis.com/cpu-throttling",
    "run.googleapis.com/startup-cpu-boost", "autoscaling.knative.dev/minScale",
    "autoscaling.knative.dev/maxScale", "run.googleapis.com/cloudsql-instances",
}


class DeploymentError(RuntimeError):
    pass


def execute(command, *, raw=False, cwd=None, input_bytes=None):
    result = subprocess.run(command, cwd=cwd, input=input_bytes, capture_output=True)
    if result.returncode:
        # Do not echo arbitrary API bodies, tokens, passwords, or application data.
        raise DeploymentError(f"Command failed ({result.returncode}): {' '.join(command[:4])}; inspect the Google Cloud operation in the console")
    value = result.stdout.decode().strip()
    return value if raw else json.loads(value or "null")


class Deployment:
    def __init__(self, args):
        self.args = args
        self.project = args.project
        self.region = args.region
        self.service = args.service
        self.instance = args.sql_instance
        self.repository = args.repository
        self.runtime = f"{self.service}-runtime@{self.project}.iam.gserviceaccount.com"
        self.builder = f"{self.service}-builder@{self.project}.iam.gserviceaccount.com"
        self.connection = f"{self.project}:{self.region}:{self.instance}"
        self.secret_names = {
            "password": f"{self.service}-db-password",
            "dsn": f"{self.service}-database-dsn",
            "session": f"{self.service}-session-secret",
            "admin": f"{self.service}-admin-login",
        }

    def gc(self, *args, raw=False):
        return execute([self.args.gcloud, *args, f"--project={self.project}", "--quiet", "--verbosity=error", *( [] if raw else ["--format=json"])], raw=raw)

    def api(self, url, method="GET", body=None):
        token = self.gc("auth", "print-access-token", raw=True)
        request = urllib.request.Request(
            url, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise DeploymentError(f"Google API {method} failed with HTTP {error.code}; response body suppressed because it may contain credentials") from None

    def project_info(self):
        return self.gc("projects", "describe", self.project)

    def service_info(self):
        services = self.gc("run", "services", "list", f"--region={self.region}")
        if not any(item["metadata"]["name"] == self.service for item in services):
            return None
        return self.gc("run", "services", "describe", self.service, f"--region={self.region}")

    def plan(self):
        print(json.dumps({
            "project": self.project, "region": self.region, "service": self.service,
            "cloud_run": {"cpu": 1, "memory": "1Gi", "min": 0, "service_max": 1,
                          "revision_max": 1, "concurrency": 10, "timeout_seconds": 300,
                          "cpu_throttling": False, "cpu_boost": False, "ingress": "all",
                          "public_after_bootstrap": True},
            "cloud_sql": {"name": self.instance, "version": "POSTGRES_16", "edition": "ENTERPRISE",
                          "tier": "db-f1-micro", "availability": "ZONAL", "ssd_gb": 10,
                          "storage_auto_increase": False, "retained_daily_backups": 3,
                          "point_in_time_recovery": False, "public_ip_with_connector_only": True,
                          "authorized_networks": [], "deletion_protection": True},
            "database": "rs_api", "database_user": "rs_app",
            "runtime_service_account": self.runtime, "build_service_account": self.builder,
            "artifact_registry": f"{self.region}/{self.repository}",
            "secrets": self.secret_names,
            "excluded_services": ["Redis", "VPC connector", "load balancer", "IAP", "Cloud Armor"],
            "budget_usd": 200, "budget_is_hard_spending_cap": False,
            "stages": ["inspect", "budget", "provision", "build", "deploy", "bootstrap", "publish", "verify"],
        }, ensure_ascii=False, indent=2))

    def inspect(self):
        info = self.project_info()
        billing = self.gc("billing", "projects", "describe", self.project)
        enabled = self.gc("services", "list", "--enabled")
        api_names = {item["config"]["name"] for item in enabled}
        result = {"project_number": info["projectNumber"], "billing_enabled": billing.get("billingEnabled", False), "missing_apis": sorted(set(APIS) - api_names)}
        if "run.googleapis.com" in api_names:
            service = self.service_info()
            metadata = (service or {}).get("metadata", {})
            template = (service or {}).get("spec", {}).get("template", {})
            result["service"] = None if not service else {
                "name": service["metadata"]["name"], "url": service.get("status", {}).get("url"),
                # last-applied configuration and custom annotations may contain secrets.
                "annotations": {key: value for key, value in metadata.get("annotations", {}).items() if key in SAFE_RUN_ANNOTATIONS},
                "revision_annotations": {key: value for key, value in template.get("metadata", {}).get("annotations", {}).items() if key in SAFE_RUN_ANNOTATIONS},
                "environment_names": sorted({env["name"] for container in template.get("spec", {}).get("containers", []) for env in container.get("env", [])}),
                "ready_revision": service.get("status", {}).get("latestReadyRevisionName"),
            }
        if "sqladmin.googleapis.com" in api_names:
            result["sql_instances"] = [{"name": item["name"], "region": item["region"], "version": item["databaseVersion"], "tier": item["settings"].get("tier")} for item in self.gc("sql", "instances", "list")]
        print(json.dumps(result, ensure_ascii=False, indent=2))

    def grant(self, scope, member, role):
        resource_index = 2 if scope[0] in ("artifacts", "storage") else 1
        command, resource = scope[:resource_index], scope[resource_index:]
        policy = self.gc(*command, "get-iam-policy", *resource)
        if any(item.get("role") == role and not item.get("condition") and member in item.get("members", []) for item in policy.get("bindings", [])):
            return
        self.gc(*command, "add-iam-policy-binding", *resource, f"--member={member}", f"--role={role}", "--condition=None")

    def secret(self, name, initial=None):
        names = self.gc("secrets", "list")
        if not any(item["name"].rsplit("/", 1)[-1] == name for item in names):
            if initial is None:
                raise DeploymentError(f"Missing required secret {name}; run provision first")
            self.gc("secrets", "create", name, "--replication-policy=user-managed", f"--locations={self.region}", "--labels=managed-by=rs-test-deploy")
        versions = self.gc("secrets", "versions", "list", name, "--filter=state=ENABLED")
        if not versions:
            if initial is None:
                raise DeploymentError(f"No enabled version of {name}")
            payload = initial() if callable(initial) else initial
            self.api(f"https://secretmanager.googleapis.com/v1/projects/{self.project}/secrets/{name}:addVersion", "POST", {"payload": {"data": base64.b64encode(payload.encode()).decode()}})
        data = self.api(f"https://secretmanager.googleapis.com/v1/projects/{self.project}/secrets/{name}/versions/latest:access")
        return base64.b64decode(data["payload"]["data"]).decode(), data["name"].rsplit("/", 1)[-1]

    def check_sql_profile(self, instance):
        settings = instance["settings"]
        ip = settings.get("ipConfiguration", {})
        backup = settings.get("backupConfiguration", {})
        retention = backup.get("backupRetentionSettings", {})
        if (instance["region"] != self.region or instance["databaseVersion"] != "POSTGRES_16"
                or settings.get("tier") != "db-f1-micro" or settings.get("availabilityType") != "ZONAL"
                or settings.get("edition", "ENTERPRISE") != "ENTERPRISE"
                or settings.get("dataDiskType") != "PD_SSD"
                or settings.get("storageAutoResize") or int(settings.get("dataDiskSizeGb", 0)) != 10
                or settings.get("connectorEnforcement") != "REQUIRED" or ip.get("authorizedNetworks")
                or not ip.get("ipv4Enabled") or ip.get("sslMode") != "ENCRYPTED_ONLY"
                or not backup.get("enabled") or backup.get("pointInTimeRecoveryEnabled", False)
                or int(retention.get("retainedBackups", 0)) != 3):
            raise DeploymentError("SQL instance differs from the reviewed low-cost connector-only profile; inspect before reusing or changing it")

    def provision(self):
        billing = self.gc("billing", "projects", "describe", self.project)
        if not billing.get("billingEnabled"):
            raise DeploymentError("Project billing is not enabled")
        enabled = {item["config"]["name"] for item in self.gc("services", "list", "--enabled")}
        missing = sorted(set(APIS) - enabled)
        if missing:
            self.gc("services", "enable", *missing)

        accounts = {item["email"] for item in self.gc("iam", "service-accounts", "list")}
        for email, title in ((self.runtime, "RS test runtime"), (self.builder, "RS test image builder")):
            if email not in accounts:
                self.gc("iam", "service-accounts", "create", email.split("@", 1)[0], f"--display-name={title}")
        # Build service account can write this repository, not arbitrary registries.
        repositories = self.gc("artifacts", "repositories", "list", f"--location={self.region}")
        matching = [item for item in repositories if item["name"].rsplit("/", 1)[-1] == self.repository]
        if matching and matching[0].get("format") != "DOCKER":
            raise DeploymentError("Existing Artifact Registry repository is not Docker format")
        if not matching:
            self.gc("artifacts", "repositories", "create", self.repository, f"--location={self.region}", "--repository-format=docker", "--description=RS new-api test releases")
        self.grant(["artifacts", "repositories", self.repository, f"--location={self.region}"], f"serviceAccount:{self.builder}", "roles/artifactregistry.writer")
        self.grant(["projects", self.project], f"serviceAccount:{self.builder}", "roles/logging.logWriter")
        self.grant(["projects", self.project], f"serviceAccount:{self.runtime}", "roles/cloudsql.client")

        # Dedicated source bucket: retained archives expire; no broad project storage role.
        bucket = f"{self.project}-rs-build-source"
        buckets = self.gc("storage", "buckets", "list")
        if not any(item.get("name", "").removeprefix("gs://").rstrip("/") == bucket for item in buckets):
            self.gc("storage", "buckets", "create", f"gs://{bucket}", f"--location={self.region}", "--uniform-bucket-level-access", "--public-access-prevention")
            self.api(f"https://storage.googleapis.com/storage/v1/b/{bucket}", "PATCH", {"lifecycle": {"rule": [{"action": {"type": "Delete"}, "condition": {"age": 7}}]}})
        self.grant(["storage", "buckets", f"gs://{bucket}"], f"serviceAccount:{self.builder}", "roles/storage.objectViewer")

        instances = self.gc("sql", "instances", "list")
        existing = next((item for item in instances if item["name"] == self.instance), None)
        if existing:
            self.check_sql_profile(existing)
        else:
            self.gc("sql", "instances", "create", self.instance,
                    f"--region={self.region}", "--database-version=POSTGRES_16", "--edition=ENTERPRISE",
                    "--tier=db-f1-micro", "--availability-type=zonal", "--storage-type=SSD", "--storage-size=10",
                    "--no-storage-auto-increase", "--backup-start-time=03:00", "--retained-backups-count=3",
                    f"--backup-location={self.region}", "--assign-ip", "--connector-enforcement=REQUIRED",
                    "--ssl-mode=ENCRYPTED_ONLY", "--deletion-protection", "--server-ca-mode=GOOGLE_MANAGED_INTERNAL_CA")
            # Check API defaults (especially PITR) rather than assuming they match the plan.
            self.check_sql_profile(self.gc("sql", "instances", "describe", self.instance))
        databases = self.gc("sql", "databases", "list", f"--instance={self.instance}")
        if not any(item["name"] == "rs_api" for item in databases):
            self.gc("sql", "databases", "create", "rs_api", f"--instance={self.instance}")
        password, _ = self.secret(self.secret_names["password"], lambda: secrets.token_urlsafe(36))
        users = self.gc("sql", "users", "list", f"--instance={self.instance}")
        if not any(item["name"] == "rs_app" for item in users):
            operation = self.api(f"https://sqladmin.googleapis.com/sql/v1/projects/{self.project}/instances/{self.instance}/users", "POST", {"name": "rs_app", "password": password, "type": "BUILT_IN"})
            self.gc("sql", "operations", "wait", operation["name"], "--timeout=600")
        query = urllib.parse.urlencode({"host": f"/cloudsql/{self.connection}", "sslmode": "disable"})
        dsn = f"postgresql://rs_app:{urllib.parse.quote(password, safe='')}@/rs_api?{query}"
        stored_dsn, _ = self.secret(self.secret_names["dsn"], dsn)
        if stored_dsn != dsn:
            raise DeploymentError("Stored SQL DSN differs from the selected instance/user; inspect secrets before changing an existing database connection")
        self.secret(self.secret_names["session"], lambda: secrets.token_urlsafe(48))
        # 15 bytes encode to 20 URL-safe characters, matching model.User's max20.
        self.secret(self.secret_names["admin"], lambda: json.dumps({"username": "rsadmin", "password": secrets.token_urlsafe(15)}))
        for key in ("dsn", "session"):
            self.grant(["secrets", self.secret_names[key]], f"serviceAccount:{self.runtime}", "roles/secretmanager.secretAccessor")
        print("Provisioning complete; credentials are in Secret Manager and have not been printed.")

    def budget(self):
        billing = self.gc("billing", "projects", "describe", self.project)
        if not billing.get("billingEnabled"):
            raise DeploymentError("Project billing is not enabled")
        account = billing["billingAccountName"].rsplit("/", 1)[-1]
        enabled = {item["config"]["name"] for item in self.gc("services", "list", "--enabled")}
        if "billingbudgets.googleapis.com" not in enabled:
            self.gc("services", "enable", "billingbudgets.googleapis.com")
        display_name = f"{self.service}-test-monthly-200usd"
        number = str(self.project_info()["projectNumber"])
        budgets = self.gc("billing", "budgets", "list", f"--billing-account={account}")
        existing = next((item for item in budgets if item.get("displayName") == display_name), None)
        if existing:
            amount = existing.get("amount", {}).get("specifiedAmount", {})
            projects = existing.get("budgetFilter", {}).get("projects", [])
            if amount.get("currencyCode") != "USD" or str(amount.get("units")) != "200" or projects not in ([f"projects/{self.project}"], [f"projects/{number}"]):
                raise DeploymentError("Existing named budget differs; inspect before updating it")
            print("The project-scoped USD 200 budget already exists; budget alerts are not a hard spending cap.")
            return
        self.gc("billing", "budgets", "create", f"--billing-account={account}", f"--display-name={display_name}",
                "--budget-amount=200USD", f"--filter-projects=projects/{number}", "--calendar-period=month",
                "--credit-types-treatment=exclude-all-credits", "--threshold-rule=percent=0.25",
                "--threshold-rule=percent=0.5", "--threshold-rule=percent=0.8", "--threshold-rule=percent=1.0")
        print("Created project-scoped USD 200 monthly alerts at USD 50/100/160/200. This is not an automatic spending cap.")

    def build(self):
        changed = execute(["git", "diff", "--name-only", "HEAD", "-z"], cwd=ROOT, raw=True).split("\0")
        changed += execute(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT, raw=True).split("\0")
        if any(path and not path.startswith("deploy/google-cloud/") for path in changed):
            raise DeploymentError("Application changes are uncommitted; build uses exactly git HEAD, so commit reviewed application changes first")
        revision = execute(["git", "rev-parse", "HEAD"], cwd=ROOT, raw=True)
        image = f"{self.region}-docker.pkg.dev/{self.project}/{self.repository}/new-api:{revision[:12]}"
        archive = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, check=True, capture_output=True).stdout
        with tempfile.TemporaryDirectory(prefix="rs-cloud-build-") as directory:
            execute(["tar", "-x", "-C", directory], input_bytes=archive, raw=True)
            build = self.gc("builds", "submit", directory, f"--region={self.region}", f"--config={HERE / 'cloudbuild.yaml'}",
                            f"--service-account=projects/{self.project}/serviceAccounts/{self.builder}",
                            f"--gcs-source-staging-dir=gs://{self.project}-rs-build-source/source",
                            f"--substitutions=_IMAGE={image},COMMIT_SHA={revision}", "--timeout=1800s")
        result = build[0] if isinstance(build, list) else build
        if result.get("status") != "SUCCESS":
            raise DeploymentError("Cloud Build did not report SUCCESS")
        images = result.get("results", {}).get("images", [])
        digest = next((item.get("digest") for item in images if item.get("name") == image), None)
        if not digest:
            raise DeploymentError("Cloud Build succeeded but did not return the expected image digest")
        print(json.dumps({"source_commit": revision, "build_id": result["id"], "image": f"{image.split(':')[0]}@{digest}"}, indent=2))

    def protect_bootstrap(self, service):
        if service is None:
            return
        policy = self.gc("run", "services", "get-iam-policy", self.service, f"--region={self.region}")
        for binding in policy.get("bindings", []):
            for member in ("allUsers", "allAuthenticatedUsers"):
                if binding.get("role") == "roles/run.invoker" and member in binding.get("members", []):
                    if binding.get("condition"):
                        raise DeploymentError("Conditional public invoker policy requires manual review")
                    self.gc("run", "services", "remove-iam-policy-binding", self.service, f"--region={self.region}", f"--member={member}", "--role=roles/run.invoker", "--condition=None")
        self.gc("run", "services", "update", self.service, f"--region={self.region}", "--invoker-iam-check")

    def deploy(self):
        prefix = f"{self.region}-docker.pkg.dev/{self.project}/{self.repository}/new-api@sha256:"
        if not self.args.image or not self.args.image.startswith(prefix) or not re.fullmatch(r"[0-9a-f]{64}", self.args.image[len(prefix):]):
            raise DeploymentError("deploy requires --image with the exact digest returned by build in this project's repository")
        info = self.project_info()
        old_service = self.service_info()
        origin = (old_service or {}).get("status", {}).get("url") or f"https://{self.service}-{info['projectNumber']}.{self.region}.run.app"
        self.protect_bootstrap(old_service)
        _, dsn_version = self.secret(self.secret_names["dsn"])
        _, session_version = self.secret(self.secret_names["session"])
        environment = {
            "GIN_MODE": "release", "TZ": "UTC", "NODE_TYPE": "master", "NODE_NAME": self.service,
            "SESSION_COOKIE_SECURE": "true", "SESSION_COOKIE_TRUSTED_URL": origin,
            "TRUSTED_PROXIES": "none", "MEMORY_CACHE_ENABLED": "true", "SYNC_FREQUENCY": "60",
            "RELAY_TIMEOUT": "300", "STREAMING_TIMEOUT": "240", "SHUTDOWN_TIMEOUT_SECONDS": "8",
            "BATCH_UPDATE_ENABLED": "false", "SQL_MAX_IDLE_CONNS": "2", "SQL_MAX_OPEN_CONNS": "10", "SQL_MAX_LIFETIME": "300",
            "GLOBAL_API_RATE_LIMIT": "180", "GLOBAL_WEB_RATE_LIMIT": "120",
        }
        env_flag = ",".join(f"{key}={value}" for key, value in environment.items())
        self.gc("run", "deploy", self.service, f"--region={self.region}", f"--image={self.args.image}",
                f"--service-account={self.runtime}", "--execution-environment=gen2", "--port=8080",
                "--cpu=1", "--memory=1Gi", "--min=0", "--max=1", "--min-instances=0", "--max-instances=1",
                "--concurrency=10", "--timeout=300", "--no-cpu-throttling", "--no-cpu-boost", "--ingress=all",
                "--invoker-iam-check", "--no-allow-unauthenticated", "--no-iap", "--default-url",
                "--clear-vpc-connector", "--clear-network", f"--set-cloudsql-instances={self.connection}",
                f"--set-env-vars={env_flag}",
                f"--set-secrets=SQL_DSN={self.secret_names['dsn']}:{dsn_version},SESSION_SECRET={self.secret_names['session']}:{session_version}",
                "--labels=managed-by=rs-test-deploy,purpose=internal-functional-test")
        service = self.service_info()
        url = service["status"]["url"]
        if url != origin:
            self.gc("run", "services", "update", self.service, f"--region={self.region}", f"--update-env-vars=SESSION_COOKIE_TRUSTED_URL={url}")
        self.gc("run", "services", "update-traffic", self.service, f"--region={self.region}", "--to-latest")
        print(f"Deployed with temporary IAM protection: {url}. Run bootstrap, then publish.")

    def app(self, url, path, method="GET", body=None, *, admin_token=None, google_auth=True):
        headers = {"Content-Type": "application/json", "Origin": url}
        if google_auth:
            headers["X-Serverless-Authorization"] = "Bearer " + self.gc("auth", "print-identity-token", raw=True)
        if admin_token:
            headers["Authorization"] = f"Bearer {admin_token}"
        request = urllib.request.Request(url + path, method=method, headers=headers, data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, {}

    def app_success(self, url, path, method="GET", body=None, *, admin_token=None, google_auth=True):
        status, payload = self.app(url, path, method, body, admin_token=admin_token, google_auth=google_auth)
        if status != 200 or payload.get("success") is not True:
            raise DeploymentError(f"Application check failed for {method} {path} (HTTP {status}); response suppressed")
        return payload.get("data")

    def bootstrap(self):
        service = self.service_info()
        if not service:
            raise DeploymentError("Deploy the service first")
        self.protect_bootstrap(service)
        url = service["status"]["url"]
        status, _ = self.app(url, "/api/setup", google_auth=False)
        if status not in (401, 403):
            raise DeploymentError("Unauthenticated bootstrap is not blocked by Cloud Run IAM; stop before sending admin credentials")
        credentials, _ = self.secret(self.secret_names["admin"])
        admin = json.loads(credentials)
        setup = self.app_success(url, "/api/setup")
        if not setup.get("status"):
            if setup.get("root_init"):
                raise DeploymentError("Existing root user found without completed setup; inspect rather than replace its credentials")
            self.app_success(url, "/api/setup", "POST", {"username": admin["username"], "password": admin["password"], "confirmPassword": admin["password"], "SelfUseModeEnabled": False, "DemoSiteEnabled": False})
        login = self.app_success(url, "/api/user/login", "POST", admin)
        if login.get("user", {}).get("role") != 100 or not login.get("access_token"):
            raise DeploymentError("Bootstrap credential did not obtain a root session; do not publish")
        token = login["access_token"]
        for key in ("RegisterEnabled", "PasswordRegisterEnabled"):
            self.app_success(url, "/api/option/", "PUT", {"key": key, "value": "false"}, admin_token=token)
        self.check_application(url)
        print(f"Admin initialized and public registration disabled. Login credentials remain in Secret Manager: {self.secret_names['admin']}. Safe to run publish.")

    def check_application(self, url, *, google_auth=True):
        setup = self.app_success(url, "/api/setup", google_auth=google_auth)
        status = self.app_success(url, "/api/status", google_auth=google_auth)
        if not setup.get("status") or status.get("register_enabled") is not False or status.get("password_register_enabled") is not False:
            raise DeploymentError("Application setup/registration verification failed")
        for path in ("/api/user/self", "/api/channel/?p=0&page_size=1", "/v1/models"):
            code, payload = self.app(url, path, google_auth=google_auth)
            if code not in (401, 403) and not (code == 200 and payload.get("success") is False):
                raise DeploymentError(f"Application anonymous authorization check failed: {path}")

    def publish(self):
        service = self.service_info()
        if not service:
            raise DeploymentError("Deploy and bootstrap first")
        url = service["status"]["url"]
        self.check_application(url)
        # Final requested state: no Google login / IAP / IP allowlist. App auth remains.
        self.gc("run", "services", "update", self.service, f"--region={self.region}", "--ingress=all", "--no-iap", "--no-invoker-iam-check")
        self.verify()

    def verify(self):
        service = self.service_info()
        if not service:
            raise DeploymentError("Service not found")
        url = service["status"]["url"]
        code, payload = self.app(url, "/api/status", google_auth=False)
        if (code != 200 or payload.get("success") is not True
                or payload.get("data", {}).get("register_enabled") is not False
                or payload.get("data", {}).get("password_register_enabled") is not False):
            raise DeploymentError("Public HTTPS service/status or disabled-registration check failed")
        self.check_application(url, google_auth=False)
        print(json.dumps({"url": url, "ready_revision": service["status"].get("latestReadyRevisionName"), "public_https": True, "registration": False, "application_authentication": "verified", "cloud_functional_acceptance": "still required: real login, API key, upstream, billing, stream, restart persistence"}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", nargs="?", default="plan", choices=("plan", "inspect", "budget", "provision", "build", "deploy", "bootstrap", "publish", "verify"))
    parser.add_argument("--project", default="project-0338f2b7-06cf-4c5a-989")
    parser.add_argument("--region", default="europe-west1")
    parser.add_argument("--service", default="superapi")
    parser.add_argument("--sql-instance", default="superapi-test-pg")
    parser.add_argument("--repository", default="rs-test")
    parser.add_argument("--gcloud", default=os.environ.get("RS_GCLOUD", "gcloud"))
    parser.add_argument("--image", help="Artifact Registry digest returned by the build stage")
    args = parser.parse_args()
    for name in ("project", "region", "service", "sql_instance", "repository"):
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", getattr(args, name)):
            parser.error(f"Invalid {name}")
    try:
        getattr(Deployment(args), args.stage)()
    except (DeploymentError, FileNotFoundError, urllib.error.URLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
