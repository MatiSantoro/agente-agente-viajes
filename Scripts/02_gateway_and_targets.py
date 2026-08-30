"""Create the protected MCP Gateway and direct API Gateway targets."""

from __future__ import annotations

import time

from botocore.exceptions import ClientError

from common import TAGS, account_id, client, ensure_role, is_error, load_state, save_state, wait_for

GATEWAY_NAME = "travel-gateway"
ROLE_NAME = "agente-agente-viajes-gateway-role"
FLIGHTS_API_ID = "5zoo2ck7cf"
HOTELS_API_ID = "2ekvs712nj"


def find_gateway() -> str | None:
    for gateway in client("bedrock-agentcore-control").list_gateways().get("items", []):
        if gateway["name"] == GATEWAY_NAME:
            return gateway["gatewayId"]
    return None


def prepare_api_for_agentcore(api_id: str, paths: list[str]) -> None:
    api_gateway = client("apigateway")
    resources = api_gateway.get_resources(restApiId=api_id, limit=500).get("items", [])
    resources_by_path = {resource["path"]: resource["id"] for resource in resources}
    for path in paths:
        resource_id = resources_by_path.get(path)
        if not resource_id:
            raise RuntimeError(f"Could not find {path} in API Gateway REST API {api_id}")
        for status_code in ("200", "404"):
            try:
                api_gateway.put_method_response(restApiId=api_id, resourceId=resource_id, httpMethod="GET", statusCode=status_code)
            except ClientError as error:
                if not is_error(error, "ConflictException"):
                    raise
    api_gateway.create_deployment(restApiId=api_id, stageName="prod", description="Add documented responses required by AgentCore target import")


def existing_target(gateway_id: str, name: str) -> dict | None:
    for target in client("bedrock-agentcore-control").list_gateway_targets(gatewayIdentifier=gateway_id).get("items", []):
        if target["name"] == name:
            return target
    return None


def main() -> None:
    control = client("bedrock-agentcore-control")
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
    gateway_id = state.get("gateway_id") or find_gateway()
    if not gateway_id:
        gateway = control.create_gateway(
            name=GATEWAY_NAME,
            roleArn=role_arn,
            protocolType="MCP",
            authorizerType="CUSTOM_JWT",
            authorizerConfiguration={"customJWTAuthorizer": {"discoveryUrl": state["cognito_discovery_url"], "allowedClients": [state["cognito_client_id"]], "allowedScopes": [state["flights_scope"], state["hotels_scope"]]}},
            description="MCP gateway for the agente-agente-viajes demo",
            tags=TAGS,
        )
        gateway_id = gateway["gatewayId"]
        gateway_arn = gateway["gatewayArn"]
        wait_for(lambda identifier: control.get_gateway(gatewayIdentifier=identifier), gateway_id)
    existing_gateway = control.get_gateway(gatewayIdentifier=gateway_id)
    gateway_arn = gateway_arn or existing_gateway["gatewayArn"]
    save_state(gateway_id=gateway_id, gateway_arn=gateway_arn, gateway_url=existing_gateway.get("gatewayUrl"), gateway_role_arn=role_arn)
    prepare_api_for_agentcore(FLIGHTS_API_ID, ["/flights", "/flights/{id}"])
    prepare_api_for_agentcore(HOTELS_API_ID, ["/hotels", "/hotels/{id}"])
    target_specs = [
        ("flights-target", FLIGHTS_API_ID, [{"name": "search_flights", "description": "Search flight options by origin, destination and date.", "path": "/flights", "method": "GET"}, {"name": "get_flight", "description": "Get one flight by its ID.", "path": "/flights/{id}", "method": "GET"}], [{"filterPath": "/flights", "methods": ["GET"]}, {"filterPath": "/flights/{id}", "methods": ["GET"]}]),
        ("hotels-target", HOTELS_API_ID, [{"name": "search_hotels", "description": "Search hotels by destination, check-in, check-out and guests.", "path": "/hotels", "method": "GET"}, {"name": "get_hotel", "description": "Get one hotel by its ID.", "path": "/hotels/{id}", "method": "GET"}], [{"filterPath": "/hotels", "methods": ["GET"]}, {"filterPath": "/hotels/{id}", "methods": ["GET"]}]),
    ]
    target_ids = {}
    for name, api_id, overrides, filters in target_specs:
        current = existing_target(gateway_id, name)
        if current and current["status"] == "FAILED":
            control.delete_gateway_target(gatewayIdentifier=gateway_id, targetId=current["targetId"])
            for _ in range(24):
                time.sleep(5)
                if not existing_target(gateway_id, name):
                    current = None
                    break
            else:
                raise TimeoutError(f"Timed out deleting failed target {name}")
        if current:
            target_ids[name] = current["targetId"]
            continue
        target = control.create_gateway_target(
            gatewayIdentifier=gateway_id,
            name=name,
            description=f"{name} for travel planning",
            targetConfiguration={"mcp": {"apiGateway": {"restApiId": api_id, "stage": "prod", "apiGatewayToolConfiguration": {"toolOverrides": overrides, "toolFilters": filters}}}},
            credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        )
        target_id = target["targetId"]
        wait_for(lambda identifier: control.get_gateway_target(gatewayIdentifier=gateway_id, targetId=identifier), target_id)
        target_ids[name] = target_id
    gateway = control.get_gateway(gatewayIdentifier=gateway_id)
    save_state(gateway_id=gateway_id, gateway_arn=gateway_arn or gateway["gatewayArn"], gateway_url=gateway.get("gatewayUrl"), gateway_role_arn=role_arn, gateway_targets=target_ids)
    print(f"Gateway ARN: {gateway_arn or gateway['gatewayArn']}")
    print(f"Gateway URL: {gateway.get('gatewayUrl', 'pending')}")


if __name__ == "__main__":
    main()
