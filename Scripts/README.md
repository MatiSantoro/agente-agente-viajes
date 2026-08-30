# AgentCore provisioning scripts

These scripts create Cognito OAuth scopes, an AgentCore Identity credential provider, a protected MCP Gateway, direct API Gateway targets, and the travel Harness.

Run them from the repository root in order:

```bash
python3 Scripts/01_cognito_identity.py
python3 Scripts/02_gateway_and_targets.py
python3 Scripts/03_harness.py
```

They use `AWS_PROFILE=agente-agente-viajes` and `AWS_REGION=us-east-1` by default. `Scripts/.state.json` records non-secret resource identifiers and is ignored by Git. Cognito's M2M client secret is passed directly to AgentCore Identity and never written to the repository or state file.
