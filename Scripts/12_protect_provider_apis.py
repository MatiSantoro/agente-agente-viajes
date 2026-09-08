"""Protect external-provider REST APIs and expose Flights and Locations as OAuth targets.

The three API backends are protected with the external provider's Cognito User Pool.
Only Flights and Locations are attached to the AgentCore Gateway. Hotels remains ready
for the live demo, where adding its OPEN_API target is the visible integration step.
"""

from __future__ import annotations

import json
import time

from botocore.exceptions import ClientError

from common import REGION, account_id, client, is_error, load_state, save_state, wait_for

EXTERNAL_POOL_NAME = "agente-agente-viajes-external-travel-provider"
GATEWAY_ID = "travel-gateway-mg1vmnirin"
API_SPECS = {
    "flights": {
        "api_id": "5zoo2ck7cf",
        "authorizer_name": "external-travel-flights-authorizer",
        "scope_suffix": "flights.read",
        "target_name": "flights-rest-api-target",
        "legacy_target_name": "flights-target",
        "paths": {
            "/flights": {
                "get": {
                    "operationId": "search_flights",
                    "summary": "Search flights by route and date",
                    "parameters": ["origin", "destination", "date", "passengers"],
                }
            },
            "/flights/{id}": {
                "get": {"operationId": "get_flight", "summary": "Get a flight by ID", "parameters": []}
            },
            "/flights/availability": {
                "get": {
                    "operationId": "find_available_flight_dates",
                    "summary": "Find dates with available flights",
                    "parameters": ["origin", "destination", "passengers"],
                }
            },
        },
    },
    "locations": {
        "api_id": "cgz8nh56v0",
        "authorizer_name": "external-travel-locations-authorizer",
        "scope_suffix": "locations.read",
        "target_name": "locations-rest-api-target",
        "legacy_target_name": "locations-target",
        "paths": {
            "/locations": {
                "get": {
                    "operationId": "resolve_travel_location",
                    "summary": "Resolve a city or airport to provider location codes",
                    "parameters": ["query"],
                }
            },
        },
    },
    "hotels": {
        "api_id": "2ekvs712nj",
        "authorizer_name": "external-travel-hotels-authorizer",
        "scope_suffix": "hotels.read",
        "target_name": "hotels-rest-api-target",
        "legacy_target_name": "hotels-target",
        "paths": {
            "/hotels": {
                "get": {
                    "operationId": "search_hotels",
                    "summary": "Search hotels by destination, dates and guest count",
                    "parameters": ["destination", "checkIn", "checkOut", "guests"],
                }
            },
            "/hotels/{id}": {
                "get": {"operationId": "get_hotel", "summary": "Get a hotel by ID", "parameters": []}
            },
            "/hotels/availability": {
                "get": {
                    "operationId": "find_available_hotel_checkins",
                    "summary": "Find available hotel stays",
                    "parameters": ["destination", "guests"],
                }
            },
        },
    },
}


def find_pool_id() -> str:
    for pool in client("cognito-idp").list_user_pools(MaxResults=50).get("UserPools", []):
        if pool["Name"] == EXTERNAL_POOL_NAME:
            return pool["Id"]
    raise RuntimeError("External provider User Pool is missing; run 11_external_provider_oauth.py first")


def ensure_authorizer(api_id: str, name: str, user_pool_arn: str) -> str:
    api = client("apigateway")
    current = next((item for item in api.get_authorizers(restApiId=api_id, limit=500)["items"] if item["name"] == name), None)
    if current:
        return current["id"]
    return api.create_authorizer(
        restApiId=api_id,
        name=name,
        type="COGNITO_USER_POOLS",
        providerARNs=[user_pool_arn],
        identitySource="method.request.header.Authorization",
    )["id"]


def protect_methods(api_id: str, authorizer_id: str, scope: str, paths: dict[str, dict]) -> None:
    api = client("apigateway")
    resources = {item["path"]: item["id"] for item in api.get_resources(restApiId=api_id, limit=500)["items"]}
    for path in paths:
        method = api.get_method(restApiId=api_id, resourceId=resources[path], httpMethod="GET")
        patch = [
            {"op": "replace", "path": "/authorizationType", "value": "COGNITO_USER_POOLS"},
            {"op": "replace", "path": "/authorizerId", "value": authorizer_id},
            {"op": "replace", "path": "/authorizationScopes", "value": scope},
            {"op": "replace", "path": "/apiKeyRequired", "value": "false"},
        ]
        try:
            api.update_method(restApiId=api_id, resourceId=resources[path], httpMethod="GET", patchOperations=patch)
        except ClientError as error:
            if not is_error(error, "BadRequestException"):
                raise
            # API Gateway sometimes exposes absent optional properties as add-only.
            api.update_method(
                restApiId=api_id,
                resourceId=resources[path],
                httpMethod="GET",
                patchOperations=[
                    {"op": "replace", "path": "/authorizationType", "value": "COGNITO_USER_POOLS"},
                    {"op": "replace", "path": "/authorizerId", "value": authorizer_id},
                    {"op": "add", "path": "/authorizationScopes", "value": scope},
                ],
            )
    for attempt in range(8):
        try:
            api.create_deployment(restApiId=api_id, stageName="prod", description="Protect external provider API with OAuth scopes")
            break
        except ClientError as error:
            if not is_error(error, "TooManyRequestsException") or attempt == 7:
                raise
            time.sleep(5 * (attempt + 1))


