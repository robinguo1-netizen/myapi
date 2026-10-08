#!/usr/bin/env python3
"""Deploy cheapersafer to its own Google Cloud project, separate from RS.

Run plan first. Other stages explicitly create or update only this target.
Credentials are read from the caller's gcloud configuration and Secret Manager.
"""

import argparse
import os
import sys
import urllib.error

from deploy import Deployment, DeploymentError

PROJECT = "cheapersafer-si-20261008"
RS_PROJECT = "project-0338f2b7-06cf-4c5a-989"


def deployment_args():
    return argparse.Namespace(
        project=PROJECT, region="europe-west1", service="cheapersafer",
        sql_instance="cheapersafer-pg", repository="cheapersafer",
        database="cheapersafer_api", database_user="cheapersafer_app",
        admin_username="csadmin", managed_by="cheapersafer-deploy",
        source_bucket=f"{PROJECT}-build-source", brand_name="cheapersafer.si",
        brand_logo="/cheapersafer-logo.svg", image=None,
        gcloud=os.environ.get("CS_GCLOUD", "gcloud"),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", nargs="?", default="plan", choices=("plan", "inspect", "budget", "provision", "build", "deploy", "bootstrap", "publish", "verify"))
    parser.add_argument("--image", help="Exact image digest returned by build")
    parser.add_argument("--gcloud", default=os.environ.get("CS_GCLOUD", "gcloud"))
    args = parser.parse_args()
    config = deployment_args()
    config.image, config.gcloud = args.image, args.gcloud
    if config.project == RS_PROJECT:
        parser.error("cheapersafer cannot deploy to the original RS project")
    try:
        getattr(Deployment(config), args.stage)()
    except (DeploymentError, FileNotFoundError, urllib.error.URLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
