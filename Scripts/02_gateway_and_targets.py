"""Create the protected MCP Gateway and direct API Gateway targets."""

from __future__ import annotations

from common import TAGS, account_id, aws_cli, ensure_role, load_state, save_state, wait_for

GATEWAY_NAME = "travel_gateway"
ROLE_NAME = "agente-agente-viajes-gateway-role"
FLIGHTS_API_ID = "5zoo2ck7cf"
HOTELS_API_ID = "2ekvs712nj"


def main() -> None:
    state = load_state()
    required = ["cognito_discovery_url", "cognito_client_id", "flights_scope", "hotels_scope", "credential_provider_arn"]
    missing = [key for key in required if key not in state]
    if missing:
        raise RuntimeError(f"Run 01_cognito_identity.py first; missing {missing}")

    account = account_id()
    role_arn = ensure_role(
        ROLE_NAME,
        {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "bedrock-agentcore.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
        "InvokeTravelApis",
        {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "execute-api:Invoke", "Resource": [f"arn:aws:execute-api:{state['region']}:{account}:{FLIGHTS_API_ID}/prod/*", f"arn:aws:execute-api:{state['region']}:{account}:{HOTELS_API_ID}/prod/*"]}]},
    )

    gateway_arn = state.get("gateway_arn")
    gateway_id = state.get("gateway_id")
    if not gateway_id:
        gateway = aws_cli(
            ["bedrock-agentcore-control", "create-gateway"],
            {"name": GATEWAY_NAME, "roleArn": role_arn, "protocolType": "MCP", "authorizerType": "CUSTOM_JWT", "authorizerConfiguration": {"customJWTAuthorizer": {"discoveryUrl": state["cognito_discovery_url"], "allowedClients": [state["cognito_client_id"]], "allowedScopes": [state["flights_scope"], state["hotels_scope"]]}}, "description": "MCP gateway for the agente-agente-viajes demo", "tags": TAGS},
        )
        gateway_id = gateway["gatewayId"]
        gateway_arn = gateway["gatewayArn"]
        wait_for(lambda identifier: aws_cli(["bedrock-agentcore-control", "get-gateway", "--gateway-identifier", identifier]), gateway_id)

    target_specs = [
        ("flights_target", FLIGHTS_API_ID, state["flights_scope"], [{"name": "search_flights", "description": "Search flight options by origin, destination and date.", "path": "/flights", "method": "GET"}, {"name": "get_flight", "description": "Get one flight by its ID.", "path": "/flights/{id}", "method": "GET"}]),
        ("hotels_target", HOTELS_API_ID, state["hotels_scope"], [{"name": "search_hotels", "description": "Search hotels by destination, check-in, check-out and guests.", "path": "/hotels", "method": "GET"}, {"name": "get_hotel", "description": "Get one hotel by its ID.", "path": "/hotels/{id}", "method": "GET"}]),
    ]
    target_arns = {}
    for name, api_id, scope, overrides in target_specs:
        target = aws_cli(
            ["bedrock-agentcore-control", "create-gateway-target"],
            {
                "gatewayIdentifier": gateway_id,
                "name": name,
                "description": f"{name} for travel planning",
                "targetConfiguration": {"mcp": {"apiGateway": {"restApiId": api_id, "stage": "prod", "apiGatewayToolConfiguration": {"toolOverrides": overrides}}}},
                "credentialProviderConfigurations": [{"credentialProviderType": "OAUTH", "credentialProvider": {"oauthCredentialProvider": {"providerArn": state["credential_provider_arn"], "grantType": "CLIENT_CREDENTIALS", "scopes": [scope]}}}],
            },
        )
        target_arns[name] = target["targetArn"]

    gateway = aws_cli(["bedrock-agentcore-control", "get-gateway", "--gateway-identifier", gateway_id])
    save_state(gateway_id=gateway_id, gateway_arn=gateway_arn or gateway["gatewayArn"], gateway_url=gateway.get("gatewayUrl"), gateway_role_arn=role_arn, gateway_targets=target_arns)
    print(f"Gateway ARN: {gateway_arn or gateway['gatewayArn']}")
    print(f"Gateway URL: {gateway.get('gatewayUrl', 'pending')}")


if __name__ == "__main__":
    main()
