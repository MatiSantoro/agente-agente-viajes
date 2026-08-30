# AgentCore provisioning scripts

These scripts create Cognito OAuth scopes, an AgentCore Identity credential provider, a protected MCP Gateway, direct API Gateway targets, and the travel Harness. Direct API Gateway targets use the Gateway's IAM role (the supported outbound mode); the Harness uses the AgentCore Identity OAuth provider to obtain a scoped Cognito token for the Gateway's inbound JWT authorization.

Run them from the repository root in order:

```bash
python3 Scripts/01_cognito_identity.py
python3 Scripts/02_gateway_and_targets.py
python3 Scripts/03_harness.py
```

They use `AWS_PROFILE=agente-agente-viajes` and `AWS_REGION=us-east-1` by default. `Scripts/.state.json` records non-secret resource identifiers and is ignored by Git. Cognito's M2M client secret is passed directly to AgentCore Identity and never written to the repository or state file.
