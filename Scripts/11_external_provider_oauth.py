"""Provision the external OAuth provider simulated by Cognito for REST API targets.

Flights, Locations and Hotels belong to one external provider security domain. Hotels
is prepared here but its AgentCore Gateway target is intentionally created separately
in the live-demo step.
"""

from __future__ import annotations

from botocore.exceptions import ClientError

from common import PROFILE, REGION, TAGS, account_id, client, is_error, load_state, save_state

POOL_NAME = "agente-agente-viajes-external-travel-provider"
RESOURCE_SERVER_ID = "travel-provider-api"
RESOURCE_SERVER_NAME = "External Travel Provider API"
DOMAIN_PREFIX = "agente-agente-viajes-external-provider"
APIS = {
    "flights": {
        "scope": "flights.read",
        "description": "Read flight inventory from the external travel provider",
        "client_name": "external-travel-flights-m2m",
        "provider_name": "external_travel_flights_oauth",
    },
    "locations": {
        "scope": "locations.read",
        "description": "Resolve travel locations from the external travel provider",
        "client_name": "external-travel-locations-m2m",
        "provider_name": "external_travel_locations_oauth",
    },
    "hotels": {
        "scope": "hotels.read",
        "description": "Read hotel inventory from the external travel provider",
        "client_name": "external-travel-hotels-m2m",
        "provider_name": "external_travel_hotels_oauth",
    },
}


def find_pool() -> str | None:
    for pool in client("cognito-idp").list_user_pools(MaxResults=50).get("UserPools", []):
        if pool["Name"] == POOL_NAME:
            return pool["Id"]
    return None


def find_client(pool_id: str, name: str) -> str | None:
    for item in client("cognito-idp").list_user_pool_clients(UserPoolId=pool_id, MaxResults=50).get("UserPoolClients", []):
        if item["ClientName"] == name:
            return item["ClientId"]
    return None


def find_provider(name: str) -> str | None:
    control = client("bedrock-agentcore-control")
    next_token = None
    while True:
        arguments = {"maxResults": 20}
        if next_token:
            arguments["nextToken"] = next_token
        response = control.list_oauth2_credential_providers(**arguments)
        for item in response.get("credentialProviders", []):
            if item["name"] == name:
                return item["credentialProviderArn"]
        next_token = response.get("nextToken")
        if not next_token:
            break
    return None


def ensure_domain(cognito, pool_id: str, domain: str) -> None:
    try:
        description = cognito.describe_user_pool_domain(Domain=domain).get("DomainDescription", {})
        if description.get("UserPoolId") == pool_id:
            return
        if description.get("UserPoolId"):
            raise RuntimeError(f"Cognito domain {domain} is already assigned to another user pool")
    except ClientError as error:
        if not is_error(error, "ResourceNotFoundException"):
            raise
    cognito.create_user_pool_domain(Domain=domain, UserPoolId=pool_id)


def main() -> None:
    cognito = client("cognito-idp")
    control = client("bedrock-agentcore-control")
    state = load_state()
    pool_id = state.get("external_provider_user_pool_id") or find_pool()
    if not pool_id:
        pool_id = cognito.create_user_pool(
            PoolName=POOL_NAME,
            MfaConfiguration="OFF",
            UserPoolTags=TAGS,
        )["UserPool"]["Id"]

    desired_scopes = [
        {"ScopeName": api["scope"], "ScopeDescription": api["description"]}
        for api in APIS.values()
    ]
    servers = cognito.list_resource_servers(UserPoolId=pool_id, MaxResults=50).get("ResourceServers", [])
    existing = next((server for server in servers if server["Identifier"] == RESOURCE_SERVER_ID), None)
    if existing:
        cognito.update_resource_server(
            UserPoolId=pool_id,
            Identifier=RESOURCE_SERVER_ID,
            Name=RESOURCE_SERVER_NAME,
            Scopes=desired_scopes,
        )
    else:
        cognito.create_resource_server(
            UserPoolId=pool_id,
            Identifier=RESOURCE_SERVER_ID,
            Name=RESOURCE_SERVER_NAME,
            Scopes=desired_scopes,
        )

    domain = f"{DOMAIN_PREFIX}-{account_id()}"
    ensure_domain(cognito, pool_id, domain)
    discovery_url = f"https://cognito-idp.{REGION}.amazonaws.com/{pool_id}/.well-known/openid-configuration"
    clients: dict[str, str] = {}
    providers: dict[str, str] = {}
    for api_name, api in APIS.items():
        full_scope = f"{RESOURCE_SERVER_ID}/{api['scope']}"
        client_id = find_client(pool_id, api["client_name"])
        if not client_id:
            created = cognito.create_user_pool_client(
                UserPoolId=pool_id,
                ClientName=api["client_name"],
                GenerateSecret=True,
                AllowedOAuthFlowsUserPoolClient=True,
                AllowedOAuthFlows=["client_credentials"],
                AllowedOAuthScopes=[full_scope],
                SupportedIdentityProviders=["COGNITO"],
                PreventUserExistenceErrors="ENABLED",
            )["UserPoolClient"]
            client_id = created["ClientId"]
            client_secret = created["ClientSecret"]
        else:
            described = cognito.describe_user_pool_client(UserPoolId=pool_id, ClientId=client_id)["UserPoolClient"]
            client_secret = described.get("ClientSecret")
            if not client_secret:
                raise RuntimeError(
                    f"Existing client {api['client_name']} has no retrievable secret; create a replacement client before rerunning."
                )

        provider_arn = find_provider(api["provider_name"])
        if not provider_arn:
            provider_arn = control.create_oauth2_credential_provider(
                name=api["provider_name"],
                credentialProviderVendor="CustomOauth2",
                oauth2ProviderConfigInput={
                    "customOauth2ProviderConfig": {
                        "oauthDiscovery": {"discoveryUrl": discovery_url},
                        "clientId": client_id,
                        "clientSecret": client_secret,
                        "clientSecretSource": "MANAGED",
                    }
                },
                tags=TAGS,
            )["credentialProviderArn"]
        clients[api_name] = client_id
        providers[api_name] = provider_arn

    save_state(
        aws_profile=PROFILE,
        external_provider_user_pool_id=pool_id,
        external_provider_domain=domain,
        external_provider_discovery_url=discovery_url,
        external_provider_resource_server_id=RESOURCE_SERVER_ID,
        external_provider_scopes={name: f"{RESOURCE_SERVER_ID}/{api['scope']}" for name, api in APIS.items()},
        external_provider_clients=clients,
        external_provider_oauth_provider_arns=providers,
    )
    print(f"External provider user pool: {pool_id}")
    print(f"Resource server: {RESOURCE_SERVER_ID}")
    for api_name in APIS:
        print(f"{api_name}: client and OAuth provider ready")


if __name__ == "__main__":
    main()
