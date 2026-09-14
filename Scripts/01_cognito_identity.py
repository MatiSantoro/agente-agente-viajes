"""Ensure the Cognito pool used by the signed-in demo UI and Gateway inbound auth."""

from __future__ import annotations

from botocore.exceptions import ClientError

from common import PROFILE, REGION, TAGS, account_id, client, is_error, load_state, save_state

POOL_NAME = "agente-agente-viajes"
DOMAIN_PREFIX = "agente-agente-viajes"


def find_pool(cognito) -> str | None:
    token = None
    while True:
        args = {"MaxResults": 60}
        if token:
            args["NextToken"] = token
        page = cognito.list_user_pools(**args)
        for pool in page.get("UserPools", []):
            if pool["Name"] == POOL_NAME:
                return pool["Id"]
        token = page.get("NextToken")
        if not token:
            return None


def ensure_domain(cognito, pool_id: str, domain: str) -> None:
    try:
        existing = cognito.describe_user_pool_domain(Domain=domain).get("DomainDescription", {})
        if existing.get("UserPoolId") == pool_id:
            return
        if existing.get("UserPoolId"):
            raise RuntimeError(f"Cognito domain {domain} is assigned to a different User Pool")
    except ClientError as error:
        if not is_error(error, "ResourceNotFoundException"):
            raise
    cognito.create_user_pool_domain(Domain=domain, UserPoolId=pool_id)


def main() -> None:
    cognito = client("cognito-idp")
    pool_id = load_state().get("cognito_user_pool_id") or find_pool(cognito)
    if not pool_id:
        pool_id = cognito.create_user_pool(
            PoolName=POOL_NAME,
            MfaConfiguration="OFF",
            UserPoolTags=TAGS,
        )["UserPool"]["Id"]

    pool = cognito.describe_user_pool(UserPoolId=pool_id)["UserPool"]
    if pool["Name"] != POOL_NAME:
        raise RuntimeError(f"Refusing to use unexpected Cognito User Pool {pool_id}: {pool['Name']}")

    domain = f"{DOMAIN_PREFIX}-{account_id()}"
    ensure_domain(cognito, pool_id, domain)
    discovery_url = f"https://cognito-idp.{REGION}.amazonaws.com/{pool_id}/.well-known/openid-configuration"
    save_state(
        aws_profile=PROFILE,
        region=REGION,
        cognito_user_pool_id=pool_id,
        cognito_pool_name=POOL_NAME,
        cognito_domain=domain,
        cognito_discovery_url=discovery_url,
    )
    print(f"UI / platform User Pool: {pool_id}")
    print(f"OIDC discovery URL: {discovery_url}")
    print("External provider APIs use their separate User Pool provisioned by 11_external_provider_oauth.py.")


if __name__ == "__main__":
    main()
