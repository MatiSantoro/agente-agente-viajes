"""Provision and publish the protected S3/CloudFront travel-agent frontend."""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

from botocore.exceptions import ClientError

from common import REGION, TAGS, account_id, client, ensure_role, is_error, load_state, save_state

ROOT = Path(__file__).resolve().parent.parent
UI_DIR = ROOT / "UI"
LAMBDA_SOURCE = ROOT / "lambda" / "ui_chat_handler.py"
APP_CLIENT_NAME = "agente-agente-viajes-ui"
API_NAME = "agente-agente-viajes-ui"
FUNCTION_NAME = "agente-agente-viajes-ui-chat"


def find_client(pool_id: str) -> str | None:
    for item in client("cognito-idp").list_user_pool_clients(UserPoolId=pool_id, MaxResults=60).get("UserPoolClients", []):
        if item["ClientName"] == APP_CLIENT_NAME:
            return item["ClientId"]
    return None


def ensure_distribution(bucket: str) -> tuple[str, str]:
    cloudfront = client("cloudfront")
    for item in cloudfront.list_distributions().get("DistributionList", {}).get("Items", []):
        if item.get("Comment") == API_NAME:
            return item["Id"], item["DomainName"]
    response = cloudfront.create_distribution(
        DistributionConfig={
            "CallerReference": f"{API_NAME}-{int(time.time())}",
            "Comment": API_NAME,
            "Enabled": True,
            "DefaultRootObject": "index.html",
            "Origins": {"Quantity": 1, "Items": [{"Id": "ui-s3", "DomainName": f"{bucket}.s3.{REGION}.amazonaws.com", "S3OriginConfig": {"OriginAccessIdentity": ""}}]},
            "DefaultCacheBehavior": {"TargetOriginId": "ui-s3", "ViewerProtocolPolicy": "redirect-to-https", "TrustedSigners": {"Enabled": False, "Quantity": 0}, "TrustedKeyGroups": {"Enabled": False, "Quantity": 0}, "ForwardedValues": {"QueryString": False, "Cookies": {"Forward": "none"}}, "MinTTL": 0},
            "CustomErrorResponses": {"Quantity": 2, "Items": [{"ErrorCode": 403, "ResponsePagePath": "/index.html", "ResponseCode": "200", "ErrorCachingMinTTL": 0}, {"ErrorCode": 404, "ResponsePagePath": "/index.html", "ResponseCode": "200", "ErrorCachingMinTTL": 0}]},
            "ViewerCertificate": {"CloudFrontDefaultCertificate": True},
            "PriceClass": "PriceClass_100",
            "HttpVersion": "http2and3",
            "IsIPV6Enabled": True,
        }
    )["Distribution"]
    return response["Id"], response["DomainName"]


def ensure_spa_client(pool_id: str, callback_url: str, scopes: list[str]) -> str:
    cognito = client("cognito-idp")
    client_id = find_client(pool_id)
    kwargs = {"UserPoolId": pool_id, "ClientName": APP_CLIENT_NAME, "AllowedOAuthFlowsUserPoolClient": True, "AllowedOAuthFlows": ["code"], "AllowedOAuthScopes": ["openid", "profile", "email", *scopes], "CallbackURLs": [callback_url], "LogoutURLs": [callback_url], "SupportedIdentityProviders": ["COGNITO"], "ExplicitAuthFlows": ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_PASSWORD_AUTH"]}
    if client_id:
        cognito.update_user_pool_client(ClientId=client_id, **kwargs)
        return client_id
    return cognito.create_user_pool_client(GenerateSecret=False, **kwargs)["UserPoolClient"]["ClientId"]


def ensure_demo_user(pool_id: str, username: str, password: str) -> None:
    cognito = client("cognito-idp")
    try:
        cognito.admin_get_user(UserPoolId=pool_id, Username=username)
    except ClientError as error:
        if not is_error(error, "UserNotFoundException"):
            raise
        cognito.admin_create_user(UserPoolId=pool_id, Username=username, MessageAction="SUPPRESS")
    cognito.admin_set_user_password(UserPoolId=pool_id, Username=username, Password=password, Permanent=True)


def ensure_bucket(bucket: str) -> None:
    s3 = client("s3")
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError:
        s3.create_bucket(Bucket=bucket)
    s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={"BlockPublicAcls": False, "IgnorePublicAcls": False, "BlockPublicPolicy": False, "RestrictPublicBuckets": False})
    s3.put_bucket_website(Bucket=bucket, WebsiteConfiguration={"IndexDocument": {"Suffix": "index.html"}, "ErrorDocument": {"Key": "index.html"}})
    s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps({"Version": "2012-10-17", "Statement": [{"Sid": "PublicReadForStaticWebsite", "Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{bucket}/*"}]}))


