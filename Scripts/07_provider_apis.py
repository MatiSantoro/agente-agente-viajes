"""Create the demo's provider APIs, Lambdas, tables, and deterministic inventory.

This module is deliberately independent of API Gateway IDs. It discovers resources
by their project names, writes their IDs to ``Scripts/.state.json`` and can be run
repeatedly without duplicating inventory. Flights, Hotels, and Locations are
created as three independent REST APIs, matching the "external provider" story
used by the AgentCore demo.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import zipfile
from decimal import Decimal
from pathlib import Path

from botocore.exceptions import ClientError

from common import REGION, TAGS, account_id, client, is_error, save_state, session

ROOT = Path(__file__).resolve().parent.parent
TABLES = {
    "flights": "agente-agente-viajes-flights",
    "hotels": "agente-agente-viajes-hotels",
    "locations": "agente-agente-viajes-locations",
}
FUNCTIONS = {
    "flights": "agente-agente-viajes-flights",
    "hotels": "agente-agente-viajes-hotels",
    "locations": "agente-agente-viajes-locations",
}
ROLE_NAMES = {
    "flights": "agente-agente-viajes-lambda-flights-role",
    "hotels": "agente-agente-viajes-lambda-hotels-role",
    "locations": "agente-agente-viajes-locations-role",
}
API_NAMES = {
    "flights": "agente-agente-viajes-flights",
    "hotels": "agente-agente-viajes-hotels",
    "locations": "agente-agente-viajes-locations",
}
HANDLERS = {
    "flights": ("flights_handler.lambda_handler", ROOT / "lambda" / "flights_handler.py"),
    "hotels": ("hotels_handler.lambda_handler", ROOT / "lambda" / "hotels_handler.py"),
    "locations": ("locations_handler.lambda_handler", ROOT / "lambda" / "locations_handler.py"),
}


def _role(name: str, table_name: str) -> str:
    iam = client("iam")
    trust = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}],
    }
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "WriteFunctionLogs",
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": f"arn:aws:logs:{REGION}:{account_id()}:log-group:/aws/lambda/{name}:*",
            },
            {
                "Sid": "ReadInventory",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"],
                "Resource": f"arn:aws:dynamodb:{REGION}:{account_id()}:table/{table_name}",
            },
        ],
    }
    try:
        arn = iam.get_role(RoleName=name)["Role"]["Arn"]
    except ClientError as error:
        if not is_error(error, "NoSuchEntity"):
            raise
        arn = iam.create_role(
            RoleName=name,
            AssumeRolePolicyDocument=json.dumps(trust),
            Tags=[{"Key": key, "Value": value} for key, value in TAGS.items()],
        )["Role"]["Arn"]
        time.sleep(5)
    iam.put_role_policy(RoleName=name, PolicyName="ReadTravelInventory", PolicyDocument=json.dumps(policy))
    return arn


def _ensure_table(kind: str) -> None:
    dynamodb = client("dynamodb")
    table_name = TABLES[kind]
    definitions = {
        "flights": ([{"AttributeName": "route", "AttributeType": "S"}, {"AttributeName": "departureDateFlightId", "AttributeType": "S"}], [{"AttributeName": "route", "KeyType": "HASH"}, {"AttributeName": "departureDateFlightId", "KeyType": "RANGE"}]),
        "hotels": ([{"AttributeName": "destination", "AttributeType": "S"}, {"AttributeName": "checkInHotelId", "AttributeType": "S"}], [{"AttributeName": "destination", "KeyType": "HASH"}, {"AttributeName": "checkInHotelId", "KeyType": "RANGE"}]),
        "locations": ([{"AttributeName": "searchKey", "AttributeType": "S"}, {"AttributeName": "locationCode", "AttributeType": "S"}], [{"AttributeName": "searchKey", "KeyType": "HASH"}, {"AttributeName": "locationCode", "KeyType": "RANGE"}]),
    }[kind]
    try:
        dynamodb.describe_table(TableName=table_name)
    except ClientError as error:
        if not is_error(error, "ResourceNotFoundException"):
            raise
        dynamodb.create_table(TableName=table_name, BillingMode="PAY_PER_REQUEST", AttributeDefinitions=definitions[0], KeySchema=definitions[1], Tags=[{"Key": key, "Value": value} for key, value in TAGS.items()])
        dynamodb.get_waiter("table_exists").wait(TableName=table_name)


def _dates() -> list[dt.date]:
    start = dt.date.today() + dt.timedelta(days=14)
    # Use daily inventory so exact natural-language windows such as December
    # 10–14 always exist, with options before and after the requested dates.
    dates = {start + dt.timedelta(days=offset) for offset in range(0, 365)}
    # Keep the demo window available even if the project is redeployed late in a
    # year and the rolling window no longer reaches the following December.
    for year in range(dt.date.today().year, dt.date.today().year + 3):
        dates.update(dt.date(year, 12, day) for day in range(8, 18))
    return sorted(dates)


def _flight_items() -> list[dict]:
    routes = [("EZE", "MDZ"), ("AEP", "MDZ"), ("MDZ", "EZE"), ("MDZ", "AEP"), ("EZE", "BRC"), ("AEP", "COR"), ("COR", "AEP"), ("BRC", "EZE")]
    airlines = [("AR", "Aerolíneas Argentinas"), ("JA", "JetSmart"), ("FO", "Flybondi")]
    items: list[dict] = []
    sequence = 1
    for date in _dates():
        for origin, destination in routes:
            for variant, (airline_code, airline_name) in enumerate(airlines[:2]):
                flight_id = f"flight-{sequence:04d}"
                departure = "07:10" if variant == 0 else "18:40"
                arrival = "09:00" if variant == 0 else "20:30"
                price = Decimal(str(68000 + (date.day % 7) * 2300 + variant * 12500 + (0 if origin in {"AEP", "EZE"} else 5000)))
                items.append({
                    "route": f"{origin}#{destination}",
                    "departureDateFlightId": f"{date.isoformat()}#{flight_id}",
                    "flightId": flight_id,
                    "origin": origin,
                    "destination": destination,
                    "departureDate": date.isoformat(),
                    "departureTime": departure,
                    "arrivalTime": arrival,
                    "airline": airline_name,
                    "airlineCode": airline_code,
                    "price": price,
                    "currency": "ARS",
                    "durationMinutes": 110,
                    "stops": 0,
                    "capacity": 186,
                    "availableSeats": 12 + ((sequence + variant * 7) % 85),
                    "passengerLimit": 9,
                    "returnRoute": f"{destination}#{origin}",
                })
                sequence += 1
    return items


def _hotel_items() -> list[dict]:
    destinations = {
        "MDZ": [("hotel-011", "Cuyo Plaza", 3, 71000), ("hotel-012", "Andes Suites", 2, 89000), ("hotel-013", "Parque Mendoza", 4, 112000), ("hotel-014", "Casa del Sol", 5, 138000)],
        "BRC": [("hotel-021", "Lago Nahuel", 3, 98000), ("hotel-022", "Patagonia Lodge", 4, 125000), ("hotel-023", "Centro Bariloche", 2, 86000)],
        "COR": [("hotel-031", "Nueva Cordoba Stay", 3, 65000), ("hotel-032", "Sierras Hotel", 4, 82000), ("hotel-033", "Plaza San Martin", 2, 59000)],
    }
    items: list[dict] = []
    for date in _dates():
        checkout = date + dt.timedelta(days=4)
        for destination, hotels in destinations.items():
            for hotel_id, name, max_guests, base_price in hotels:
                # Each hotel has multiple stays and capacities, including rooms that fit 2 guests.
                for room_index in range(1, 3):
                    capacity = min(6, max_guests + room_index - 1)
                    item_id = f"{hotel_id}-{date.strftime('%m%d')}-{room_index}"
                    items.append({
                        "destination": destination,
                        "checkInHotelId": f"{date.isoformat()}#{item_id}",
                        "hotelId": hotel_id,
                        "name": name,
                        "city": destination,
                        "checkIn": date.isoformat(),
                        "checkOut": checkout.isoformat(),
                        "nights": 4,
                        "maxGuests": capacity,
                        "guests": capacity,
                        "roomsAvailable": 1 + ((date.day + room_index) % 5),
                        "pricePerNight": Decimal(str(base_price + room_index * 6000 + (date.day % 5) * 2500)),
                        "currency": "ARS",
                        "rating": Decimal(str(4.1 + ((date.day + room_index) % 8) / 10)),
                        "amenities": ["wifi", "breakfast", "air-conditioning"],
                    })
    return items


def _location_items() -> list[dict]:
    locations = [
        ("buenos aires", "BUE", "Buenos Aires", "AR", [{"code": "EZE", "name": "Ministro Pistarini", "searchable": True}, {"code": "AEP", "name": "Aeroparque Jorge Newbery", "searchable": True}]),
        ("ezeiza", "EZE", "Ezeiza", "AR", [{"code": "EZE", "name": "Ministro Pistarini", "searchable": True}]),
        ("aeroparque", "AEP", "Aeroparque", "AR", [{"code": "AEP", "name": "Aeroparque Jorge Newbery", "searchable": True}]),
        ("mendoza", "MDZ", "Mendoza", "AR", [{"code": "MDZ", "name": "El Plumerillo", "searchable": True}]),
        ("bariloche", "BRC", "Bariloche", "AR", [{"code": "BRC", "name": "Teniente Luis Candelaria", "searchable": True}]),
        ("cordoba", "COR", "Córdoba", "AR", [{"code": "COR", "name": "Ingeniero Taravella", "searchable": True}]),
    ]
    return [{"searchKey": key, "locationCode": code, "type": "city" if code in {"BUE", "MDZ", "BRC", "COR"} else "airport", "name": name, "country": country, "airports": airports} for key, code, name, country, airports in locations]


def _seed(kind: str) -> int:
    data = {"flights": _flight_items, "hotels": _hotel_items, "locations": _location_items}[kind]()
    table = session().resource("dynamodb").Table(TABLES[kind])
    with table.batch_writer(overwrite_by_pkeys=["route", "departureDateFlightId"] if kind == "flights" else ["destination", "checkInHotelId"] if kind == "hotels" else ["searchKey", "locationCode"]) as batch:
        for item in data:
            batch.put_item(Item=item)
    return len(data)


def _wait_lambda(function_name: str) -> dict:
    lambda_client = client("lambda")
    for _ in range(60):
        config = lambda_client.get_function(FunctionName=function_name)["Configuration"]
        if config.get("State") == "Active" and config.get("LastUpdateStatus") in {None, "Successful"}:
            return config
        if config.get("State") == "Failed" or config.get("LastUpdateStatus") == "Failed":
            raise RuntimeError(config.get("StateReason") or config.get("LastUpdateStatusReason") or f"Lambda {function_name} failed")
        time.sleep(5)
    raise TimeoutError(f"Lambda {function_name} did not become active")


def _ensure_lambda(kind: str, role_arn: str) -> str:
    lambda_client = client("lambda")
    function_name = FUNCTIONS[kind]
    handler, source = HANDLERS[kind]
    archive = ROOT / "Scripts" / ".build" / f"{kind}_provider.zip"
    archive.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(source, source.name)
    code = archive.read_bytes()
    environment = {"Variables": {"TABLE_NAME": TABLES[kind]}}
    try:
        lambda_client.get_function(FunctionName=function_name)
        lambda_client.update_function_code(FunctionName=function_name, ZipFile=code)
        _wait_lambda(function_name)
        lambda_client.update_function_configuration(FunctionName=function_name, Environment=environment, Role=role_arn, Handler=handler, Runtime="python3.13")
    except ClientError as error:
        if not is_error(error, "ResourceNotFoundException"):
            raise
        lambda_client.create_function(FunctionName=function_name, Runtime="python3.13", Role=role_arn, Handler=handler, Code={"ZipFile": code}, Timeout=29, Environment=environment, Tags=TAGS)
    config = _wait_lambda(function_name)
    return config["FunctionArn"]


def _ensure_method(api, api_id: str, resource_id: str, method: str, function_arn: str, parameters: dict[str, bool]) -> None:
    request_parameters = {
        f"method.request.path.{name}" if name == "id" else f"method.request.querystring.{name}": required
        for name, required in parameters.items()
    }
    # API Gateway requires path parameters to be declared on the method even
    # though the Lambda proxy receives them from the request context.
    if "id" in parameters:
        request_parameters["method.request.path.id"] = True
    try:
        api.put_method(restApiId=api_id, resourceId=resource_id, httpMethod=method, authorizationType="NONE", requestParameters=request_parameters)
    except ClientError as error:
        if not is_error(error, "ConflictException"):
            raise
    api.put_integration(restApiId=api_id, resourceId=resource_id, httpMethod=method, type="AWS_PROXY", integrationHttpMethod="POST", uri=f"arn:aws:apigateway:{REGION}:lambda:path/2015-03-31/functions/{function_arn}/invocations")
    for status in ("200", "400", "404"):
        try:
            api.put_method_response(restApiId=api_id, resourceId=resource_id, httpMethod=method, statusCode=status)
        except ClientError as error:
            if not is_error(error, "ConflictException"):
                raise


def _ensure_options(api, api_id: str, resource_id: str) -> None:
    try:
        api.put_method(restApiId=api_id, resourceId=resource_id, httpMethod="OPTIONS", authorizationType="NONE")
    except ClientError as error:
        if not is_error(error, "ConflictException"):
            raise
    api.put_integration(restApiId=api_id, resourceId=resource_id, httpMethod="OPTIONS", type="MOCK", requestTemplates={"application/json": '{"statusCode": 204}'})


def _ensure_api(kind: str, function_arn: str) -> str:
    api = client("apigateway")
    current = next((item for item in api.get_rest_apis(limit=500).get("items", []) if item["name"] == API_NAMES[kind]), None)
    if not current:
        current = api.create_rest_api(name=API_NAMES[kind], endpointConfiguration={"types": ["REGIONAL"]}, tags=TAGS)
    api_id = current["id"]
    resources = api.get_resources(restApiId=api_id, limit=500)["items"]
    root = next(item for item in resources if item["path"] == "/")
    definitions = {
        "flights": [("/flights", {"origin": True, "destination": True, "date": True, "passengers": False}), ("/flights/{id}", {"id": True}), ("/flights/availability", {"origin": True, "destination": True, "passengers": False})],
        "hotels": [("/hotels", {"destination": True, "checkIn": True, "checkOut": True, "guests": True}), ("/hotels/{id}", {"id": True}), ("/hotels/availability", {"destination": True, "guests": False})],
        "locations": [("/locations", {"query": True})],
    }[kind]
    by_path = {item["path"]: item for item in resources}
    for path, parameters in definitions:
        parent = root
        parts = [part for part in path.split("/") if part]
        built = ""
        for part in parts:
            built += "/" + part
            if built not in by_path:
                resource = api.create_resource(restApiId=api_id, parentId=parent["id"], pathPart=part)
                by_path[built] = resource
            parent = by_path[built]
        _ensure_method(api, api_id, parent["id"], "GET", function_arn, parameters)
        _ensure_options(api, api_id, parent["id"])
        try:
            client("lambda").add_permission(FunctionName=FUNCTIONS[kind], StatementId=f"apigateway-{api_id}-{parent['id']}", Action="lambda:InvokeFunction", Principal="apigateway.amazonaws.com", SourceArn=f"arn:aws:execute-api:{REGION}:{account_id()}:{api_id}/*/*{path}")
        except ClientError as error:
            if not is_error(error, "ResourceConflictException"):
                raise
    api.create_deployment(restApiId=api_id, stageName="prod", description="Publish external travel provider API")
    return api_id


def main() -> None:
    api_ids: dict[str, str] = {}
    counts: dict[str, int] = {}
    for kind in ("flights", "hotels", "locations"):
        _ensure_table(kind)
        role_arn = _role(ROLE_NAMES[kind], TABLES[kind])
        function_arn = _ensure_lambda(kind, role_arn)
        api_ids[kind] = _ensure_api(kind, function_arn)
        counts[kind] = _seed(kind)
    save_state(provider_api_ids=api_ids, provider_api_names=API_NAMES, provider_table_names=TABLES, provider_function_names=FUNCTIONS)
    print("Provider APIs ready:")
    for kind in ("flights", "hotels", "locations"):
        print(f"  {kind}: API {api_ids[kind]}, table {TABLES[kind]}, seeded {counts[kind]} items")


if __name__ == "__main__":
    main()
