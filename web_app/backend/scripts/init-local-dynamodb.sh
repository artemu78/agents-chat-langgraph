#!/usr/bin/env bash
# Create AI_Chat_Sessions on DynamoDB Local if missing (matches template.yaml).
set -euo pipefail
cd "$(dirname "$0")/.."
ENDPOINT="${DYNAMODB_LOCAL_ENDPOINT:-http://localhost:8000}"
TABLE="${DYNAMODB_TABLE:-AI_Chat_Sessions}"

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-local}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-local}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

if aws dynamodb describe-table --table-name "$TABLE" --endpoint-url "$ENDPOINT" &>/dev/null; then
  echo "Table $TABLE already exists at $ENDPOINT"
  exit 0
fi

aws dynamodb create-table \
  --table-name "$TABLE" \
  --attribute-definitions \
    AttributeName=thread_id,AttributeType=S \
    AttributeName=checkpoint_id,AttributeType=S \
  --key-schema \
    AttributeName=thread_id,KeyType=HASH \
    AttributeName=checkpoint_id,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --endpoint-url "$ENDPOINT"

echo "Created table $TABLE at $ENDPOINT"
