"""Provision a location-resolution API and attach it to the travel MCP Gateway."""

from __future__ import annotations

import time
import zipfile
from pathlib import Path

from botocore.exceptions import ClientError

from common import REGION, TAGS, account_id, client, ensure_role, is_error, load_state, save_state, session, wait_for

ROOT = Path(__file__).resolve().parent.parent
TABLE_NAME = "agente-agente-viajes-locations"
FUNCTION_NAME = "agente-agente-viajes-locations"
API_NAME = "agente-agente-viajes-locations"
TARGET_NAME = "locations-target"

LOCATIONS = [
    {"searchKey": "buenos aires", "locationCode": "BUE", "type": "city", "name": "Buenos Aires", "country": "AR", "airports": [{"code": "EZE", "name": "Ministro Pistarini", "searchable": True}, {"code": "AEP", "name": "Aeroparque Jorge Newbery", "searchable": True}]},
    {"searchKey": "mendoza", "locationCode": "MDZ", "type": "city", "name": "Mendoza", "country": "AR", "airports": [{"code": "MDZ", "name": "El Plumerillo", "searchable": True}]},
]


def ensure_table() -> None:
    dynamodb = client("dynamodb")
    try:
        dynamodb.describe_table(TableName=TABLE_NAME)
    except ClientError as error:
        if not is_error(error, "ResourceNotFoundException"):
            raise
        dynamodb.create_table(TableName=TABLE_NAME, BillingMode="PAY_PER_REQUEST", AttributeDefinitions=[{"AttributeName": "searchKey", "AttributeType": "S"}, {"AttributeName": "locationCode", "AttributeType": "S"}], KeySchema=[{"AttributeName": "searchKey", "KeyType": "HASH"}, {"AttributeName": "locationCode", "KeyType": "RANGE"}], Tags=[{"Key": key, "Value": value} for key, value in TAGS.items()])
        dynamodb.get_waiter("table_exists").wait(TableName=TABLE_NAME)
    table = session().resource("dynamodb").Table(TABLE_NAME)
    for location in LOCATIONS:
        table.put_item(Item=location)


def ensure_lambda() -> str:
    role_arn = ensure_role(FUNCTION_NAME + "-role", {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}, "ReadLocations", {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], "Resource": "*"}, {"Effect": "Allow", "Action": "dynamodb:Query", "Resource": f"arn:aws:dynamodb:{REGION}:{account_id()}:table/{TABLE_NAME}"}]})
    archive = Path(__file__).resolve().parent / ".build" / "locations.zip"
    archive.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(ROOT / "lambda" / "locations_handler.py", "locations_handler.py")
    lambda_client = client("lambda")
    try:
        lambda_client.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=archive.read_bytes())
        for _ in range(36):
            if lambda_client.get_function(FunctionName=FUNCTION_NAME)["Configuration"].get("LastUpdateStatus") in {"Successful", None}:
                break
            time.sleep(5)
        lambda_client.update_function_configuration(FunctionName=FUNCTION_NAME, Environment={"Variables": {"TABLE_NAME": TABLE_NAME}})
    except ClientError as error:
        if not is_error(error, "ResourceNotFoundException"):
            raise
        for attempt in range(6):
            try:
                lambda_client.create_function(FunctionName=FUNCTION_NAME, Runtime="python3.13", Role=role_arn, Handler="locations_handler.lambda_handler", Code={"ZipFile": archive.read_bytes()}, Environment={"Variables": {"TABLE_NAME": TABLE_NAME}}, Tags=TAGS)
                break
            except ClientError as create_error:
                if not is_error(create_error, "InvalidParameterValueException") or attempt == 5:
                    raise
                time.sleep(10)
    for _ in range(36):
        configuration = lambda_client.get_function(FunctionName=FUNCTION_NAME)["Configuration"]
        if configuration.get("LastUpdateStatus") in {"Successful", None} and configuration.get("State") == "Active":
            return configuration["FunctionArn"]
        time.sleep(5)
    raise TimeoutError("Locations Lambda did not become ready")


