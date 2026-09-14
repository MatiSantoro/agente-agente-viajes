# AgentCore provisioning scripts

All scripts use Boto3 with the `agente-agente-viajes` AWS profile and `us-east-1` region. They manage the demo resources in the current AWS account; they do not create the three provider APIs or their Lambda/DynamoDB backends.

## Current architecture

- `01_cognito_identity.py` ensures the UI/platform Cognito User Pool and OIDC discovery URL.
- `11_external_provider_oauth.py` creates the separate external-provider User Pool, one resource server with Flights, Locations, and Hotels scopes, and one M2M app client plus AgentCore Identity OAuth provider per API.
- `14_platform_gateway_oauth.py` creates the platform `gateway.invoke` scope, M2M app client, and Identity provider used by the Harness to call the Gateway.
- `02_gateway_and_targets.py` configures the Gateway's platform OAuth inbound auth and the Gateway role's least-privilege outbound OAuth access. It does not create targets.
- `12_protect_provider_apis.py` protects the existing Flights, Locations, and Hotels REST API methods with Cognito scope validation and attaches Flights and Locations as `OPEN_API` Gateway targets using OAuth.
- `13_add_hotels_gateway_target.py` attaches the already-protected Hotels API as an `OPEN_API` target during the live demo.
- `03_harness.py` creates/updates the Harness with Gateway OAuth outbound auth and platform-pool inbound auth.
- `06_ui_frontend.py` publishes the UI, chat API, and Cognito SPA client.

## Provision or reconcile

Run from the repository root. Provider API Gateway APIs and their backend resources must already exist.

```bash
.venv/bin/python -m pip install -r Scripts/requirements.txt
.venv/bin/python Scripts/01_cognito_identity.py
.venv/bin/python Scripts/11_external_provider_oauth.py
.venv/bin/python Scripts/14_platform_gateway_oauth.py
.venv/bin/python Scripts/02_gateway_and_targets.py
.venv/bin/python Scripts/12_protect_provider_apis.py
.venv/bin/python Scripts/03_harness.py
.venv/bin/python Scripts/06_ui_frontend.py
```

To add Hotels as the live-demo moment, run:

```bash
.venv/bin/python Scripts/13_add_hotels_gateway_target.py
```

For a demo that starts without Hotels, Flights and Locations remain connected; do not run step 13 until the live addition. `04_test_agent.py` tests the Harness after the Harness endpoint is ready.

## Teardown

`99_teardown_project.py` is scoped to the verified project resources in account `239248123204`, region `us-east-1`. It prints a plan by default and performs no mutations unless `--execute` is supplied. It preserves unrelated workloads and shared account resources, including the AWS-managed DynamoDB KMS key.

```bash
.venv/bin/python Scripts/99_teardown_project.py
.venv/bin/python Scripts/99_teardown_project.py --execute
```
