"""Create a Harness that uses the AgentCore Gateway as its tool surface."""

from __future__ import annotations

from common import REGION, TAGS, account_id, client, ensure_role, load_state, save_state, wait_for

HARNESS_NAME = "travel_agent"
ROLE_NAME = "agente-agente-viajes-harness-role"
MODEL_ID = "us.anthropic.claude-sonnet-4-6"
MODEL_MAX_TOKENS = 3000
MODEL_TEMPERATURE = 0
MAX_ITERATIONS = 8
UI_SESSION_SCOPE = "aws.cognito.signin.user.admin"
SYSTEM_PROMPT = """You are Viajá, a reliable travel-planning assistant. Reply in the user's language.

Your capabilities are defined exclusively by the tools available in this session. Read their descriptions and schemas before using them. Tool results are the source of truth: never invent availability, prices, schedules, policies, ratings, locations, dates, or market claims. The runtime context provides today's date; resolve a month or relative date with no year to its next future occurrence.

Use discovery tools when they are available before proposing a value that must exist in connected data. Suggest only values returned by a discovery tool. When a resolved entity contains a parent identifier plus child values marked usable for search, never send the parent identifier to a downstream search; use the usable child values instead. Preserve user constraints exactly: do not convert days into nights, assume missing dates, or silently broaden a request. An empty result proves only the exact filters queried, never an entire category or month. If the request needs a capability not represented by an available tool, state plainly that no connected source is available for that information in this session. Never suggest an option, category, provider, link, or workaround that cannot be searched or confirmed using connected tools.

Write concise, polished Markdown with clear spacing. Separate confirmed data from suggestions. Use no emojis. Do not narrate tool calls, waiting, retries, or internal reasoning; never emit an interim progress update. Do not expose tool names, API names, internal IDs, or chain-of-thought. Never claim a booking was made. If information is missing and no discovery tool can provide it, ask one focused question."""


def find_harness() -> str | None:
    for harness in client("bedrock-agentcore-control").list_harnesses().get("harnesses", []):
        if harness["harnessName"] == HARNESS_NAME:
            return harness["harnessId"]
    return None


