"""Lambda proxy handler for the travel demo's Hotels API."""
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
    """Handles GET /hotels and GET /hotels/{id} API Gateway proxy events."""
    method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method")
    if method == "OPTIONS":
        return _response(204, {})
    if method != "GET":
        return _response(405, {"message": "Only GET is supported"})

    hotel_id = (event.get("pathParameters") or {}).get("id")
    try:
        if hotel_id:
            result = TABLE.scan(FilterExpression=Attr("hotelId").eq(hotel_id))
            items = result.get("Items", [])
            while result.get("LastEvaluatedKey"):
                result = TABLE.scan(
                    FilterExpression=Attr("hotelId").eq(hotel_id),
                    ExclusiveStartKey=result["LastEvaluatedKey"],
                )
                items.extend(result.get("Items", []))
            return _response(200, items[0]) if items else _response(404, {"message": "Hotel not found"})

        params = _query(event)
        destination, check_in = params.get("destination"), params.get("checkIn")
        check_out, guests = params.get("checkOut"), params.get("guests")
        if not all((destination, check_in, check_out, guests)):
            return _response(400, {"message": "destination, checkIn, checkOut and guests are required"})
        try:
            if int(guests) < 1:
                raise ValueError
        except ValueError:
            return _response(400, {"message": "guests must be a positive integer"})
        result = TABLE.query(
            KeyConditionExpression=Key("destination").eq(destination.upper())
            & Key("checkInHotelId").begins_with(check_in)
        )
        return _response(200, {"items": result.get("Items", []), "count": result.get("Count", 0)})
    except Exception:
        LOG.exception("Hotels data access failed")
        return _response(500, {"message": "Unable to retrieve hotels"})