def openapi_schema(api_id: str, paths: dict[str, dict], scope: str, token_url: str) -> str:
    server_url = f"https://{api_id}.execute-api.{REGION}.amazonaws.com/prod"
    output_paths: dict[str, dict] = {}
    for path, methods in paths.items():
        output_paths[path] = {}
        for method, config in methods.items():
            parameters = []
            declared_parameters = list(config["parameters"])
            for path_parameter in (segment[1:-1] for segment in path.split("/") if segment.startswith("{") and segment.endswith("}")):
                if path_parameter not in declared_parameters:
                    declared_parameters.append(path_parameter)
            for parameter in declared_parameters:
                location = "path" if parameter == "id" else "query"
                parameters.append({"name": parameter, "in": location, "required": parameter in {"id", "origin", "destination", "date", "query"}, "schema": {"type": "string"}})
            output_paths[path][method] = {
                "operationId": config["operationId"],
                "summary": config["summary"],
                "parameters": parameters,
                # AgentCore's OpenAPI adapter expects a JSON response schema.
                # Keep it to the basic object type supported by the adapter.
                "responses": {
                    "200": {
                        "description": "Provider response",
                        "content": {
                            "application/json": {
                                "schema": {"type": "object"}
                            }
                        },
                    },
                    "400": {"description": "Invalid request"},
                    "404": {"description": "Not found"},
                },
            }
    return json.dumps(
        {
            "openapi": "3.0.3",
            "info": {"title": "External Travel Provider API", "version": "1.0.0"},
            "servers": [{"url": server_url}],
            "paths": output_paths,
        }
    )


def delete_target_if_present(control, gateway_id: str, target_name: str) -> None:
    existing = next((item for item in control.list_gateway_targets(gatewayIdentifier=gateway_id)["items"] if item["name"] == target_name), None)
    if existing:
        control.delete_gateway_target(gatewayIdentifier=gateway_id, targetId=existing["targetId"])
        for _ in range(24):
            targets = control.list_gateway_targets(gatewayIdentifier=gateway_id)["items"]
            if not any(item["targetId"] == existing["targetId"] for item in targets):
                return
            time.sleep(5)
        raise TimeoutError(f"Timed out deleting target {target_name}")


def ensure_openapi_target(control, gateway_id: str, spec: dict, provider_arn: str, scope: str, token_url: str) -> str:
    current = next((item for item in control.list_gateway_targets(gatewayIdentifier=gateway_id)["items"] if item["name"] == spec["target_name"]), None)
    if current and current["status"] == "FAILED":
        delete_target_if_present(control, gateway_id, spec["target_name"])
        current = None
    configuration = {"mcp": {"openApiSchema": {"inlinePayload": openapi_schema(spec["api_id"], spec["paths"], scope, token_url)}}}
    credentials = [{"credentialProviderType": "OAUTH", "credentialProvider": {"oauthCredentialProvider": {"providerArn": provider_arn, "scopes": [scope], "grantType": "CLIENT_CREDENTIALS"}}}]
    if current:
        control.update_gateway_target(
            gatewayIdentifier=gateway_id,
            targetId=current["targetId"],
            name=spec["target_name"],
            description="OAuth-protected external travel provider REST API",
            targetConfiguration=configuration,
            credentialProviderConfigurations=credentials,
        )
        target_id = current["targetId"]
    else:
        target_id = control.create_gateway_target(
            gatewayIdentifier=gateway_id,
            name=spec["target_name"],
            description="OAuth-protected external travel provider REST API",
            targetConfiguration=configuration,
            credentialProviderConfigurations=credentials,
        )["targetId"]
    wait_for(lambda identifier: control.get_gateway_target(gatewayIdentifier=gateway_id, targetId=identifier), target_id)
    return target_id


def main() -> None:
    state = load_state()
    provider_arns = state.get("external_provider_oauth_provider_arns", {})
    missing = [name for name in ("flights", "locations") if name not in provider_arns]
    if missing:
        raise RuntimeError(f"Missing OAuth providers for {missing}; run 11_external_provider_oauth.py first")
    pool_id = state.get("external_provider_user_pool_id") or find_pool_id()
    pool_arn = f"arn:aws:cognito-idp:{REGION}:{account_id()}:userpool/{pool_id}"
    resource_server = state.get("external_provider_resource_server_id", "travel-provider-api")
    token_url = f"https://{state['external_provider_domain']}.auth.{REGION}.amazoncognito.com/oauth2/token"
    gateway_id = state.get("gateway_id", GATEWAY_ID)
    control = client("bedrock-agentcore-control")

    # Retire direct targets first. OPEN_API targets below are the OAuth-capable replacements.
    for spec in API_SPECS.values():
        delete_target_if_present(control, gateway_id, spec["legacy_target_name"])

    target_ids: dict[str, str] = {}
    for name in ("flights", "locations"):
        spec = API_SPECS[name]
        scope = f"{resource_server}/{spec['scope_suffix']}"
        target_ids[name] = ensure_openapi_target(control, gateway_id, spec, provider_arns[name], scope, token_url)

    # Hotels is fully protected, but deliberately has no Gateway target until the live demo.
    for spec in API_SPECS.values():
        scope = f"{resource_server}/{spec['scope_suffix']}"
        authorizer_id = ensure_authorizer(spec["api_id"], spec["authorizer_name"], pool_arn)
        protect_methods(spec["api_id"], authorizer_id, scope, spec["paths"])

    save_state(external_provider_authorizers={name: spec["authorizer_name"] for name, spec in API_SPECS.items()}, external_provider_openapi_target_ids=target_ids)
    print("Flights, Locations and Hotels API methods now require their OAuth scope.")
    print("Flights and Locations are connected as OPEN_API targets. Hotels has no target yet.")


if __name__ == "__main__":
    main()
