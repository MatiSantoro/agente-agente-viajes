"""Expose DynamoDB-backed date discovery endpoints through the MCP Gateway."""

from __future__ import annotations

import time
import zipfile
from pathlib import Path

from botocore.exceptions import ClientError

from common import REGION, account_id, client, is_error, load_state, wait_for

ROOT = Path(__file__).resolve().parent.parent
ENDPOINTS = (
    {
        "api_id": "5zoo2ck7cf",
        "parent_path": "/flights",
        "path_part": "availability",
        "function_name": "agente-agente-viajes-flights",
        "source": ROOT / "lambda" / "flights_handler.py",
        "parameters": {"origin": True, "destination": True, "passengers": False},
        "target_name": "flights-target",
        "tool": {"name": "find_available_flight_dates", "description": "Discover only departure dates with connected flight inventory for an origin, destination, and passenger count. Each option includes the lowest price, whether a nonstop option exists, and the maximum seats available.", "path": "/flights/availability", "method": "GET"},
    },
    {
        "api_id": "2ekvs712nj",
        "parent_path": "/hotels",
        "path_part": "availability",
        "function_name": "agente-agente-viajes-hotels",
        "source": ROOT / "lambda" / "hotels_handler.py",
        "parameters": {"destination": True, "guests": False},
        "target_name": "hotels-target",
        "tool": {"name": "find_available_hotel_checkins", "description": "Discover only connected hotel stays for a destination and guest count. Each stay includes exact check-in/check-out, maximum room capacity, nights, rooms remaining, and the lowest nightly price.", "path": "/hotels/availability", "method": "GET"},
    },
)


def update_lambda(function_name: str, source: Path) -> None:
    archive = Path(__file__).resolve().parent / ".build" / f"{function_name}.zip"
    archive.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(source, source.name)
    lambda_client = client("lambda")
    lambda_client.update_function_code(FunctionName=function_name, ZipFile=archive.read_bytes())
    for _ in range(36):
        configuration = lambda_client.get_function(FunctionName=function_name)["Configuration"]
        if configuration.get("LastUpdateStatus") in {"Successful", None}:
            return
        if configuration.get("LastUpdateStatus") == "Failed":
            raise RuntimeError(configuration.get("LastUpdateStatusReason", "Lambda update failed"))
        time.sleep(5)
    raise TimeoutError(f"{function_name} did not become ready")


