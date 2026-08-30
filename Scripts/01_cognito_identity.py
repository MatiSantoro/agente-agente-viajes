"""Create Cognito scopes and an AgentCore Identity OAuth credential provider."""

from __future__ import annotations

from common import AwsCliError, PROFILE, REGION, TAGS, account_id, aws_cli, load_state, save_state

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
    for pool in aws_cli(["cognito-idp", "list-user-pools", "--max-results", "60"]).get("UserPools", []):
        if pool["Name"] == POOL_NAME:
            return pool["Id"]
    return None


def find_client(pool_id: str) -> str | None:
    for client in aws_cli(["cognito-idp", "list-user-pool-clients", "--user-pool-id", pool_id, "--max-results", "60"]).get("UserPoolClients", []):
        if client["ClientName"] == CLIENT_NAME:
            return client["ClientId"]
    return None


def main() -> None:
    state = load_state()
    pool_id = state.get("cognito_user_pool_id") or find_user_pool()
    if not pool_id:
        pool_id = aws_cli(["cognito-idp", "create-user-pool"], {"PoolName": POOL_NAME, "UserPoolTags": TAGS})["UserPool"]["Id"]

    servers = aws_cli(["cognito-idp", "list-resource-servers", "--user-pool-id", pool_id, "--max-results", "60"]).get("ResourceServers", [])
    if not any(server["Identifier"] == RESOURCE_SERVER_ID for server in servers):
        aws_cli(["cognito-idp", "create-resource-server"], {"UserPoolId": pool_id, "Identifier": RESOURCE_SERVER_ID, "Name": RESOURCE_SERVER_NAME, "Scopes": SCOPES})

    client_id = state.get("cognito_client_id") or find_client(pool_id)
    if not client_id:
        response = aws_cli(
            ["cognito-idp", "create-user-pool-client"],
            {
                "UserPoolId": pool_id,
                "ClientName": CLIENT_NAME,
                "GenerateSecret": True,
                "AllowedOAuthFlowsUserPoolClient": True,
                "AllowedOAuthFlows": ["client_credentials"],
                "AllowedOAuthScopes": [f"{RESOURCE_SERVER_ID}/flights.read", f"{RESOURCE_SERVER_ID}/hotels.read"],
                "SupportedIdentityProviders": ["COGNITO"],
            },
        )
        client_id = response["UserPoolClient"]["ClientId"]

    domain = f"agente-agente-viajes-{account_id()}"
    try:
        aws_cli(["cognito-idp", "describe-user-pool-domain", "--domain", domain])
    except AwsCliError as error:
        if "ResourceNotFoundException" not in str(error):
            raise
        aws_cli(["cognito-idp", "create-user-pool-domain"], {"Domain": domain, "UserPoolId": pool_id})

    client = aws_cli(["cognito-idp", "describe-user-pool-client", "--user-pool-id", pool_id, "--client-id", client_id])["UserPoolClient"]
    discovery_url = f"https://cognito-idp.{REGION}.amazonaws.com/{pool_id}/.well-known/openid-configuration"

    provider_arn = state.get("credential_provider_arn")
    if not provider_arn:
        response = aws_cli(
            ["bedrock-agentcore-control", "create-oauth2-credential-provider"],
            {
                "name": PROVIDER_NAME,
                "credentialProviderVendor": "CustomOauth2",
                "oauth2ProviderConfigInput": {"customOauth2ProviderConfig": {"oauthDiscovery": {"discoveryUrl": discovery_url}, "clientId": client_id, "clientSecret": client["ClientSecret"], "clientSecretSource": "MANAGED"}},
                "tags": TAGS,
            },
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
    print("The M2M client secret is intentionally not written to Scripts/.state.json.")


if __name__ == "__main__":
    main()
