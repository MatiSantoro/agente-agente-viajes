"""Create Cognito scopes and an AgentCore Identity OAuth credential provider."""

from __future__ import annotations

from botocore.exceptions import ClientError

from common import PROFILE, REGION, TAGS, account_id, client, is_error, load_state, save_state

POOL_NAME = "agente-agente-viajes"
RESOURCE_SERVER_ID = "travel-api"
RESOURCE_SERVER_NAME = "Travel API"
CLIENT_NAME = "agente-agente-viajes-m2m"
PROVIDER_NAME = "travel_cognito_oauth"
SCOPES = [
    {"ScopeName": "flights.read", "ScopeDescription": "Read flight options"},
    {"ScopeName": "hotels.read", "ScopeDescription": "Read hotel options"},
]


def find_user_pool() -> str | None:
    for pool in client("cognito-idp").list_user_pools(MaxResults=50).get("UserPools", []):
        if pool["Name"] == POOL_NAME:
            return pool["Id"]
    return None


def find_client(pool_id: str) -> str | None:
    for item in client("cognito-idp").list_user_pool_clients(UserPoolId=pool_id, MaxResults=50).get("UserPoolClients", []):
        if item["ClientName"] == CLIENT_NAME:
            return item["ClientId"]
    return None


def find_provider() -> str | None:
    for item in client("bedrock-agentcore-control").list_oauth2_credential_providers().get("items", []):
        if item["name"] == PROVIDER_NAME:
            return item["credentialProviderArn"]
    return None


def main() -> None:
    cognito = client("cognito-idp")
    control = client("bedrock-agentcore-control")
    state = load_state()
    pool_id = state.get("cognito_user_pool_id") or find_user_pool()
    if not pool_id:
        pool_id = cognito.create_user_pool(PoolName=POOL_NAME, UserPoolTags=TAGS)["UserPool"]["Id"]
    servers = cognito.list_resource_servers(UserPoolId=pool_id, MaxResults=50).get("ResourceServers", [])
    if not any(server["Identifier"] == RESOURCE_SERVER_ID for server in servers):
        cognito.create_resource_server(UserPoolId=pool_id, Identifier=RESOURCE_SERVER_ID, Name=RESOURCE_SERVER_NAME, Scopes=SCOPES)
    client_id = state.get("cognito_client_id") or find_client(pool_id)
    if not client_id:
        response = cognito.create_user_pool_client(
            UserPoolId=pool_id,
            ClientName=CLIENT_NAME,
            GenerateSecret=True,
            AllowedOAuthFlowsUserPoolClient=True,
            AllowedOAuthFlows=["client_credentials"],
            AllowedOAuthScopes=[f"{RESOURCE_SERVER_ID}/flights.read", f"{RESOURCE_SERVER_ID}/hotels.read"],
            SupportedIdentityProviders=["COGNITO"],
        )
        client_id = response["UserPoolClient"]["ClientId"]
    domain = f"agente-agente-viajes-{account_id()}"
    try:
        domain_description = cognito.describe_user_pool_domain(Domain=domain).get("DomainDescription", {})
        if not domain_description.get("UserPoolId"):
            cognito.create_user_pool_domain(Domain=domain, UserPoolId=pool_id)
    except ClientError as error:
        if not is_error(error, "ResourceNotFoundException"):
            raise
        cognito.create_user_pool_domain(Domain=domain, UserPoolId=pool_id)
    user_pool_client = cognito.describe_user_pool_client(UserPoolId=pool_id, ClientId=client_id)["UserPoolClient"]
    discovery_url = f"https://cognito-idp.{REGION}.amazonaws.com/{pool_id}/.well-known/openid-configuration"
    provider_arn = state.get("credential_provider_arn") or find_provider()
    if not provider_arn:
        response = control.create_oauth2_credential_provider(
            name=PROVIDER_NAME,
            credentialProviderVendor="CustomOauth2",
            oauth2ProviderConfigInput={"customOauth2ProviderConfig": {"oauthDiscovery": {"discoveryUrl": discovery_url}, "clientId": client_id, "clientSecret": user_pool_client["ClientSecret"], "clientSecretSource": "MANAGED"}},
            tags=TAGS,
        )
        provider_arn = response["credentialProviderArn"]
    save_state(
        aws_profile=PROFILE,
        region=REGION,
        cognito_user_pool_id=pool_id,
        cognito_client_id=client_id,
        cognito_domain=domain,
        cognito_discovery_url=discovery_url,
        flights_scope=f"{RESOURCE_SERVER_ID}/flights.read",
        hotels_scope=f"{RESOURCE_SERVER_ID}/hotels.read",
        credential_provider_arn=provider_arn,
    )
    print(f"Cognito pool: {pool_id}")
    print(f"AgentCore Identity OAuth provider: {provider_arn}")


if __name__ == "__main__":
    main()
