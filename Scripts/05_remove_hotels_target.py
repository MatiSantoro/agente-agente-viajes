"""Remove only the Hotels target, so it can be added live during the demo."""

from __future__ import annotations

import time

from common import client, load_state, save_state

TARGET_NAME = "hotels-target"


def find_target(gateway_id: str) -> dict | None:
    for target in client("bedrock-agentcore-control").list_gateway_targets(gatewayIdentifier=gateway_id).get("items", []):
        if target["name"] == TARGET_NAME:
            return target
    return None


def main() -> None:
    state = load_state()
    gateway_id = state.get("gateway_id")
    if not gateway_id:
        raise RuntimeError("Gateway ID is missing; run 02_gateway_and_targets.py first.")
    target = find_target(gateway_id)
    if not target:
        print("Hotels target is already absent.")
        return
    client("bedrock-agentcore-control").delete_gateway_target(gatewayIdentifier=gateway_id, targetId=target["targetId"])
    for _ in range(24):
        time.sleep(5)
        if not find_target(gateway_id):
            targets = state.get("gateway_targets", {})
            targets.pop(TARGET_NAME, None)
            save_state(gateway_targets=targets)
            print("Hotels target deleted. Add it again through the AgentCore console during the live demo.")
            return
    raise TimeoutError("Timed out waiting for the Hotels target to be deleted.")


if __name__ == "__main__":
    main()
