"""Remove legacy platform OAuth and Hotels OAuth Cognito configuration for the live demo."""

from __future__ import annotations

import json

from botocore.exceptions import ClientError

from common import REGION, STATE_PATH, account_id, client, is_error, load_state

LEGACY_RESOURCE_SERVER = "travel-api"
HOTELS_SCOPE = "hotels.read"
PROVIDER_NAMES = ("external_travel_hotels_oauth", "travel_cognito_oauth")


def delete_client(cognito, pool_id: str, client_id: str) -> None:
    try:
        cognito.delete_user_pool_client(UserPoolId=pool_id, ClientId=client_id)
    except ClientError as error:
        if not is_error(error, "ResourceNotFoundException"):
            raise


def delete_identity_provider(control, name: str) -> str | None:
    try:
        control.delete_oauth2_credential_provider(name=name)
        return f"arn:aws:bedrock-agentcore:{REGION}:{account_id()}:token-vault/default/oauth2credentialprovider/{name}"
    except ClientError as error:
        if not is_error(error, "ResourceNotFoundException"):
            raise
        return None


def remove_provider_permissions(arns: list[str]) -> None:
    iam = client("iam")
    policy = iam.get_role_policy(RoleName="agente-agente-viajes-gateway-role", PolicyName="InvokeTravelApis")["PolicyDocument"]
    removed = {arn for arn in arns if arn}
    for statement in policy.get("Statement", []):
        if statement.get("Sid") == "RetrieveOAuthCredentialsForGatewayTargets":
            resources = statement.get("Resource", [])
            statement["Resource"] = [resource for resource in resources if resource not in removed]
    iam.put_role_policy(RoleName="agente-agente-viajes-gateway-role", PolicyName="InvokeTravelApis", PolicyDocument=json.dumps(policy))


def main() -> None:
    state = load_state()
    cognito = client("cognito-idp")

    # The old Harness-to-Gateway client is replaced by travel-agent-platform.
    legacy_client = state.get("cognito_client_id")
    if legacy_client:
        delete_client(cognito, state["cognito_user_pool_id"], legacy_client)
    try:
        cognito.delete_resource_server(UserPoolId=state["cognito_user_pool_id"], Identifier=LEGACY_RESOURCE_SERVER)
    except ClientError as error:
        if not is_error(error, "ResourceNotFoundException"):
            raise

    # Hotels stays backend-protected, but its provider-facing Cognito scope and M2M
    # client are intentionally recreated during the live-add demo.
    external_pool = state["external_provider_user_pool_id"]
    hotel_client = state.get("external_provider_clients", {}).get("hotels")
    if hotel_client:
        delete_client(cognito, external_pool, hotel_client)
    servers = cognito.list_resource_servers(UserPoolId=external_pool, MaxResults=50).get("ResourceServers", [])
    resource_server = next(server for server in servers if server["Identifier"] == state["external_provider_resource_server_id"])
    remaining_scopes = [scope for scope in resource_server.get("Scopes", []) if scope["ScopeName"] != HOTELS_SCOPE]
    cognito.update_resource_server(
        UserPoolId=external_pool,
        Identifier=resource_server["Identifier"],
        Name=resource_server["Name"],
        Scopes=remaining_scopes,
    )

    control = client("bedrock-agentcore-control")
    deleted_arns = []
    for provider_name in PROVIDER_NAMES:
        provider_arn = delete_identity_provider(control, provider_name)
        if provider_arn:
            deleted_arns.append(provider_arn)
    remove_provider_permissions(deleted_arns)

    clients = {key: value for key, value in state.get("external_provider_clients", {}).items() if key != "hotels"}
    scopes = {key: value for key, value in state.get("external_provider_scopes", {}).items() if key != "hotels"}
    providers = {key: value for key, value in state.get("external_provider_oauth_provider_arns", {}).items() if key != "hotels"}
    state.update(external_provider_clients=clients, external_provider_scopes=scopes, external_provider_oauth_provider_arns=providers)
    state.pop("credential_provider_arn", None)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    print("Removed legacy Travel API and Hotels Cognito configuration plus the two unused AgentCore Identity providers.")


if __name__ == "__main__":
    main()
