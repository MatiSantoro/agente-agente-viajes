"""Shared boto3 helpers for the AgentCore demo provisioning scripts."""

from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

PROFILE = "agente-agente-viajes"
REGION = "us-east-1"
ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / ".state.json"
TAGS = {"Project": "agente-agente-viajes", "ManagedBy": "Scripts", "Environment": "demo"}


@lru_cache(maxsize=1)
def session() -> boto3.Session:
    return boto3.Session(profile_name=PROFILE, region_name=REGION)


@lru_cache(maxsize=None)
def client(service_name: str):
    return session().client(service_name)


def is_error(error: ClientError, code: str) -> bool:
    return error.response["Error"].get("Code") == code


def load_state() -> dict:
    return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}


def save_state(**updates: object) -> dict:
    state = load_state()
    state.update(updates)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return state


def account_id() -> str:
    return client("sts").get_caller_identity()["Account"]


def ensure_role(name: str, trust_policy: dict, inline_policy_name: str, inline_policy: dict) -> str:
    iam = client("iam")
    try:
        role = iam.get_role(RoleName=name)["Role"]
    except ClientError as error:
        if not is_error(error, "NoSuchEntity"):
            raise
        role = iam.create_role(
            RoleName=name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Tags=[{"Key": key, "Value": value} for key, value in TAGS.items()],
        )["Role"]
        time.sleep(8)
    iam.put_role_policy(RoleName=name, PolicyName=inline_policy_name, PolicyDocument=json.dumps(inline_policy))
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