def ensure_api(function_arn: str) -> str:
    api = client("apigateway")
    current = next((item for item in api.get_rest_apis(limit=500)["items"] if item["name"] == API_NAME), None) or api.create_rest_api(name=API_NAME, endpointConfiguration={"types": ["REGIONAL"]}, tags=TAGS)
    resources = api.get_resources(restApiId=current["id"], limit=100)["items"]
    root = next(item for item in resources if item["path"] == "/")
    locations = next((item for item in resources if item["path"] == "/locations"), None) or api.create_resource(restApiId=current["id"], parentId=root["id"], pathPart="locations")
    try:
        api.put_method(restApiId=current["id"], resourceId=locations["id"], httpMethod="GET", authorizationType="NONE", requestParameters={"method.request.querystring.query": True})
    except ClientError as error:
        if not is_error(error, "ConflictException"):
            raise
    api.put_integration(restApiId=current["id"], resourceId=locations["id"], httpMethod="GET", type="AWS_PROXY", integrationHttpMethod="POST", uri=f"arn:aws:apigateway:{REGION}:lambda:path/2015-03-31/functions/{function_arn}/invocations")
    for code in ("200", "400"):
        try:
            api.put_method_response(restApiId=current["id"], resourceId=locations["id"], httpMethod="GET", statusCode=code)
        except ClientError as error:
            if not is_error(error, "ConflictException"):
                raise
    try:
        client("lambda").add_permission(FunctionName=FUNCTION_NAME, StatementId=f"apigateway-{current['id']}", Action="lambda:InvokeFunction", Principal="apigateway.amazonaws.com", SourceArn=f"arn:aws:execute-api:{REGION}:{account_id()}:{current['id']}/*/GET/locations")
    except ClientError as error:
        if not is_error(error, "ResourceConflictException"):
            raise
    api.create_deployment(restApiId=current["id"], stageName="prod", description="Publish location resolution API")
    return current["id"]


def ensure_target(api_id: str) -> None:
    state = load_state()
    control = client("bedrock-agentcore-control")
    configuration = {"mcp": {"apiGateway": {"restApiId": api_id, "stage": "prod", "apiGatewayToolConfiguration": {"toolOverrides": [{"name": "resolve_travel_location", "description": "Resolve a city or airport name to only connected travel location codes and airports.", "path": "/locations", "method": "GET"}], "toolFilters": [{"filterPath": "/locations", "methods": ["GET"]}]}}}}
    current = next((item for item in control.list_gateway_targets(gatewayIdentifier=state["gateway_id"])["items"] if item["name"] == TARGET_NAME), None)
    if current:
        control.update_gateway_target(gatewayIdentifier=state["gateway_id"], targetId=current["targetId"], name=TARGET_NAME, description="Location resolver for travel planning", targetConfiguration=configuration)
        target_id = current["targetId"]
    else:
        target_id = control.create_gateway_target(gatewayIdentifier=state["gateway_id"], name=TARGET_NAME, description="Location resolver for travel planning", targetConfiguration=configuration, credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}])["targetId"]
    wait_for(lambda identifier: control.get_gateway_target(gatewayIdentifier=state["gateway_id"], targetId=identifier), target_id)
    control.synchronize_gateway_targets(gatewayIdentifier=state["gateway_id"], targetIdList=[target_id])
    wait_for(lambda identifier: control.get_gateway_target(gatewayIdentifier=state["gateway_id"], targetId=identifier), target_id)
    save_state(locations_table_name=TABLE_NAME, locations_api_id=api_id, locations_target_id=target_id)


def main() -> None:
    ensure_table()
    function_arn = ensure_lambda()
    api_id = ensure_api(function_arn)
    ensure_target(api_id)
    print(f"Locations API: https://{api_id}.execute-api.{REGION}.amazonaws.com/prod/locations")


if __name__ == "__main__":
    main()
