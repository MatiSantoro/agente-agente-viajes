"""Lambda proxy handler for the travel demo's Flights API."""
import json
import logging
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key

LOG = logging.getLogger()
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO"))
TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value) if value % 1 else int(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,OPTIONS",
        },
        "body": json.dumps(body, default=_json_default),
    }


def _query(event):
    return event.get("queryStringParameters") or {}


def _all_for_route(route):
    result = TABLE.query(KeyConditionExpression=Key("route").eq(route))
    items = result.get("Items", [])
    while result.get("LastEvaluatedKey"):
        result = TABLE.query(
            KeyConditionExpression=Key("route").eq(route),
            ExclusiveStartKey=result["LastEvaluatedKey"],
        )
        items.extend(result.get("Items", []))
    return items


def lambda_handler(event, _context):
    """Handles GET /flights and GET /flights/{id} API Gateway proxy events."""
    method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method")
    if method == "OPTIONS":
        return _response(204, {})
    if method != "GET":
        return _response(405, {"message": "Only GET is supported"})

    resource_path = event.get("resource") or event.get("requestContext", {}).get("resourcePath", "")
    flight_id = (event.get("pathParameters") or {}).get("id")
    try:
        if flight_id:
            result = TABLE.scan(FilterExpression=Attr("flightId").eq(flight_id))
            items = result.get("Items", [])
            while result.get("LastEvaluatedKey"):
                result = TABLE.scan(
                    FilterExpression=Attr("flightId").eq(flight_id),
                    ExclusiveStartKey=result["LastEvaluatedKey"],
                )
                items.extend(result.get("Items", []))
            return _response(200, items[0]) if items else _response(404, {"message": "Flight not found"})

        params = _query(event)
        origin, destination, date = params.get("origin"), params.get("destination"), params.get("date")
        if resource_path.endswith("/availability"):
            if not all((origin, destination)):
                return _response(400, {"message": "origin and destination are required"})
            items = _all_for_route(f"{origin.upper()}#{destination.upper()}")
            dates = sorted({item.get("departureDate") or item["departureDateFlightId"].split("#", 1)[0] for item in items})
            options = [
                {
                    "date": available_date,
                    "lowestPrice": min(item["price"] for item in items if (item.get("departureDate") or item["departureDateFlightId"].split("#", 1)[0]) == available_date),
                    "hasNonstop": any(item.get("stops") == 0 for item in items if (item.get("departureDate") or item["departureDateFlightId"].split("#", 1)[0]) == available_date),
                }
                for available_date in dates
            ]
            return _response(200, {"origin": origin.upper(), "destination": destination.upper(), "availableDates": dates, "options": options, "count": len(dates)})
        if not all((origin, destination, date)):
            return _response(400, {"message": "origin, destination and date are required"})
        items = [item for item in _all_for_route(f"{origin.upper()}#{destination.upper()}") if (item.get("departureDate") or item["departureDateFlightId"].split("#", 1)[0]) == date]
        max_price, max_stops = params.get("maxPrice"), params.get("maxStops")
        if max_price:
            items = [item for item in items if item.get("price", 0) <= float(max_price)]
        if max_stops:
            items = [item for item in items if item.get("stops", 0) <= int(max_stops)]
        items.sort(key=lambda item: (item.get("price", 0), item.get("stops", 0)))
        return _response(200, {"items": items, "count": len(items)})
    except Exception:
        LOG.exception("Flights data access failed")
        return _response(500, {"message": "Unable to retrieve flights"})
