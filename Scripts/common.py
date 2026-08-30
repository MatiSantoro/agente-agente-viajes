"""Shared helpers for the AgentCore demo provisioning scripts."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path

PROFILE = "agente-agente-viajes"
REGION = "us-east-1"
ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / ".state.json"
TAGS = {"Project": "agente-agente-viajes", "ManagedBy": "Scripts", "Environment": "demo"}


class AwsCliError(RuntimeError):
    pass


def aws_cli(arguments: list[str], payload: dict | None = None) -> dict:
    """Call AWS CLI with the project profile; never prints request secrets."""
    command = ["aws", *arguments, "--profile", PROFILE, "--region", REGION, "--output", "json"]
    payload_path = None
    if payload is not None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as stream:
            stream.write(json.dumps(payload))
            payload_path = stream.name
        command.extend(["--cli-input-json", f"file://{payload_path}"])
    try:
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
    finally:
        if payload_path:
            Path(payload_path).unlink(missing_ok=True)
    if completed.returncode:
        raise AwsCliError(completed.stderr.strip() or completed.stdout.strip())
    return json.loads(completed.stdout) if completed.stdout.strip() else {}


def load_state() -> dict:
    return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}


def save_state(**updates: object) -> dict:
    state = load_state()
    state.update(updates)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return state


def account_id() -> str:
    return aws_cli(["sts", "get-caller-identity"])["Account"]


def ensure_role(name: str, trust_policy: dict, inline_policy_name: str, inline_policy: dict) -> str:
    try:
        role = aws_cli(["iam", "get-role", "--role-name", name])["Role"]
    except AwsCliError as error:
        if "NoSuchEntity" not in str(error):
            raise
        role = aws_cli(
            ["iam", "create-role"],
            {"RoleName": name, "AssumeRolePolicyDocument": json.dumps(trust_policy), "Tags": [{"Key": k, "Value": v} for k, v in TAGS.items()]},
        )["Role"]
        time.sleep(8)
    aws_cli(
        ["iam", "put-role-policy"],
        {"RoleName": name, "PolicyName": inline_policy_name, "PolicyDocument": json.dumps(inline_policy)},
    )
    return role["Arn"]


def wait_for(getter, identifier: str, terminal: str = "READY", attempts: int = 60) -> dict:
    for _ in range(attempts):
        response = getter(identifier)
        status = response.get("status")
        if status == terminal:
            return response
        if status in {"FAILED", "DELETE_FAILED"}:
            raise RuntimeError(f"{identifier} entered {status}: {response}")
        time.sleep(5)
    raise TimeoutError(f"{identifier} did not reach {terminal} in time")
