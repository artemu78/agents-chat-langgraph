from __future__ import annotations

from typing import Sequence

from langchain_core.messages import BaseMessage

from persistence import add_user_tokens


def record_usage_from_messages(user_id: str, messages: Sequence[BaseMessage]) -> None:
    total = 0
    for message in messages:
        meta = getattr(message, "usage_metadata", None) or {}
        if not meta:
            meta = getattr(message, "response_metadata", {}).get("token_usage", {}) or {}
        if isinstance(meta, dict):
            input_tokens = meta.get("input_tokens") or meta.get("prompt_tokens") or 0
            output_tokens = meta.get("output_tokens") or meta.get("completion_tokens") or 0
            total += int(input_tokens) + int(output_tokens)
    if total:
        add_user_tokens(user_id, total)