def ensure_endpoint(config: dict) -> None:
    api = client("apigateway")
    resources = api.get_resources(restApiId=config["api_id"], limit=500)["items"]
    by_path = {item["path"]: item for item in resources}
    path = f"{config['parent_path']}/{config['path_part']}"
    resource = by_path.get(path)
    if not resource:
        resource = api.create_resource(
            restApiId=config["api_id"],
            parentId=by_path[config["parent_path"]]["id"],
            pathPart=config["path_part"],
        )
    request_parameters = {f"method.request.querystring.{name}": required for name, required in config["parameters"].items()}
    try:
        api.put_method(restApiId=config["api_id"], resourceId=resource["id"], httpMethod="GET", authorizationType="NONE", requestParameters=request_parameters)
    except ClientError as error:
        if not is_error(error, "ConflictException"):
            raise
        method = api.get_method(restApiId=config["api_id"], resourceId=resource["id"], httpMethod="GET")
        declared = method.get("requestParameters", {})
        missing = [name for name in config["parameters"] if f"method.request.querystring.{name}" not in declared]
        if missing:
            api.update_method(
                restApiId=config["api_id"],
                resourceId=resource["id"],
                httpMethod="GET",
                patchOperations=[{"op": "add", "path": f"/requestParameters/method.request.querystring.{name}", "value": str(config["parameters"][name]).lower()} for name in missing],
            )
    function_arn = client("lambda").get_function(FunctionName=config["function_name"])["Configuration"]["FunctionArn"]
    api.put_integration(
        restApiId=config["api_id"],
        resourceId=resource["id"],
        httpMethod="GET",
        type="AWS_PROXY",
        integrationHttpMethod="POST",
        uri=f"arn:aws:apigateway:{REGION}:lambda:path/2015-03-31/functions/{function_arn}/invocations",
    )
    for status_code in ("200", "400"):
        try:
            api.put_method_response(restApiId=config["api_id"], resourceId=resource["id"], httpMethod="GET", statusCode=status_code)
        except ClientError as error:
            if not is_error(error, "ConflictException"):
                raise
    try:
        client("lambda").add_permission(
            FunctionName=config["function_name"],
            StatementId=f"availability-{config['api_id']}",
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:{account_id()}:{config['api_id']}/*/GET{path}",
        )
    except ClientError as error:
        if not is_error(error, "ResourceConflictException"):
            raise
    api.create_deployment(restApiId=config["api_id"], stageName="prod", description="Expose date availability for travel planning")


def ensure_optional_query_parameters(api_id: str, path: str, parameters: tuple[str, ...]) -> None:
    api = client("apigateway")
    resources = {item["path"]: item for item in api.get_resources(restApiId=api_id, limit=500)["items"]}
    method = api.get_method(restApiId=api_id, resourceId=resources[path]["id"], httpMethod="GET")
    declared = method.get("requestParameters", {})
    missing = [name for name in parameters if f"method.request.querystring.{name}" not in declared]
    if missing:
        api.update_method(
            restApiId=api_id,
            resourceId=resources[path]["id"],
            httpMethod="GET",
            patchOperations=[{"op": "add", "path": f"/requestParameters/method.request.querystring.{name}", "value": "false"} for name in missing],
        )
        api.create_deployment(restApiId=api_id, stageName="prod", description="Document optional travel search parameters")


def update_gateway_targets() -> None:
    state = load_state()
    control = client("bedrock-agentcore-control")
    base_tools = {
        "flights-target": [
            {"name": "search_flights", "description": "Search flight options by origin, destination and exact date.", "path": "/flights", "method": "GET"},
            {"name": "get_flight", "description": "Get one flight by its ID.", "path": "/flights/{id}", "method": "GET"},
        ],
        "hotels-target": [
            {"name": "search_hotels", "description": "Search hotel options by destination, exact check-in/check-out dates and guests.", "path": "/hotels", "method": "GET"},
            {"name": "get_hotel", "description": "Get one hotel by its ID.", "path": "/hotels/{id}", "method": "GET"},
        ],
    }
    by_target = {item["name"]: item for item in control.list_gateway_targets(gatewayIdentifier=state["gateway_id"])["items"]}
    for endpoint in ENDPOINTS:
        target = by_target[endpoint["target_name"]]
        tools = [*base_tools[endpoint["target_name"]], endpoint["tool"]]
        paths = [tool["path"] for tool in tools]
        control.update_gateway_target(
            gatewayIdentifier=state["gateway_id"],
            targetId=target["targetId"],
            name=endpoint["target_name"],
            description=f"{endpoint['target_name']} for travel planning",
            targetConfiguration={"mcp": {"apiGateway": {"restApiId": endpoint["api_id"], "stage": "prod", "apiGatewayToolConfiguration": {"toolOverrides": tools, "toolFilters": [{"filterPath": path, "methods": ["GET"]} for path in paths]}}}},
        )
        wait_for(lambda identifier: control.get_gateway_target(gatewayIdentifier=state["gateway_id"], targetId=identifier), target["targetId"])
        control.synchronize_gateway_targets(gatewayIdentifier=state["gateway_id"], targetIdList=[target["targetId"]])
        wait_for(lambda identifier: control.get_gateway_target(gatewayIdentifier=state["gateway_id"], targetId=identifier), target["targetId"])


def main() -> None:
    for endpoint in ENDPOINTS:
        update_lambda(endpoint["function_name"], endpoint["source"])
        ensure_endpoint(endpoint)
    ensure_optional_query_parameters("5zoo2ck7cf", "/flights", ("passengers",))
    update_gateway_targets()
    print("Availability tools are published and synchronized.")


if __name__ == "__main__":
    main()