def main() -> None:
    control = client("bedrock-agentcore-control")
    state = load_state()
    required = ["gateway_arn", "platform_gateway_oauth_provider_arn", "platform_gateway_scope", "platform_gateway_client_id"]
    missing = [key for key in required if key not in state]
    if missing:
        raise RuntimeError(f"Run 01 and 02 first; missing {missing}")
    # Harness is called by the signed-in UI user and by the platform M2M
    # client used for CLI smoke tests. The old travel-api scopes belonged to
    # the retired resource server and must not remain here.
    allowed_clients = [state["platform_gateway_client_id"]]
    if state.get("ui_cognito_client_id"):
        allowed_clients.append(state["ui_cognito_client_id"])
    allowed_clients = list(dict.fromkeys(allowed_clients))
    allowed_scopes = [state["platform_gateway_scope"], UI_SESSION_SCOPE]
    desired_authorizer = {
        "customJWTAuthorizer": {
            "discoveryUrl": state["cognito_discovery_url"],
            "allowedClients": allowed_clients,
            "allowedScopes": allowed_scopes,
        }
    }
    authorizer_request = {"optionalValue": desired_authorizer}
    account = account_id()
    role_arn = ensure_role(
        ROLE_NAME,
        {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "bedrock-agentcore.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
        "RunTravelHarness",
        {
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"], "Resource": "*"},
                {"Effect": "Allow", "Action": "bedrock-agentcore:InvokeGateway", "Resource": state["gateway_arn"]},
                {
                    "Effect": "Allow",
                    "Action": "bedrock-agentcore:GetResourceOauth2Token",
                    "Resource": [
                        state["platform_gateway_oauth_provider_arn"],
                        f"arn:aws:bedrock-agentcore:{REGION}:{account}:token-vault/default",
                        f"arn:aws:bedrock-agentcore:{REGION}:{account}:workload-identity-directory/default",
                        f"arn:aws:bedrock-agentcore:{REGION}:{account}:workload-identity-directory/default/workload-identity/harness_{HARNESS_NAME}-*",
                    ],
                },
                {
                    "Effect": "Allow",
                    "Action": "secretsmanager:GetSecretValue",
                    "Resource": f"arn:aws:secretsmanager:{REGION}:{account}:secret:bedrock-agentcore-identity!default/oauth2/travel_agent_platform_gateway_oauth-*",
                },
            ],
        },
    )
    harness_id = state.get("harness_id") or find_harness()
    if not harness_id:
        response = control.create_harness(
            harnessName=HARNESS_NAME,
            executionRoleArn=role_arn,
            model={"bedrockModelConfig": {"modelId": MODEL_ID, "apiFormat": "converse_stream", "maxTokens": MODEL_MAX_TOKENS, "temperature": MODEL_TEMPERATURE}},
            systemPrompt=[{"text": SYSTEM_PROMPT}],
            tools=[{"type": "agentcore_gateway", "name": "travel_gateway", "config": {"agentCoreGateway": {"gatewayArn": state["gateway_arn"], "outboundAuth": {"oauth": {"providerArn": state["platform_gateway_oauth_provider_arn"], "grantType": "CLIENT_CREDENTIALS", "scopes": [state["platform_gateway_scope"]]}}}}}],
            authorizerConfiguration=authorizer_request,
            memory={"disabled": {}},
            maxIterations=MAX_ITERATIONS,
            maxTokens=MODEL_MAX_TOKENS,
            timeoutSeconds=300,
            tags=TAGS,
        )
        harness_id = response["harness"]["harnessId"]
    ready = wait_for(lambda identifier: control.get_harness(harnessId=identifier)["harness"], harness_id)
    current_model_id = ready.get("model", {}).get("bedrockModelConfig", {}).get("modelId")
    current_model = ready.get("model", {}).get("bedrockModelConfig", {})
    changes = {}
    if (
        current_model_id != MODEL_ID
        or current_model.get("maxTokens") != MODEL_MAX_TOKENS
        or current_model.get("temperature") != MODEL_TEMPERATURE
    ):
        changes["model"] = {"bedrockModelConfig": {"modelId": MODEL_ID, "apiFormat": "converse_stream", "maxTokens": MODEL_MAX_TOKENS, "temperature": MODEL_TEMPERATURE}}
        changes["maxTokens"] = MODEL_MAX_TOKENS
    if ready.get("maxIterations") != MAX_ITERATIONS:
        changes["maxIterations"] = MAX_ITERATIONS
    if ready.get("authorizerConfiguration") != desired_authorizer:
        changes["authorizerConfiguration"] = authorizer_request
    if ready.get("systemPrompt") != [{"text": SYSTEM_PROMPT}]:
        changes["systemPrompt"] = [{"text": SYSTEM_PROMPT}]
    desired_tools = [{"type": "agentcore_gateway", "name": "travel_gateway", "config": {"agentCoreGateway": {"gatewayArn": state["gateway_arn"], "outboundAuth": {"oauth": {"providerArn": state["platform_gateway_oauth_provider_arn"], "grantType": "CLIENT_CREDENTIALS", "scopes": [state["platform_gateway_scope"]]}}}}}]
    if ready.get("tools") != desired_tools:
        changes["tools"] = desired_tools
    if changes:
        control.update_harness(harnessId=harness_id, **changes)
        ready = wait_for(lambda identifier: control.get_harness(harnessId=identifier)["harness"], harness_id)
    save_state(harness_id=harness_id, harness_arn=ready["arn"], harness_role_arn=role_arn)
    print(f"Harness ARN: {ready['arn']}")


if __name__ == "__main__":
    main()
