"""Switch AgentCore Gateway inbound JWT validation to the platform scope."""

from __future__ import annotations

from common import client, load_state, wait_for


def main() -> None:
    state = load_state()
    required = ["gateway_id", "cognito_discovery_url", "platform_gateway_client_id", "platform_gateway_scope"]
    missing = [key for key in required if not state.get(key)]
    if missing:
        raise RuntimeError(f"Missing platform auth configuration: {missing}")
    control = client("bedrock-agentcore-control")
    current = control.get_gateway(gatewayIdentifier=state["gateway_id"])
    control.update_gateway(
        gatewayIdentifier=state["gateway_id"],
        name=current["name"],
        roleArn=current["roleArn"],
        authorizerType="CUSTOM_JWT",
        authorizerConfiguration={"customJWTAuthorizer": {"discoveryUrl": state["cognito_discovery_url"], "allowedClients": [state["platform_gateway_client_id"]], "allowedScopes": [state["platform_gateway_scope"]]}},
    )
    gateway = wait_for(lambda identifier: control.get_gateway(gatewayIdentifier=identifier), state["gateway_id"])
    print(f"Gateway inbound auth now accepts only {state['platform_gateway_scope']}")
    print(gateway["authorizerConfiguration"])


if __name__ == "__main__":
    main()
