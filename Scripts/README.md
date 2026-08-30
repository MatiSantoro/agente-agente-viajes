# AgentCore provisioning scripts

These scripts create Cognito OAuth scopes, an AgentCore Identity credential provider, a protected MCP Gateway, direct API Gateway targets, and the travel Harness.

Run the provisioning scripts from the repository root in order:

```bash
.venv/bin/python -m pip install -r Scripts/requirements.txt
.venv/bin/python Scripts/01_cognito_identity.py
.venv/bin/python Scripts/02_gateway_and_targets.py
.venv/bin/python Scripts/03_harness.py
```

Test the complete agent while both targets are connected:

```bash
.venv/bin/python Scripts/04_test_agent.py
```

Before the live demo, remove only the Hotels target. Add it back in the AgentCore console as the live moment:

```bash
.venv/bin/python Scripts/05_remove_hotels_target.py
```
