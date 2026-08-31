"""Read-only location resolver for the travel demo."""

import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(body, default=lambda value: float(value) if isinstance(value, Decimal) else str(value)),
    }


def lambda_handler(event, _context):
    if (event.get("httpMethod") or "GET") != "GET":
        return _response(405, {"message": "Only GET is supported"})
    query = (event.get("queryStringParameters") or {}).get("query", "").strip().lower()
    if not query:
        return _response(400, {"message": "query is required"})
    result = TABLE.query(KeyConditionExpression=Key("searchKey").eq(query))
    return _response(200, {"query": query, "locations": result.get("Items", []), "count": result.get("Count", 0)})
