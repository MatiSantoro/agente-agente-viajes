"""Print the exact Hotels OpenAPI inline schema for the live console demo.

Read-only: this script discovers the generated Hotels API ID by name/state and
prints JSON to stdout. It does not create or modify AWS resources.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from common import client, load_state


def protection_module():
    source = Path(__file__).with_name("12_protect_provider_apis.py")
    spec = importlib.util.spec_from_file_location("provider_api_protection_for_schema", source)
    if not spec or not spec.loader:
        raise RuntimeError("Could not load the OpenAPI helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def find_hotels_api_id() -> str:
    state = load_state()
    for item in client("apigateway").get_rest_apis(limit=500).get("items", []):
        if item.get("name") == "agente-agente-viajes-hotels":
            return item["id"]
    api_id = state.get("provider_api_ids", {}).get("hotels")
    if api_id:
        try:
            api = client("apigateway").get_rest_api(restApiId=api_id)
            if api.get("name") == "agente-agente-viajes-hotels":
                return api_id
        except Exception:
            pass
    raise RuntimeError("Hotels API is missing; run Scripts/00_deploy.py first")


def main() -> None:
    helpers = protection_module()
    spec = helpers.API_SPECS["hotels"]
    payload = json.loads(helpers.openapi_schema(find_hotels_api_id(), spec["paths"], "", ""))
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
