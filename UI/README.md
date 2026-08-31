# Viajá UI

Static frontend for the AgentCore travel Harness. `Scripts/06_ui_frontend.py` creates the Cognito SPA client and demo users, a Cognito-protected chat API, the S3 website bucket, and a CloudFront HTTPS URL. It then uploads this folder with a generated `config.js` file.

The UI has its own sign-in screen. It authenticates directly with the Cognito User Pool using `USER_PASSWORD_AUTH`; it does not redirect users to the Cognito Hosted UI. It renders returned agent Markdown with `marked` and sanitizes it with DOMPurify.

Only Claude Sonnet 4.6 and Nova Pro are presented because they use the compatible Bedrock Converse / AgentCore tool contract. Nova is deliberately locked to temperature `0` to preserve reliable MCP tool invocation.