def package_lambda() -> Path:
    build = Path(__file__).resolve().parent / ".build"
    build.mkdir(exist_ok=True)
    archive = build / "ui_chat.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(LAMBDA_SOURCE, "ui_chat_handler.py")
    return archive


def wait_for_lambda(function_name: str) -> dict:
    lambda_client = client("lambda")
    for _ in range(36):
        configuration = lambda_client.get_function(FunctionName=function_name)["Configuration"]
        if configuration.get("State") == "Active" and configuration.get("LastUpdateStatus") in {"Successful", None}:
            return configuration
        if configuration.get("State") == "Failed" or configuration.get("LastUpdateStatus") == "Failed":
            raise RuntimeError(f"Lambda deployment failed: {configuration.get('StateReason') or configuration.get('LastUpdateStatusReason')}")
        time.sleep(5)
    raise TimeoutError(f"Lambda {function_name} did not become ready")


def ensure_chat_lambda(harness_arn: str) -> str:
    role_arn = ensure_role(FUNCTION_NAME + "-role", {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}, "WriteLogs", {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], "Resource": "*"}]})
    archive = package_lambda().read_bytes()
    lambda_client = client("lambda")
    environment = {"Variables": {"HARNESS_ARN": harness_arn}}
    try:
        function = wait_for_lambda(FUNCTION_NAME)
        lambda_client.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=archive)
        wait_for_lambda(FUNCTION_NAME)
        lambda_client.update_function_configuration(FunctionName=FUNCTION_NAME, Environment=environment, Timeout=300)
    except ClientError as error:
        if not is_error(error, "ResourceNotFoundException"):
            raise
        function = lambda_client.create_function(FunctionName=FUNCTION_NAME, Runtime="python3.13", Role=role_arn, Handler="ui_chat_handler.lambda_handler", Code={"ZipFile": archive}, Timeout=300, Environment=environment, Tags=TAGS)
    function = wait_for_lambda(FUNCTION_NAME)
    return function["FunctionArn"]


def ensure_chat_api(pool_id: str, scope: str, function_arn: str) -> str:
    api = client("apigateway")
    rest_apis = api.get_rest_apis(limit=500).get("items", [])
    current = next((item for item in rest_apis if item["name"] == API_NAME), None)
    if not current:
        current = api.create_rest_api(name=API_NAME, endpointConfiguration={"types": ["REGIONAL"]}, tags=TAGS)
    api_id = current["id"]
    resources = api.get_resources(restApiId=api_id, limit=100).get("items", [])
    root = next(item for item in resources if item["path"] == "/")
    chat = next((item for item in resources if item["path"] == "/chat"), None) or api.create_resource(restApiId=api_id, parentId=root["id"], pathPart="chat")
    authorizers = api.get_authorizers(restApiId=api_id, limit=100).get("items", [])
    authorizer = next((item for item in authorizers if item["name"] == "cognito-users"), None)
    if not authorizer:
        authorizer = api.create_authorizer(restApiId=api_id, name="cognito-users", type="COGNITO_USER_POOLS", providerARNs=[f"arn:aws:cognito-idp:{REGION}:{account_id()}:userpool/{pool_id}"], identitySource="method.request.header.Authorization")
    try:
        api.put_method(restApiId=api_id, resourceId=chat["id"], httpMethod="POST", authorizationType="COGNITO_USER_POOLS", authorizerId=authorizer["id"], authorizationScopes=[scope])
    except ClientError as error:
        if not is_error(error, "ConflictException"):
            raise
    api.put_integration(restApiId=api_id, resourceId=chat["id"], httpMethod="POST", type="AWS_PROXY", integrationHttpMethod="POST", uri=f"arn:aws:apigateway:{REGION}:lambda:path/2015-03-31/functions/{function_arn}/invocations")
    try:
        api.put_method(restApiId=api_id, resourceId=chat["id"], httpMethod="OPTIONS", authorizationType="NONE")
    except ClientError as error:
        if not is_error(error, "ConflictException"):
            raise
    api.put_integration(restApiId=api_id, resourceId=chat["id"], httpMethod="OPTIONS", type="MOCK", requestTemplates={"application/json": '{"statusCode": 200}'})
    api.put_method_response(restApiId=api_id, resourceId=chat["id"], httpMethod="OPTIONS", statusCode="200", responseParameters={"method.response.header.Access-Control-Allow-Headers": False, "method.response.header.Access-Control-Allow-Methods": False, "method.response.header.Access-Control-Allow-Origin": False})
    api.put_integration_response(restApiId=api_id, resourceId=chat["id"], httpMethod="OPTIONS", statusCode="200", responseParameters={"method.response.header.Access-Control-Allow-Headers": "'Authorization,Content-Type'", "method.response.header.Access-Control-Allow-Methods": "'POST,OPTIONS'", "method.response.header.Access-Control-Allow-Origin": "'*'"})
    try:
        client("lambda").add_permission(FunctionName=FUNCTION_NAME, StatementId=f"apigateway-{api_id}", Action="lambda:InvokeFunction", Principal="apigateway.amazonaws.com", SourceArn=f"arn:aws:execute-api:{REGION}:{account_id()}:{api_id}/*/POST/chat")
    except ClientError as error:
        if not is_error(error, "ResourceConflictException"):
            raise
    api.create_deployment(restApiId=api_id, stageName="prod", description="Publish protected travel-agent chat API")
    return f"https://{api_id}.execute-api.{REGION}.amazonaws.com/prod/chat"


