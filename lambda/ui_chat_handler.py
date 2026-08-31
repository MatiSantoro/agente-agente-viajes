"""Cognito-protected browser bridge for the AgentCore travel Harness."""

from __future__ import annotations

import json
import os
import struct
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

HARNESS_ARN = os.environ["HARNESS_ARN"]
REGION = os.environ["AWS_REGION"]
MODEL_CONFIGS = {
    "claude": "us.anthropic.claude-sonnet-4-6",
    "nova": "amazon.nova-pro-v1:0",
}


def response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Authorization,Content-Type", "Access-Control-Allow-Methods": "POST,OPTIONS", "Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def header_event_type(headers: bytes) -> str:
    offset = 0
    while offset < len(headers):
        name_length = headers[offset]
        offset += 1
        name = headers[offset : offset + name_length].decode("utf-8")
        offset += name_length + 1
        value_length = struct.unpack(">H", headers[offset : offset + 2])[0]
        offset += 2
        value = headers[offset : offset + value_length].decode("utf-8")
        offset += value_length
        if name == ":event-type":
            return value
    return "unknown"


def read_markdown(stream: bytes) -> str:
    output: list[str] = []
    error: str | None = None
    while len(stream) >= 16:
        total_length, headers_length = struct.unpack(">II", stream[:8])
        frame, stream = stream[:total_length], stream[total_length:]
        payload = json.loads(frame[12 + headers_length : -4])
        event_name = header_event_type(frame[12 : 12 + headers_length])
        if event_name == "contentBlockDelta":
            output.append(payload.get("delta", {}).get("text", ""))
        elif event_name in {"runtimeClientError", "internalServerException", "validationException"}:
            error = payload.get("message", event_name)
    if error:
        raise RuntimeError(error)
    return "".join(output)


def lambda_handler(event: dict, _context: object) -> dict:
    if event.get("httpMethod") == "OPTIONS":
        return response(200, {})
    try:
        payload = json.loads(event.get("body") or "{}")
        message = str(payload["message"]).strip()
        session_id = str(payload["sessionId"])
        model_name = str(payload.get("model", "claude"))
        temperature = float(payload.get("temperature", 0.2))
        if not message or len(message) > 4000:
            raise ValueError("message must contain 1–4000 characters")
        if model_name not in MODEL_CONFIGS:
            raise ValueError("Unsupported model")
        if model_name == "nova":
            temperature = 0
        elif not 0 <= temperature <= 1:
            raise ValueError("temperature must be between 0 and 1")
        authorization = (event.get("headers") or {}).get("Authorization") or (event.get("headers") or {}).get("authorization")
        if not authorization:
            return response(401, {"message": "Missing Cognito access token"})
        if not authorization.startswith("Bearer "):
            authorization = f"Bearer {authorization}"
        today = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date().isoformat()
        runtime_context = (
            f"Runtime date: {today} (America/Argentina/Buenos_Aires). "
            "Treat a month or relative date with no year as its next future occurrence. "
            "This context is authoritative and must not be shown to the user.\n\n"
        )
        invoke_body = json.dumps({
            "maxTokens": 3000,
            "messages": [{"role": "user", "content": [{"text": runtime_context + message}]}],
            "model": {"bedrockModelConfig": {"modelId": MODEL_CONFIGS[model_name], "apiFormat": "converse_stream", "maxTokens": 3000, "temperature": temperature}},
        }).encode("utf-8")
        endpoint = f"https://bedrock-agentcore.{REGION}.amazonaws.com/harnesses/invoke?harnessArn={urllib.parse.quote(HARNESS_ARN, safe='')}"
        request = urllib.request.Request(endpoint, data=invoke_body, headers={"Authorization": authorization, "Accept": "application/vnd.amazon.eventstream", "Content-Type": "application/json", "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id, "X-Amzn-Bedrock-AgentCore-Runtime-User-Id": "travel-ui"}, method="POST")
        with urllib.request.urlopen(request, timeout=300) as upstream:
            markdown = read_markdown(upstream.read())
        return response(200, {"markdown": markdown or "The agent did not return a final response."})
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        return response(400, {"message": str(error)})
    except Exception as error:
        return response(502, {"message": f"Agent request failed: {error}"})
