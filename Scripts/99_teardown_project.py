"""Plan or delete only the verified agente-agente-viajes AWS resources.

This intentionally uses exact account IDs, resource IDs, and names. Dry-run is the
default. It preserves unrelated workloads and shared account infrastructure.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable

from botocore.exceptions import ClientError

from common import PROFILE, REGION, account_id, client

EXPECTED_ACCOUNT = "239248123204"
PROJECT_TAG = "agente-agente-viajes"
CF_COMMENT = "agente-agente-viajes-ui"
GATEWAY_ID = "travel-gateway-mg1vmnirin"
HARNESS_ID = "travel_agent-0wLiXOVd6M"
HARNESS_NAME = "travel_agent"
RUNTIME_ID = "harness_travel_agent-oRKuCZEHro"
RUNTIME_NAME = "harness_travel_agent"
CF_DISTRIBUTION_ID = "E31W0QTTO4X1XC"
UI_BUCKET = "agente-agente-viajes-ui-239248123204"

API_GATEWAYS = {
    "5zoo2ck7cf": "agente-agente-viajes-flights",
    "2ekvs712nj": "agente-agente-viajes-hotels",
    "cgz8nh56v0": "agente-agente-viajes-locations",
    "8fvpmace3g": "agente-agente-viajes-ui",
}
FUNCTIONS = {
    "agente-agente-viajes-flights": "agente-agente-viajes-lambda-flights-role",
    "agente-agente-viajes-hotels": "agente-agente-viajes-lambda-hotels-role",
    "agente-agente-viajes-locations": "agente-agente-viajes-locations-role",
    "agente-agente-viajes-ui-chat": "agente-agente-viajes-ui-chat-role",
}
TABLES = (
    "agente-agente-viajes-flights",
    "agente-agente-viajes-hotels",
    "agente-agente-viajes-locations",
)
USER_POOLS = {
    "us-east-1_ts7h7e63I": "agente-agente-viajes",
    "us-east-1_xwX7tSGtI": "agente-agente-viajes-external-travel-provider",
}
OAUTH_PROVIDERS = (
    "external_travel_flights_oauth",
    "external_travel_hotels_oauth",
    "external_travel_locations_oauth",
    "travel_agent_platform_gateway_oauth",
)
WORKLOAD_IDENTITIES = (GATEWAY_ID, RUNTIME_ID)
LOG_GROUPS = (
    "/aws/lambda/agente-agente-viajes-flights",
    "/aws/lambda/agente-agente-viajes-hotels",
    "/aws/lambda/agente-agente-viajes-locations",
    "/aws/lambda/agente-agente-viajes-ui-chat",
)
IAM_ROLES = (
    "agente-agente-viajes-gateway-role",
    "agente-agente-viajes-harness-role",
    *FUNCTIONS.values(),
)


def missing(error: ClientError) -> bool:
    return error.response.get("Error", {}).get("Code") in {
        "ResourceNotFoundException",
        "ResourceNotFound",
        "NotFoundException",
        "NoSuchEntity",
        "NoSuchBucket",
        "NoSuchDistribution",
        "404",
        "NotFound",
        "InvalidDistribution",
    }


def maybe(call: Callable, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except ClientError as error:
        if missing(error):
            return None
        raise


def retry_throttled(call: Callable, *args, **kwargs):
    throttle_codes = {"TooManyRequestsException", "ThrottlingException", "Throttling", "RequestLimitExceeded", "LimitExceededException"}
    for attempt in range(8):
        try:
            return call(*args, **kwargs)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code not in throttle_codes or attempt == 7:
                raise
            delay = min(5 * (2**attempt), 60)
            print(f"  AWS throttled {call.__name__}; retrying in {delay}s")
            time.sleep(delay)


def verify_project_tag(tags: dict[str, str], what: str) -> None:
    if tags.get("Project") != PROJECT_TAG:
        raise RuntimeError(f"Refusing to delete {what}: Project tag is {tags.get('Project')!r}, expected {PROJECT_TAG!r}")


def cognito_tags(user_pool_arn: str) -> dict[str, str]:
    return client("cognito-idp").list_tags_for_resource(ResourceArn=user_pool_arn).get("Tags", {})


def bucket_region(s3, name: str) -> str:
    location = s3.get_bucket_location(Bucket=name).get("LocationConstraint")
    return location or "us-east-1"


def oauth_providers(control) -> list[dict]:
    items = []
    token = None
    while True:
        args = {"maxResults": 20}
        if token:
            args["nextToken"] = token
        page = control.list_oauth2_credential_providers(**args)
        items.extend(page.get("credentialProviders", []))
        token = page.get("nextToken")
        if not token:
            return items


def validate_plan() -> list[tuple[str, str, bool]]:
    """Read live resource metadata and abort before mutation if any identity mismatches."""
    plan: list[tuple[str, str, bool]] = []
    account = account_id()
    if account != EXPECTED_ACCOUNT:
        raise RuntimeError(f"Profile {PROFILE!r} resolved to account {account}, not the authorized project account {EXPECTED_ACCOUNT}")
    if REGION != "us-east-1":
        raise RuntimeError(f"Unexpected configured region {REGION}")

    control = client("bedrock-agentcore-control")
    gateway = maybe(control.get_gateway, gatewayIdentifier=GATEWAY_ID)
    if gateway:
        if gateway.get("name") != "travel-gateway":
            raise RuntimeError(f"Gateway ID {GATEWAY_ID} now belongs to {gateway.get('name')!r}; stopping")
        if not gateway.get("roleArn", "").endswith(":role/agente-agente-viajes-gateway-role"):
            raise RuntimeError(f"Gateway {GATEWAY_ID} does not use the known project role; stopping")
        plan.append(("AgentCore Gateway", f"{GATEWAY_ID} ({gateway['name']}) and its attached targets", True))
    else:
        plan.append(("AgentCore Gateway", f"{GATEWAY_ID}", False))

    harness_response = maybe(control.get_harness, harnessId=HARNESS_ID)
    harness = harness_response.get("harness") if harness_response else None
    if harness:
        if harness.get("harnessName") != HARNESS_NAME:
            raise RuntimeError(f"Harness ID {HARNESS_ID} now belongs to {harness.get('harnessName')!r}; stopping")
        if not harness.get("executionRoleArn", "").endswith(":role/agente-agente-viajes-harness-role"):
            raise RuntimeError(f"Harness {HARNESS_ID} does not use the known project role; stopping")
        plan.append(("AgentCore Harness and runtime", f"{HARNESS_ID} ({HARNESS_NAME}) / {RUNTIME_ID}", True))
    else:
        plan.append(("AgentCore Harness and runtime", f"{HARNESS_ID} / {RUNTIME_ID}", False))

    for name in OAUTH_PROVIDERS:
        provider = next((item for item in oauth_providers(control) if item.get("name") == name), None)
        plan.append(("AgentCore Identity OAuth provider", name, provider is not None))

    apigw = client("apigateway")
    for api_id, expected_name in API_GATEWAYS.items():
        api = maybe(apigw.get_rest_api, restApiId=api_id)
        if api:
            if api.get("name") != expected_name:
                raise RuntimeError(f"API Gateway ID {api_id} now belongs to {api.get('name')!r}; stopping")
            verify_project_tag(api.get("tags", {}), f"API Gateway {api_id}")
        plan.append(("API Gateway REST API", f"{api_id} ({expected_name})", api is not None))

    lam = client("lambda")
    for function_name, expected_role in FUNCTIONS.items():
        function = maybe(lam.get_function, FunctionName=function_name)
        if function:
            config = function["Configuration"]
            if not config.get("Role", "").endswith(f":role/{expected_role}"):
                raise RuntimeError(f"Lambda {function_name} does not use its known project role; stopping")
            env = config.get("Environment", {}).get("Variables", {})
            linked = any(
                value.startswith("agente-agente-viajes-") or "travel_agent-0wLiXOVd6M" in value
                for value in env.values()
            )
            if not linked:
                raise RuntimeError(f"Lambda {function_name} no longer references a project resource; stopping")
        plan.append(("Lambda function", function_name, function is not None))

    dynamodb = client("dynamodb")
    for table_name in TABLES:
        table = maybe(dynamodb.describe_table, TableName=table_name)
        if table:
            tags = {item["Key"]: item["Value"] for item in dynamodb.list_tags_of_resource(ResourceArn=table["Table"]["TableArn"]).get("Tags", [])}
            verify_project_tag(tags, f"DynamoDB table {table_name}")
        plan.append(("DynamoDB table", table_name, table is not None))

    cognito = client("cognito-idp")
    for pool_id, expected_name in USER_POOLS.items():
        pool_response = maybe(cognito.describe_user_pool, UserPoolId=pool_id)
        pool = pool_response.get("UserPool") if pool_response else None
        if pool:
            if pool.get("Name") != expected_name:
                raise RuntimeError(f"Cognito pool {pool_id} now belongs to {pool.get('Name')!r}; stopping")
            verify_project_tag(cognito_tags(pool["Arn"]), f"Cognito User Pool {pool_id}")
        plan.append(("Cognito User Pool", f"{pool_id} ({expected_name})", pool is not None))

    cloudfront = client("cloudfront")
    distribution = maybe(cloudfront.get_distribution, Id=CF_DISTRIBUTION_ID)
    if distribution:
        detail = distribution["Distribution"]
        config = detail["DistributionConfig"]
        if config.get("Comment") != CF_COMMENT:
            raise RuntimeError(f"CloudFront distribution {CF_DISTRIBUTION_ID} has unexpected comment {config.get('Comment')!r}; stopping")
        origins = [origin.get("DomainName", "") for origin in config.get("Origins", {}).get("Items", [])]
        if not any(UI_BUCKET in origin for origin in origins):
            raise RuntimeError(f"CloudFront distribution {CF_DISTRIBUTION_ID} does not point to the verified project UI bucket; stopping")
    plan.append(("CloudFront distribution", CF_DISTRIBUTION_ID, distribution is not None))

    s3 = client("s3")
    bucket = maybe(s3.head_bucket, Bucket=UI_BUCKET)
    if bucket is not None:
        if bucket_region(s3, UI_BUCKET) != REGION:
            raise RuntimeError(f"UI bucket {UI_BUCKET} is outside {REGION}; stopping")
        website = maybe(s3.get_bucket_website, Bucket=UI_BUCKET)
        if not website:
            raise RuntimeError(f"UI bucket {UI_BUCKET} no longer has the expected static website configuration; stopping")
    plan.append(("UI S3 website bucket", UI_BUCKET, bucket is not None))

    logs = client("logs")
    existing_logs = {item["logGroupName"] for item in logs.describe_log_groups(logGroupNamePrefix="/aws/lambda/agente-agente-viajes").get("logGroups", [])}
    for log_group in LOG_GROUPS:
        plan.append(("CloudWatch log group", log_group, log_group in existing_logs))

    iam = client("iam")
    for role_name in IAM_ROLES:
        role = maybe(iam.get_role, RoleName=role_name)
        if role and role["Role"].get("RoleName") != role_name:
            raise RuntimeError(f"IAM role lookup returned a mismatched name for {role_name}; stopping")
        plan.append(("IAM role", role_name, role is not None))

    return plan


def wait_until(description: str, predicate: Callable[[], bool], attempts: int = 90, delay: int = 10) -> None:
    for _ in range(attempts):
        if predicate():
            return
        time.sleep(delay)
    raise TimeoutError(f"Timed out waiting for {description}")


def delete_cloudfront_and_bucket() -> None:
    cloudfront = client("cloudfront")
    current = maybe(cloudfront.get_distribution, Id=CF_DISTRIBUTION_ID)
    if current:
        detail = current["Distribution"]
        config = detail["DistributionConfig"]
        etag = current["ETag"]
        if config.get("Enabled"):
            config["Enabled"] = False
            cloudfront.update_distribution(Id=CF_DISTRIBUTION_ID, IfMatch=etag, DistributionConfig=config)
            print("  Disabled CloudFront distribution; waiting for global deployment before deletion...")
            cloudfront.get_waiter("distribution_deployed").wait(Id=CF_DISTRIBUTION_ID)
        else:
            cloudfront.get_waiter("distribution_deployed").wait(Id=CF_DISTRIBUTION_ID)
        latest = cloudfront.get_distribution(Id=CF_DISTRIBUTION_ID)
        if latest["Distribution"]["DistributionConfig"].get("Enabled"):
            raise RuntimeError("CloudFront distribution is still enabled; refusing to delete")
        cloudfront.delete_distribution(Id=CF_DISTRIBUTION_ID, IfMatch=latest["ETag"])
        print("  Requested CloudFront distribution deletion; waiting for it to disappear...")
        wait_until(
            f"CloudFront distribution {CF_DISTRIBUTION_ID} deletion",
            lambda: maybe(cloudfront.get_distribution, Id=CF_DISTRIBUTION_ID) is None,
            attempts=180,
            delay=10,
        )

    s3 = client("s3")
    if maybe(s3.head_bucket, Bucket=UI_BUCKET) is None:
        return
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=UI_BUCKET):
        objects = [
            {"Key": item["Key"], "VersionId": item["VersionId"]}
            for item in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]
        ]
        for start in range(0, len(objects), 1000):
            s3.delete_objects(Bucket=UI_BUCKET, Delete={"Objects": objects[start : start + 1000], "Quiet": True})
    for page in s3.get_paginator("list_multipart_uploads").paginate(Bucket=UI_BUCKET):
        for upload in page.get("Uploads", []):
            s3.abort_multipart_upload(Bucket=UI_BUCKET, Key=upload["Key"], UploadId=upload["UploadId"])
    s3.delete_bucket(Bucket=UI_BUCKET)
    print(f"  Deleted S3 website bucket {UI_BUCKET}")


def delete_agentcore_resources() -> None:
    control = client("bedrock-agentcore-control")
    endpoint_token = None
    endpoints = []
    while True:
        args = {"harnessId": HARNESS_ID, "maxResults": 100}
        if endpoint_token:
            args["nextToken"] = endpoint_token
        page = control.list_harness_endpoints(**args)
        endpoints.extend(page.get("endpoints", []))
        endpoint_token = page.get("nextToken")
        if not endpoint_token:
            break
    for endpoint in endpoints:
        name = endpoint.get("name") or endpoint.get("endpointName")
        if not name:
            raise RuntimeError(f"Cannot identify a Harness endpoint for deletion: {endpoint}")
        if name.upper() == "DEFAULT":
            # AWS removes the mandatory DEFAULT endpoint together with its Harness.
            continue
        maybe(control.delete_harness_endpoint, harnessId=HARNESS_ID, endpointName=name)
        wait_until(
            f"Harness endpoint {name} deletion",
            lambda: maybe(control.get_harness_endpoint, harnessId=HARNESS_ID, endpointName=name) is None,
            attempts=60,
            delay=5,
        )

    if maybe(control.get_harness, harnessId=HARNESS_ID):
        control.delete_harness(harnessId=HARNESS_ID, deleteManagedMemory=True)
        wait_until(
            f"Harness {HARNESS_ID} deletion",
            lambda: maybe(control.get_harness, harnessId=HARNESS_ID) is None,
            attempts=90,
            delay=10,
        )

    runtime = maybe(control.get_agent_runtime, agentRuntimeId=RUNTIME_ID)
    if runtime:
        if runtime.get("agentRuntimeName") != RUNTIME_NAME or not runtime.get("roleArn", "").endswith(":role/agente-agente-viajes-harness-role"):
            raise RuntimeError(f"Runtime {RUNTIME_ID} does not match the verified project Harness; refusing to delete")
        control.delete_agent_runtime(agentRuntimeId=RUNTIME_ID)
        wait_until(
            f"AgentCore runtime {RUNTIME_ID} deletion",
            lambda: maybe(control.get_agent_runtime, agentRuntimeId=RUNTIME_ID) is None,
            attempts=120,
            delay=10,
        )

    gateway = maybe(control.get_gateway, gatewayIdentifier=GATEWAY_ID)
    if gateway:
        while True:
            target_page = control.list_gateway_targets(gatewayIdentifier=GATEWAY_ID, maxResults=100)
            targets = target_page.get("items", [])
            if not targets:
                break
            target = targets[0]
            target_id = target["targetId"]
            maybe(control.delete_gateway_target, gatewayIdentifier=GATEWAY_ID, targetId=target_id)
            wait_until(
                f"Gateway target {target_id} deletion",
                lambda: maybe(control.get_gateway_target, gatewayIdentifier=GATEWAY_ID, targetId=target_id) is None,
                attempts=60,
                delay=5,
            )
        maybe(control.delete_gateway, gatewayIdentifier=GATEWAY_ID)
        wait_until(
            f"Gateway {GATEWAY_ID} deletion",
            lambda: maybe(control.get_gateway, gatewayIdentifier=GATEWAY_ID) is None,
            attempts=90,
            delay=10,
        )

    for name in OAUTH_PROVIDERS:
        existing = next((item for item in oauth_providers(control) if item.get("name") == name), None)
        if existing:
            maybe(control.delete_oauth2_credential_provider, name=name)
            wait_until(
                f"OAuth credential provider {name} deletion",
                lambda: not any(item.get("name") == name for item in oauth_providers(control)),
                attempts=30,
                delay=5,
            )

    for name in WORKLOAD_IDENTITIES:
        identity = maybe(control.get_workload_identity, name=name)
        if identity:
            maybe(control.delete_workload_identity, name=name)

    print("  Deleted AgentCore Harness/runtime, Gateway/targets, OAuth providers, and project workload identities")


def delete_remaining_resources() -> None:
    apigw = client("apigateway")
    for api_id, expected_name in API_GATEWAYS.items():
        api = maybe(apigw.get_rest_api, restApiId=api_id)
        if api:
            if api.get("name") != expected_name:
                raise RuntimeError(f"API Gateway {api_id} identity changed during teardown; stopping")
            verify_project_tag(api.get("tags", {}), f"API Gateway {api_id}")
            retry_throttled(apigw.delete_rest_api, restApiId=api_id)
            time.sleep(3)

    lam = client("lambda")
    for name, expected_role in FUNCTIONS.items():
        function = maybe(lam.get_function, FunctionName=name)
        if function:
            if not function["Configuration"].get("Role", "").endswith(f":role/{expected_role}"):
                raise RuntimeError(f"Lambda {name} role changed during teardown; stopping")
            retry_throttled(lam.delete_function, FunctionName=name)

    dynamodb = client("dynamodb")
    for name in TABLES:
        table = maybe(dynamodb.describe_table, TableName=name)
        if table:
            tags = {item["Key"]: item["Value"] for item in dynamodb.list_tags_of_resource(ResourceArn=table["Table"]["TableArn"]).get("Tags", [])}
            verify_project_tag(tags, f"DynamoDB table {name}")
            retry_throttled(dynamodb.delete_table, TableName=name)
            dynamodb.get_waiter("table_not_exists").wait(TableName=name)

    cognito = client("cognito-idp")
    for pool_id, expected_name in USER_POOLS.items():
        response = maybe(cognito.describe_user_pool, UserPoolId=pool_id)
        pool = response.get("UserPool") if response else None
        if pool:
            if pool.get("Name") != expected_name:
                raise RuntimeError(f"Cognito pool {pool_id} identity changed during teardown; stopping")
            verify_project_tag(cognito_tags(pool["Arn"]), f"Cognito User Pool {pool_id}")
            retry_throttled(cognito.delete_user_pool, UserPoolId=pool_id)

    logs = client("logs")
    for name in LOG_GROUPS:
        retry_throttled(logs.delete_log_group, logGroupName=name)

    iam = client("iam")
    for role_name in IAM_ROLES:
        role = maybe(iam.get_role, RoleName=role_name)
        if not role:
            continue
        # Detach project-role references but preserve any unrelated shared profile.
        for page in iam.get_paginator("list_instance_profiles_for_role").paginate(RoleName=role_name):
            for profile in page.get("InstanceProfiles", []):
                retry_throttled(iam.remove_role_from_instance_profile, InstanceProfileName=profile["InstanceProfileName"], RoleName=role_name)
        for page in iam.get_paginator("list_role_policies").paginate(RoleName=role_name):
            for policy_name in page.get("PolicyNames", []):
                retry_throttled(iam.delete_role_policy, RoleName=role_name, PolicyName=policy_name)
        for page in iam.get_paginator("list_attached_role_policies").paginate(RoleName=role_name):
            for policy in page.get("AttachedPolicies", []):
                retry_throttled(iam.detach_role_policy, RoleName=role_name, PolicyArn=policy["PolicyArn"])
        if role["Role"].get("PermissionsBoundary"):
            retry_throttled(iam.delete_role_permissions_boundary, RoleName=role_name)
        retry_throttled(iam.delete_role, RoleName=role_name)

    delete_cloudfront_and_bucket()
    print("  Deleted project API Gateways, Lambdas, DynamoDB tables, Cognito pools, log groups, IAM roles, CloudFront and UI bucket")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="perform the AWS deletions (default is read-only dry-run)")
    args = parser.parse_args()

    print(f"AWS profile: {PROFILE}; account: {account_id()}; region: {REGION}")
    plan = validate_plan()
    print("\nVerified project-scoped deletion plan:")
    for category, name, found in plan:
        print(f"  [{'FOUND' if found else 'absent'}] {category}: {name}")
    print("\nPreserved by design: all non-project resources and shared KMS key alias/aws/dynamodb.")
    if not args.execute:
        print("\nDry-run only. Pass --execute to delete the listed resources.")
        return

    print("\nExecuting project teardown...")
    delete_agentcore_resources()
    delete_remaining_resources()
    print("Teardown completed. Run this script without --execute to verify remaining project resources.")


if __name__ == "__main__":
    main()
