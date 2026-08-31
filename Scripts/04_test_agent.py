"""Obtain a scoped Cognito M2M token and invoke the protected Harness."""

from __future__ import annotations

import json
import os
import struct
import sys
import uuid
from collections.abc import Iterator
from urllib.parse import quote

import requests

from common import REGION, client, load_state

PROMPT = "Quiero viajar desde Buenos Aires a Mendoza en septiembre de 2026. Somos 2 personas y podemos quedarnos hasta 4 noches. Buscá solamente opciones que existan en los datos conectados y recomendame la de mejor precio."
MODEL_ID = os.environ.get("MODEL_ID")


def event_type(headers: bytes) -> str | None:
    """Extract :event-type without assuming every EventStream header is a string."""
    offset = 0
    fixed_sizes = {0: 0, 1: 0, 2: 1, 3: 2, 4: 4, 5: 8, 8: 8, 9: 16}
    while offset < len(headers):
        name_length = headers[offset]
        offset += 1
        name = headers[offset : offset + name_length].decode("utf-8")
        offset += name_length
        value_type = headers[offset]
        offset += 1
        if value_type in {6, 7}:
            value_length = struct.unpack(">H", headers[offset : offset + 2])[0]
            offset += 2
            value_bytes = headers[offset : offset + value_length]
            offset += value_length
        else:
            value_bytes = headers[offset : offset + fixed_sizes.get(value_type, 0)]
            offset += fixed_sizes.get(value_type, 0)
        if name == ":event-type" and value_type == 7:
            return value_bytes.decode("utf-8")
    return None


def event_payloads(response: requests.Response) -> Iterator[dict]:
    """Decode AWS EventStream frames from InvokeHarness into typed events."""
    buffer = b""
    for chunk in response.iter_content(chunk_size=None):
        buffer += chunk
        while len(buffer) >= 12:
            total_length, headers_length = struct.unpack(">II", buffer[:8])
            if len(buffer) < total_length:
                break
            headers = buffer[12 : 12 + headers_length]
            payload = buffer[12 + headers_length : total_length - 4]
            buffer = buffer[total_length:]
            name = event_type(headers)
            if name:
                yield {name: json.loads(payload)}


def print_agent_response(response: requests.Response) -> None:
    print(
        "Harness HTTP status: "
        f"{response.status_code} ({response.headers.get('content-type', 'unknown content type')})"
    )
    response.raise_for_status()
    event_types: list[str] = []
    received_text = False
    for event in event_payloads(response):
        event_types.extend(event)
        if "contentBlockDelta" in event:
            text = event["contentBlockDelta"].get("delta", {}).get("text")
            if text:
                received_text = True
                print(text, end="", flush=True)
        elif "runtimeClientError" in event:
            print(f"\nAgent error: {event['runtimeClientError']['message']}", file=sys.stderr)
        elif "messageStop" in event:
            print(f"\nStop reason: {event['messageStop'].get('stopReason')}")
        elif "message" in event:
            print(f"\nAgent error: {event['message']}", file=sys.stderr)
    if not event_types:
        raise RuntimeError("Harness returned HTTP 200 but no EventStream events.")
    if not received_text:
        print(f"No final text returned. Stream events: {', '.join(event_types)}")


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
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.amazon.eventstream",
            "Content-Type": "application/json",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": str(uuid.uuid4()),
            "X-Amzn-Bedrock-AgentCore-Runtime-User-Id": "demo-traveler",
        },
        json={
            "messages": [{"role": "user", "content": [{"text": PROMPT}]}],
            **({"model": {"bedrockModelConfig": {"modelId": MODEL_ID, "apiFormat": "converse_stream", "maxTokens": 3000, "temperature": 0}}} if MODEL_ID else {}),
        },
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
