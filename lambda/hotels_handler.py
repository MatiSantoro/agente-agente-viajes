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


def _all_for_destination(destination):
    result = TABLE.query(KeyConditionExpression=Key("destination").eq(destination))
    items = result.get("Items", [])
    while result.get("LastEvaluatedKey"):
        result = TABLE.query(
            KeyConditionExpression=Key("destination").eq(destination),
            ExclusiveStartKey=result["LastEvaluatedKey"],
        )
        items.extend(result.get("Items", []))
    return items


def lambda_handler(event, _context):
    """Handles GET /hotels and GET /hotels/{id} API Gateway proxy events."""
    method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method")
    if method == "OPTIONS":
        return _response(204, {})
    if method != "GET":
        return _response(405, {"message": "Only GET is supported"})

    resource_path = event.get("resource") or event.get("requestContext", {}).get("resourcePath", "")
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
        if resource_path.endswith("/availability"):
            if not destination:
                return _response(400, {"message": "destination is required"})
            items = _all_for_destination(destination.upper())
            dates = sorted({item.get("checkIn") or item["checkInHotelId"].split("#", 1)[0] for item in items})
            stays = {}
            for item in items:
                key = (item.get("checkIn"), item.get("checkOut"), item.get("guests"), item.get("nights"))
                existing = stays.get(key)
                if not existing or item.get("pricePerNight", 0) < existing.get("lowestPricePerNight", 0):
                    stays[key] = {"checkIn": key[0], "checkOut": key[1], "guests": key[2], "nights": key[3], "lowestPricePerNight": item.get("pricePerNight"), "currency": item.get("currency", "USD")}
            return _response(200, {"destination": destination.upper(), "availableCheckIns": dates, "stays": sorted(stays.values(), key=lambda stay: (stay["checkIn"], stay["guests"], stay["lowestPricePerNight"])), "count": len(dates)})
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
        items = [item for item in result.get("Items", []) if item.get("checkOut") == check_out and int(item.get("guests", 0)) >= int(guests)]
        items.sort(key=lambda item: (item.get("pricePerNight", 0), -item.get("rating", 0)))
        return _response(200, {"items": items, "count": len(items)})
    except Exception:
        LOG.exception("Hotels data access failed")
        return _response(500, {"message": "Unable to retrieve hotels"})
