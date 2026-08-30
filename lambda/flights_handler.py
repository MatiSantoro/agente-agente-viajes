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


def lambda_handler(event, _context):
    """Handles GET /flights and GET /flights/{id} API Gateway proxy events."""
    method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method")
    if method == "OPTIONS":
        return _response(204, {})
    if method != "GET":
        return _response(405, {"message": "Only GET is supported"})

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
        if not all((origin, destination, date)):
            return _response(400, {"message": "origin, destination and date are required"})
        result = TABLE.query(
            KeyConditionExpression=Key("route").eq(f"{origin.upper()}#{destination.upper()}")
            & Key("departureDateFlightId").begins_with(date)
        )
        return _response(200, {"items": result.get("Items", []), "count": result.get("Count", 0)})
    except Exception:
        LOG.exception("Flights data access failed")
        return _response(500, {"message": "Unable to retrieve flights"})
