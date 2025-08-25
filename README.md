
# AssistIQ — AI IT Support on AWS (Lex V2)

Dark, glass‑morphism front‑end + fully serverless back‑end. Minimal manual steps.

## What you get
- **Modern dark UI** (responsive, gradient, glass) with a custom chat widget.
- **HTTP API** `/chat` → **ChatProxy Lambda** → **Lex V2** bot.
- **Fulfillment Lambda** for business logic → FAQ in **DynamoDB**, fallback via **SES** email.
- **DynamoDB tables** for FAQs and chat logs.
- **S3 website hosting** for the front‑end.

> ⚠️ Manual bits you still must do (AWS limitations):
> 1. Verify **SES** sender/receiver emails and (if needed) move SES out of Sandbox.
> 2. Create/Import the **Lex V2 Bot** once (we pass its `BotId`/`BotAliasId` into SAM). A JSON import file is provided at the end of this README.

---

## 0) Prereqs
- AWS account + IAM user/role with admin (or equivalent) for setup.
- Region: choose one where **Lex V2** and **SES** are available (e.g., `us-east-1`).
- Tools:
  - AWS CLI configured: `aws configure` 

Hide
  - AWS SAM CLI
  - Python 3.10+ (for local seeding script)

## 1) Configure SES (email escalation)
1. In **SES → Identities**, verify:
   - `SourceEmail` (sender) e.g., `assistiq@yourdomain.com`
   - `SupportEmail` (destination IT inbox) e.g., `it@yourdomain.com`
2. If your SES account is in **Sandbox**, open a support case to move to **Production** (so you can email unverified addresses).

## 2) Create/Import the Lex V2 bot (one-time)
You can create the bot manually or import the JSON below.
- **Name**: `AssistIQSupportBot`
- **Locale**: `en_US`
- **Intents**: `PasswordReset`, `WifiIssue`, `EmailAccess`, and a `Fallback`.
- **Fulfillment**: Lambda → `AssistIQ-Fulfillment` (SAM will create it; wire after deploy).
- After building and creating an **Alias**, note its **BotId** and **BotAliasId**.

> You can also import the included JSON snippet at the end of this README (copy/paste into a file and import).

## 3) Deploy the stack
```bash
# from the project root
sam build
sam deploy --guided
# parameters:
# ProjectName: AssistIQ
# SourceEmail: VERIFIED_SENDER@domain
# SupportEmail: IT_INBOX@domain
# BotId: <copy from Lex console>
# BotAliasId: <copy from Lex console>
# BotLocaleId: en_US
# WebsiteBucketName: (leave empty to autogenerate)
```

Outputs include:
- `ApiEndpoint` → paste into front‑end config.
- `WebsiteBucketName` → where the site will be hosted.

## 4) Publish the website
```bash
# one‑liner helper (Linux/macOS):
./scripts/deploy.sh
# or manual:
# replace placeholder in frontend/assets/app.js with the ApiEndpoint value
aws s3 sync frontend/ s3://<WebsiteBucketName> --delete
```

Open the site URL shown by S3 Static Website hosting (or front with CloudFront later).

## 5) Seed the FAQ table (optional demo content)
```bash
python3 scripts/seed_faq.py $(aws cloudformation describe-stacks --stack-name AssistIQ   --query "Stacks[0].Outputs[?OutputKey=='FAQTableName'].OutputValue" --output text)
```

## 6) Wire Lex → Fulfillment Lambda
In **Lex console → your bot → intents → fulfillment** set the Lambda to **AssistIQ-Fulfillment** (created by SAM). Build the bot and redeploy the alias.

---

## Front-end customizations
- Always dark theme with gradients + glass.
- Centered, curved, bordered navbar.
- Fully responsive.
- Chat bubbles match glass style; API endpoint configured via `window.ASSISTIQ_API_ENDPOINT` in `assets/app.js`.
- You can change accent colors in `assets/style.css`.

## Monitoring & Feedback
- **CloudWatch Logs** for both Lambdas.
- **ChatLogs** table records: query, (optional) NLU confidence, intent, sessionId, and timestamp.
- Weekly review logs → add new utterances/FAQs.

## Security
- IAM least‑privilege policies scoped to DynamoDB tables and SES send.
- Public API for demo; for intranet, put HTTP API behind a WAF/Cognito authorizer and host site privately.
- HTTPS: front with CloudFront + ACM cert for production.

---

## Common issues & fixes
- **SES Sandbox** → Only verified recipients work. Move to production via AWS Support.
- **Lex permissions from bot to Lambda** → Attach the proper execution role when configuring fulfillment.
- **CORS** → The HTTP API enables CORS; if you front with a different domain, adjust `AllowOrigins`.
- **Lex Runtime AccessDenied in ChatProxy** → Verify the ChatProxy role has `lex:RecognizeText`.
- **No answer for valid FAQ** → Add keywords in `scripts/seed_faq.json` or enhance matching.
- **Region mismatch** → Keep all resources in the same region; set AWS CLI default to that region.

---

## Lex import JSON (optional)
This skeleton defines basic intents + sample utterances and uses Lambda fulfillment. Import it in **Lex V2 → Bot → Import** then create an alias.

```json
{
  "metadataVersion": "2022-07-14",
  "resourceType": "BOT",
  "name": "AssistIQSupportBot",
  "locale": "en_US",
  "intents": [
    { "name": "PasswordReset", "sampleUtterances": ["I forgot my password", "reset password", "can't log in"] },
    { "name": "WifiIssue", "sampleUtterances": ["wifi not working", "internet is slow", "can't connect to wifi"] },
    { "name": "EmailAccess", "sampleUtterances": ["can't access email", "outlook not opening", "email down"] },
    { "name": "FallbackIntent", "sampleUtterances": [] }
  ]
}
```

---

## Repo structure
```
backend/
  functions/
    fulfillment/
    chat_proxy/
frontend/
  assets/
scripts/
sam-template.yaml
```
