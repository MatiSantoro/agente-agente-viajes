"""Live-demo step: connect the already-protected Hotels REST API to AgentCore Gateway."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from common import REGION, client, load_state, save_state


def provider_module():
    source = Path(__file__).with_name("12_protect_provider_apis.py")
    spec = importlib.util.spec_from_file_location("provider_api_protection", source)
    if not spec or not spec.loader:
        raise RuntimeError("Could not load provider API helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    helpers = provider_module()
    state = load_state()
    resource_server = state["external_provider_resource_server_id"]
    provider_arn = state["external_provider_oauth_provider_arns"]["hotels"]
    spec = helpers.API_SPECS["hotels"]
    scope = f"{resource_server}/{spec['scope_suffix']}"
    token_url = f"https://{state['external_provider_domain']}.auth.{REGION}.amazoncognito.com/oauth2/token"
    target_id = helpers.ensure_openapi_target(
        client("bedrock-agentcore-control"),
        state["gateway_id"],
        spec,
        provider_arn,
        scope,
        token_url,
    )
    current = state.get("external_provider_openapi_target_ids", {})
    save_state(external_provider_openapi_target_ids={**current, "hotels": target_id})
    print(f"Hotels REST API target ready: {target_id}")


if __name__ == "__main__":
    main()
