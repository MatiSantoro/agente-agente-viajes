# AgentCore provisioning scripts

These scripts create Cognito OAuth scopes, an AgentCore Identity credential provider, a protected MCP Gateway, direct API Gateway targets, and the travel Harness.

Run the provisioning scripts from the repository root in order:

```bash
.venv/bin/python -m pip install -r Scripts/requirements.txt
.venv/bin/python Scripts/01_cognito_identity.py
.venv/bin/python Scripts/02_gateway_and_targets.py
.venv/bin/python Scripts/03_harness.py
.venv/bin/python Scripts/06_ui_frontend.py
```

`06_ui_frontend.py` publishes the `UI/` static frontend through an S3 website bucket and CloudFront HTTPS distribution. It also creates the Cognito SPA client, protected chat API and Lambda bridge. The script prints the deployed URL and the demo login credentials; it intentionally does not store passwords in Git.

Test the complete agent while both targets are connected:

```bash
.venv/bin/python Scripts/04_test_agent.py
```

Before the live demo, remove only the Hotels target. Add it back in the AgentCore console as the live moment:

```bash
.venv/bin/python Scripts/05_remove_hotels_target.py
```
