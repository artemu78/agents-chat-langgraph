---
name: nebula-aws-logs
description: Use when you need to view, tail, or debug AWS CloudWatch logs for the Nebula Glass backend (AWS SAM Lambda functions).
---

# Nebula Glass AWS Logs

This skill provides precise instructions for querying AWS CloudWatch logs for the Nebula Glass backend, specifically for the `NebulaChatFunction` deployed via AWS SAM.

## 1. Finding the Log Group Name

AWS SAM generates a unique CloudWatch log group for the Lambda function. The name will typically contain `NebulaChatFunction` and a random suffix. 

To find the correct log group dynamically, use this command:
```bash
aws logs describe-log-groups --query 'logGroups[*].logGroupName' --output text | grep -o '/aws/lambda/.*NebulaChatFunction.*' | head -n 1
```

*(Note: In the current dev environment, the log group is often `/aws/lambda/LLMChatLangGraph-NebulaChatFunction-tpDjRscpkX8r`.)*

## 2. Fetching Recent Logs (For Debugging Errors)

When investigating an error or checking recent executions, use `aws logs tail` with the `--since` flag.

```bash
LOG_GROUP=$(aws logs describe-log-groups --query 'logGroups[*].logGroupName' --output text | grep -o '/aws/lambda/.*NebulaChatFunction.*' | head -n 1)
aws logs tail "$LOG_GROUP" --since 15m
```
*Note: Do not use `--max-items` with the `tail` command as it is an unknown option in some AWS CLI v2 versions.*

## 3. Tailing Logs in Real-Time (Live Debugging)

If you are about to trigger a request and want to watch the logs live, run the command in the background (using `is_background: true` in `run_shell_command`):

```bash
LOG_GROUP=$(aws logs describe-log-groups --query 'logGroups[*].logGroupName' --output text | grep -o '/aws/lambda/.*NebulaChatFunction.*' | head -n 1)
aws logs tail "$LOG_GROUP" --follow
```

## 4. Searching for Specific Errors

If the logs are too verbose, pipe them into `grep`:

```bash
LOG_GROUP=$(aws logs describe-log-groups --query 'logGroups[*].logGroupName' --output text | grep -o '/aws/lambda/.*NebulaChatFunction.*' | head -n 1)
aws logs tail "$LOG_GROUP" --since 1h | grep -E -i "error|exception|traceback" -A 15 -B 2
```

## Requirements

The local `aws` CLI must be configured and authenticated (check with `aws sts get-caller-identity`). This is already handled in the user's environment.