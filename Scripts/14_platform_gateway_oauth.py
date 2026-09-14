"""Create the platform OAuth credential used by Harness to call the Gateway."""

from __future__ import annotations

from botocore.exceptions import ClientError

from common import REGION, TAGS, client, is_error, load_state, save_state

RESOURCE_SERVER_ID = "travel-agent-platform"
RESOURCE_SERVER_NAME = "Travel Agent Platform"
SCOPE_NAME = "gateway.invoke"
CLIENT_NAME = "travel-agent-platform-gateway-m2m"
PROVIDER_NAME = "travel_agent_platform_gateway_oauth"


def find_provider() -> str | None:
    control = client("bedrock-agentcore-control")
    token = None
    while True:
        args = {"maxResults": 20}
        if token:
            args["nextToken"] = token
        page = control.list_oauth2_credential_providers(**args)
        for provider in page.get("credentialProviders", []):
            if provider["name"] == PROVIDER_NAME:
                return provider["credentialProviderArn"]
        token = page.get("nextToken")
        if not token:
            return None


def find_client(cognito, pool_id: str) -> str | None:
    for item in cognito.list_user_pool_clients(UserPoolId=pool_id, MaxResults=50).get("UserPoolClients", []):
        if item["ClientName"] == CLIENT_NAME:
            return item["ClientId"]
    return None


def main() -> None:
    state = load_state()
    pool_id = state["cognito_user_pool_id"]
    cognito = client("cognito-idp")
    servers = cognito.list_resource_servers(UserPoolId=pool_id, MaxResults=50).get("ResourceServers", [])
    scope = f"{RESOURCE_SERVER_ID}/{SCOPE_NAME}"
    existing = next((server for server in servers if server["Identifier"] == RESOURCE_SERVER_ID), None)
    if existing:
        cognito.update_resource_server(UserPoolId=pool_id, Identifier=RESOURCE_SERVER_ID, Name=RESOURCE_SERVER_NAME, Scopes=[{"ScopeName": SCOPE_NAME, "ScopeDescription": "Invoke the travel AgentCore Gateway"}])
    else:
        cognito.create_resource_server(UserPoolId=pool_id, Identifier=RESOURCE_SERVER_ID, Name=RESOURCE_SERVER_NAME, Scopes=[{"ScopeName": SCOPE_NAME, "ScopeDescription": "Invoke the travel AgentCore Gateway"}])
    client_id = find_client(cognito, pool_id)
    if not client_id:
        created = cognito.create_user_pool_client(
            UserPoolId=pool_id,
            ClientName=CLIENT_NAME,
            GenerateSecret=True,
            AllowedOAuthFlowsUserPoolClient=True,
            AllowedOAuthFlows=["client_credentials"],
            AllowedOAuthScopes=[scope],
            SupportedIdentityProviders=["COGNITO"],
            PreventUserExistenceErrors="ENABLED",
        )["UserPoolClient"]
        client_id, client_secret = created["ClientId"], created["ClientSecret"]
    else:
        client_secret = cognito.describe_user_pool_client(UserPoolId=pool_id, ClientId=client_id)["UserPoolClient"].get("ClientSecret")
        if not client_secret:
            raise RuntimeError("The platform M2M client has no retrievable secret")
    provider_arn = find_provider()
    if not provider_arn:
        provider_arn = client("bedrock-agentcore-control").create_oauth2_credential_provider(
            name=PROVIDER_NAME,
            credentialProviderVendor="CustomOauth2",
            oauth2ProviderConfigInput={"customOauth2ProviderConfig": {"oauthDiscovery": {"discoveryUrl": state["cognito_discovery_url"]}, "clientId": client_id, "clientSecret": client_secret, "clientSecretSource": "MANAGED"}},
            tags=TAGS,
        )["credentialProviderArn"]
    save_state(platform_gateway_resource_server_id=RESOURCE_SERVER_ID, platform_gateway_scope=scope, platform_gateway_client_id=client_id, platform_gateway_oauth_provider_arn=provider_arn)
    print(f"Platform gateway scope: {scope}")
    print(f"Platform gateway client: {client_id}")
    print("This provider is for Harness outbound auth to the Gateway; its permissions belong on the Harness role, not the Gateway role.")


if __name__ == "__main__":
    main()
