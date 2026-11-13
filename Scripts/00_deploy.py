"""Reproducible entrypoint for the complete Viajá demo deployment.

The implementation stays split into small, reviewable modules, but Claude (or a
human) only needs one command. The default state deliberately prepares the Hotels
backend while leaving its OAuth client, authorizer, Identity provider, and Gateway
target for the live console demo.
"""

from __future__ import annotations

import argparse
import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BASE_STEPS = (
    "07_provider_apis.py",
    "01_cognito_identity.py",
    "11_external_provider_oauth.py",
    "14_platform_gateway_oauth.py",
    "02_gateway_and_targets.py",
    "12_protect_provider_apis.py",
    "03_harness.py",
)


def run_step(filename: str) -> None:
    print(f"\n=== {filename} ===")
    runpy.run_path(str(ROOT / filename), run_name="__main__")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-ui", action="store_true", help="Provision backend and AgentCore only")
    args = parser.parse_args()

    for filename in BASE_STEPS:
        run_step(filename)
    if not args.skip_ui:
        run_step("06_ui_frontend.py")
    print("\nDeployment complete.")
    print("Hotels backend is deployed, but its OAuth and Gateway integration is intentionally absent.")
    print("Configure Hotels live in the AWS console: scope, M2M client, Identity provider, API authorizer/method scopes, IAM, then REST API target.")


if __name__ == "__main__":
    main()
