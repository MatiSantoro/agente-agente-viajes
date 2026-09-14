"""Ensure the AgentCore Gateway with platform OAuth inbound authorization.

The provider APIs are external REST APIs from the Gateway's point of view. Their
OpenAPI targets and per-API OAuth credentials are provisioned separately by
11_external_provider_oauth.py and 12_protect_provider_apis.py (Hotels is attached
only by the live-demo step, 13_add_hotels_gateway_target.py).
"""

from __future__ import annotations

from common import TAGS, account_id, client, ensure_role, load_state, save_state, wait_for

GATEWAY_NAME = "travel-gateway"
ROLE_NAME = "agente-agente-viajes-gateway-role"
POLICY_NAME = "InvokeTravelApis"
PLATFORM_SCOPE = "travel-agent-platform/gateway.invoke"
EXTERNAL_PROVIDER_NAMES = (
    "external_travel_flights_oauth",
    "external_travel_locations_oauth",
    "external_travel_hotels_oauth",
)


def find_gateway(control) -> str | None:
    token = None
    while True:
        args = {"maxResults": 20}
        if token:
            args["nextToken"] = token
        page = control.list_gateways(**args)
        for gateway in page.get("items", []):
            if gateway.get("name") == GATEWAY_NAME:
                return gateway["gatewayId"]
        token = page.get("nextToken")
        if not token:
            return None


def main() -> None:
    state = load_state()
    required = (
        "cognito_discovery_url",
        "platform_gateway_client_id",
        "platform_gateway_scope",
        "external_provider_oauth_provider_arns",
    )
    missing = [key for key in required if not state.get(key)]
    if missing:
        raise RuntimeError(f"Run 01_cognito_identity.py, 11_external_provider_oauth.py and 14_platform_gateway_oauth.py first; missing {missing}")
    providers = state["external_provider_oauth_provider_arns"]
    missing_providers = [name for name in ("flights", "locations", "hotels") if not providers.get(name)]
    if missing_providers:
        raise RuntimeError(f"External OAuth providers are missing: {missing_providers}")

    region = state.get("region", "us-east-1")
    account = account_id()
    provider_arns = [providers[name] for name in ("flights", "locations", "hotels")]
    workload_directory_arn = f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default"
    secret_arns = [
        f"arn:aws:secretsmanager:{region}:{account}:secret:bedrock-agentcore-identity!default/oauth2/{name}-*"
        for name in EXTERNAL_PROVIDER_NAMES
    ]
    role_arn = ensure_role(
        ROLE_NAME,
        {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Principal": {"Service": "bedrock-agentcore.amazonaws.com"}, "Action": "sts:AssumeRole"}],
        },
        POLICY_NAME,
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "GetWorkloadAccessToken",
                    "Effect": "Allow",
                    "Action": "bedrock-agentcore:GetWorkloadAccessToken",
                    "Resource": [
                        workload_directory_arn,
                        f"{workload_directory_arn}/workload-identity/travel-gateway-*",
                    ],
                },
                {
                    "Sid": "GetResourceOauth2Token",
                    "Effect": "Allow",
                    "Action": "bedrock-agentcore:GetResourceOauth2Token",
                    "Resource": provider_arns,
                },
                {
                    "Sid": "GetExternalProviderOAuthSecrets",
                    "Effect": "Allow",
                    "Action": "secretsmanager:GetSecretValue",
                    "Resource": secret_arns,
                },
            ],
        },
    )

    control = client("bedrock-agentcore-control")
    gateway_id = state.get("gateway_id") or find_gateway(control)
    auth = {
        "customJWTAuthorizer": {
            "discoveryUrl": state["cognito_discovery_url"],
            "allowedClients": [state["platform_gateway_client_id"]],
            "allowedScopes": [state.get("platform_gateway_scope", PLATFORM_SCOPE)],
        }
    }
    if not gateway_id:
        response = control.create_gateway(
            name=GATEWAY_NAME,
            roleArn=role_arn,
            protocolType="MCP",
            authorizerType="CUSTOM_JWT",
            authorizerConfiguration=auth,
            description="MCP gateway for the agente-agente-viajes demo",
            tags=TAGS,
        )
        gateway_id = response["gatewayId"]
        gateway = wait_for(lambda identifier: control.get_gateway(gatewayIdentifier=identifier), gateway_id)
    else:
        gateway = control.get_gateway(gatewayIdentifier=gateway_id)
        if gateway.get("name") != GATEWAY_NAME:
            raise RuntimeError(f"Refusing to update unexpected Gateway {gateway_id}: {gateway.get('name')}")
        if gateway.get("roleArn") != role_arn or gateway.get("authorizerConfiguration") != auth:
            control.update_gateway(
                gatewayIdentifier=gateway_id,
                name=GATEWAY_NAME,
                roleArn=role_arn,
                authorizerType="CUSTOM_JWT",
                authorizerConfiguration=auth,
            )
            gateway = wait_for(lambda identifier: control.get_gateway(gatewayIdentifier=identifier), gateway_id)

    save_state(
        aws_profile="agente-agente-viajes",
        region=region,
        gateway_id=gateway_id,
        gateway_arn=gateway["gatewayArn"],
        gateway_url=gateway.get("gatewayUrl"),
        gateway_role_arn=role_arn,
    )
    print(f"Gateway: {gateway_id}")
    print(f"Inbound auth: Cognito UI pool; client {state['platform_gateway_client_id']}; scope {state.get('platform_gateway_scope', PLATFORM_SCOPE)}")
    print("Targets are provisioned separately from OpenAPI schemas with per-API OAuth (12 for Flights/Locations; 13 for Hotels).")


if __name__ == "__main__":
    main()