def upload_ui(bucket: str, config: dict) -> None:
    s3 = client("s3")
    for path in UI_DIR.iterdir():
        if not path.is_file() or path.name.endswith(".example") or path.name == "README.md":
            continue
        body = path.read_bytes()
        content_type = "text/html" if path.suffix == ".html" else "text/css" if path.suffix == ".css" else "application/javascript"
        s3.put_object(Bucket=bucket, Key=path.name, Body=body, ContentType=content_type, CacheControl="no-cache")
    s3.put_object(Bucket=bucket, Key="config.js", Body=f"window.TRAVEL_UI_CONFIG = {json.dumps(config)};\n".encode(), ContentType="application/javascript", CacheControl="no-cache")


def main() -> None:
    state = load_state()
    required = ["cognito_user_pool_id", "cognito_domain", "flights_scope", "hotels_scope", "harness_arn", "harness_id", "cognito_client_id"]
    missing = [key for key in required if key not in state]
    if missing:
        raise RuntimeError(f"Run Scripts/01–03 first; missing {missing}")
    account = account_id()
    bucket = state.get("ui_bucket") or f"agente-agente-viajes-ui-{account}"
    ensure_bucket(bucket)
    distribution_id, distribution_domain = ensure_distribution(bucket)
    app_url = f"https://{distribution_domain}/"
    ui_client_id = ensure_spa_client(state["cognito_user_pool_id"], app_url, [state["flights_scope"], state["hotels_scope"]])
    ensure_demo_user(state["cognito_user_pool_id"], "matiassantoro", "MatiDemo!2026")
    ensure_demo_user(state["cognito_user_pool_id"], "MateoF01", "MateoDemo!2026")
    control = client("bedrock-agentcore-control")
    control.update_harness(harnessId=state["harness_id"], authorizerConfiguration={"optionalValue": {"customJWTAuthorizer": {"discoveryUrl": state["cognito_discovery_url"], "allowedClients": [state["cognito_client_id"], ui_client_id], "allowedScopes": [state["flights_scope"], state["hotels_scope"]]}}})
    function_arn = ensure_chat_lambda(state["harness_arn"])
    api_url = ensure_chat_api(state["cognito_user_pool_id"], state["flights_scope"], function_arn)
    upload_ui(bucket, {"region": REGION, "cognitoDomain": state["cognito_domain"], "userPoolClientId": ui_client_id, "apiUrl": api_url, "scopes": ["openid", "profile", "email", state["flights_scope"], state["hotels_scope"]]})
    client("cloudfront").create_invalidation(DistributionId=distribution_id, InvalidationBatch={"Paths": {"Quantity": 1, "Items": ["/*"]}, "CallerReference": str(time.time())})
    save_state(ui_bucket=bucket, ui_distribution_id=distribution_id, ui_url=app_url, ui_cognito_client_id=ui_client_id, ui_api_url=api_url, ui_lambda_arn=function_arn)
    print(f"UI URL: {app_url}")
    print("Demo users: matiassantoro / MatiDemo!2026; MateoF01 / MateoDemo!2026")


if __name__ == "__main__":
    main()
