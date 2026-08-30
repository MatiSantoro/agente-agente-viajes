"""Obtain a scoped Cognito M2M token and invoke the protected Harness."""

from __future__ import annotations

import json
import struct
import sys
import uuid
from collections.abc import Iterator
from urllib.parse import quote

import requests

from common import REGION, client, load_state

PROMPT = "Find a flight from EZE to BRC on 2026-09-10 and a compatible hotel for two guests for four nights. Recommend one combination."


def event_payloads(response: requests.Response) -> Iterator[dict]:
    """Decode the AWS EventStream frames returned by InvokeHarness."""
    buffer = b""
    for chunk in response.iter_content(chunk_size=None):
        buffer += chunk
        while len(buffer) >= 12:
            total_length, headers_length = struct.unpack(">II", buffer[:8])
            if len(buffer) < total_length:
                break
            payload = buffer[12 + headers_length : total_length - 4]
            buffer = buffer[total_length:]
            yield json.loads(payload)


def print_agent_response(response: requests.Response) -> None:
    print(f"Harness HTTP status: {response.status_code}")
    response.raise_for_status()
    for event in event_payloads(response):
        if "contentBlockDelta" in event:
            text = event["contentBlockDelta"].get("delta", {}).get("text")
            if text:
                print(text, end="", flush=True)
        elif "runtimeClientError" in event:
            print(f"\nAgent error: {event['runtimeClientError']['message']}", file=sys.stderr)
        elif "messageStop" in event:
            print(f"\nStop reason: {event['messageStop'].get('stopReason')}")


def main() -> None:
    state = load_state()
    required = ["cognito_domain", "cognito_user_pool_id", "cognito_client_id", "harness_arn", "flights_scope", "hotels_scope"]
    missing = [key for key in required if key not in state]
    if missing:
        raise RuntimeError(f"Run scripts 01–03 first; missing {missing}")
    user_pool_client = client("cognito-idp").describe_user_pool_client(UserPoolId=state["cognito_user_pool_id"], ClientId=state["cognito_client_id"])["UserPoolClient"]
    token_url = f"https://{state['cognito_domain']}.auth.{REGION}.amazoncognito.com/oauth2/token"
    try:
        token_response = requests.post(
            token_url,
            auth=(state["cognito_client_id"], user_pool_client["ClientSecret"]),
            data={"grant_type": "client_credentials", "scope": f"{state['flights_scope']} {state['hotels_scope']}"},
            timeout=30,
        )
    except requests.ConnectionError as error:
        raise RuntimeError(f"Cognito hosted-domain DNS is not ready yet: {token_url}. Wait for propagation, then retry.") from error
    token_response.raise_for_status()
    access_token = token_response.json()["access_token"]
    endpoint = f"https://bedrock-agentcore.{REGION}.amazonaws.com/harnesses/invoke?harnessArn={quote(state['harness_arn'], safe='')}"
    response = requests.post(
        endpoint,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": str(uuid.uuid4()), "X-Amzn-Bedrock-AgentCore-Runtime-User-Id": "demo-traveler"},
        json={"messages": [{"role": "user", "content": [{"text": PROMPT}]}]},
        timeout=310,
        stream=True,
    )
    print_agent_response(response)


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as error:
        print(error.response.text, file=sys.stderr)
        raise
