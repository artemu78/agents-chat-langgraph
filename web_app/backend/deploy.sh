#!/bin/bash
set -e

# Navigate to the script's directory
cd "$(dirname "$0")"

# 1. Load local environment variables if .env exists
if [ -f .env ]; then
    echo "--- Loading .env ---"
    # Export variables from .env, ignoring comments
    export $(grep -v '^#' .env | xargs)
fi

# 2. Check for required keys
MISSING_KEYS=0
if [ -z "$GEMINI_API_KEY" ]; then
    echo "Error: GEMINI_API_KEY is not set in .env or environment."
    MISSING_KEYS=1
fi
if [ -z "$OPENAI_API_KEY" ]; then
    echo "Error: OPENAI_API_KEY is not set in .env or environment."
    MISSING_KEYS=1
fi

if [ "$MISSING_KEYS" -eq 1 ]; then
    echo "Please ensure you have a .env file with the following:"
    echo "GEMINI_API_KEY=your_key"
    echo "OPENAI_API_KEY=your_key"
    exit 1
fi

# 3. Read Firebase credentials and format as compact JSON
echo "--- Reading Firebase Credentials ---"
if [ ! -f firebase-credentials.json ]; then
    echo "Error: firebase-credentials.json not found."
    exit 1
fi
# We use jq to ensure it's valid compact JSON
FIREBASE_JSON=$(cat firebase-credentials.json | jq -c .)

# 4. Define models (with defaults if not in env)
GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.1-flash-lite-preview}"
OPENAI_MODEL="${OPENAI_MODEL:-gpt-5.4-nano}"

# 5. Clean and Build
echo "--- Building SAM Application ---"
rm -rf .aws-sam
sam build

# 6. Deploy
echo "--- Deploying to AWS ---"
# Passing all parameters explicitly. 
# We use single quotes around the entire parameter value to handle the JSON correctly.
sam deploy --parameter-overrides \
    "GeminiApiKey='${GEMINI_API_KEY}'" \
    "OpenaiApiKey='${OPENAI_API_KEY}'" \
    "FirebaseCredentials='${FIREBASE_JSON}'" \
    "GeminiModel='${GEMINI_MODEL}'" \
    "OpenaiModel='${OPENAI_MODEL}'"

echo "--- Deployment Complete ---"
