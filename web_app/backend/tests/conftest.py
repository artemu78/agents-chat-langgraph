"""
Test environment: DEV_MODE auth bypass, no DynamoDB/Lambda so main uses MemorySaver.
Must not import main before these env vars are set.
"""
from __future__ import annotations

import os

os.environ["DEV_MODE"] = "1"
for _k in ("USE_DYNAMODB", "AWS_LAMBDA_FUNCTION_NAME", "BACKEND_DEBUG", "BACKEND_DEBUG_TRACE_PYTHON"):
    os.environ.pop(_k, None)
