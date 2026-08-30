"""Create a Harness that uses the AgentCore Gateway as its tool surface."""

from __future__ import annotations

from common import TAGS, aws_cli, ensure_role, load_state, save_state, wait_for

HARNESS_NAME = "travel_agent"
ROLE_NAME = "agente-agente-viajes-harness-role"


def main() -> None:
    state = load_state()
    required = ["gateway_arn", "credential_provider_arn", "flights_scope", "hotels_scope", "cognito_discovery_url", "cognito_client_id"]
    missing = [key for key in required if key not in state]
    if missing:
        raise RuntimeError(f"Run 01 and 02 first; missing {missing}")

    role_arn = ensure_role(
        ROLE_NAME,
        {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "bedrock-agentcore.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
        "RunTravelHarness",
        {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], "Resource": "*"}, {"Effect": "Allow", "Action": "bedrock-agentcore:InvokeGateway", "Resource": state["gateway_arn"]}]},
    )

    harness = aws_cli(
        ["bedrock-agentcore-control", "create-harness"],
        {
            "harnessName": HARNESS_NAME,
            "executionRoleArn": role_arn,
            "model": {"bedrockModelConfig": {"modelId": "amazon.nova-lite-v1:0", "apiFormat": "converse_stream", "maxTokens": 1024, "temperature": 0.2}},
            "systemPrompt": [{"text": "You are a helpful travel-planning agent. Use the available flight and hotel tools, clearly state assumptions, and propose compatible flight and hotel combinations."}],
            "tools": [{"type": "agentcore_gateway", "name": "travel_gateway", "config": {"agentCoreGateway": {"gatewayArn": state["gateway_arn"], "outboundAuth": {"oauth": {"providerArn": state["credential_provider_arn"], "grantType": "CLIENT_CREDENTIALS", "scopes": [state["flights_scope"], state["hotels_scope"]]}}}}}],
            "authorizerConfiguration": {"customJWTAuthorizer": {"discoveryUrl": state["cognito_discovery_url"], "allowedClients": [state["cognito_client_id"]], "allowedScopes": [state["flights_scope"], state["hotels_scope"]]}},
            "memory": {"disabled": {}},
            "maxIterations": 6,
            "maxTokens": 1024,
            "timeoutSeconds": 300,
            "tags": TAGS,
        },
    )
    harness_id = harness["harnessId"]
    ready = wait_for(lambda identifier: aws_cli(["bedrock-agentcore-control", "get-harness", "--harness-identifier", identifier]), harness_id)
    save_state(harness_id=harness_id, harness_arn=ready["harnessArn"], harness_role_arn=role_arn)
    print(f"Harness ARN: {ready['harnessArn']}")


if __name__ == "__main__":
    main()
