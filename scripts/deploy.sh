
#!/usr/bin/env bash
set -euo pipefail
PROJECT=AssistIQ

echo "=== Building & deploying backend with SAM ==="
# sam build
# sam deploy --guided
sam build --template-file sam-template.yaml
sam deploy --config-file samconfig.toml


API=$(aws cloudformation describe-stacks --stack-name ${PROJECT} --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" --output text)
BUCKET=$(aws cloudformation describe-stacks --stack-name ${PROJECT} --query "Stacks[0].Outputs[?OutputKey=='WebsiteBucketName'].OutputValue" --output text)

echo "API: $API"
echo "Bucket: $BUCKET"

echo "=== Injecting API endpoint into frontend config ==="
# replace placeholder in app.js
sed -i.bak "s#REPLACE_WITH_API_ENDPOINT#${API}#g" frontend/assets/app.js

echo "=== Syncing website to S3 ==="
aws s3 sync frontend/ s3://$BUCKET --delete

echo "Done. Enable static website hosting and open: http://$BUCKET.s3-website-$(aws configure get region).amazonaws.com"
