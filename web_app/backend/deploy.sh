#!/bin/bash                                                                                                                                            
cd "$(dirname "$0")"
rm -rf .aws-sam
sam build
sam deploy --parameter-overrides "FirebaseCredentials=\"$(cat firebase-credentials.json | jq -c .)\""
