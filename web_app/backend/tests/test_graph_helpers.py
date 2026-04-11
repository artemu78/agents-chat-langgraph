"""Unit tests for graph.router, format_history, and main._process_attachments."""
from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.graph import END

import graph as graph_module
from graph import format_history, router
from main import _process_attachments


@pytest.fixture
def reset_local_tokens(monkeypatch):
    """Isolate token counter used by router when not on DynamoDB."""
    import persistence

    persistence._LOCAL_USER_TOKENS.clear()
    yield
    persistence._LOCAL_USER_TOKENS.clear()


def test_router_paused_returns_end():
    state = {
        "messages": [{"role": "Gemini", "content": "hi"}],
        "paused": True,
        "is_asking": False,
        "user_id": "u1",
    }
    assert router(state) is END


def test_router_system_message_returns_end(reset_local_tokens):
    state = {
        "messages": [{"role": "System", "content": "Gemini Error: x"}],
        "paused": False,
        "is_asking": False,
        "user_id": "u1",
    }
    assert router(state) is END


def test_router_ask_routes_human(reset_local_tokens):
    state = {
        "messages": [{"role": "Gemini", "content": "Need [ASK] help"}],
        "paused": False,
        "is_asking": False,
        "user_id": "u1",
    }
    assert router(state) == "Human"


def test_router_token_limit(reset_local_tokens, monkeypatch):
    monkeypatch.setattr(graph_module, "get_user_tokens", lambda uid: 500_000)
    state = {
        "messages": [{"role": "Gemini", "content": "hi"}],
        "paused": False,
        "is_asking": False,
        "user_id": "u1",
    }
    assert router(state) == "LimitReached"


def test_router_human_after_openai_goes_gemini(reset_local_tokens):
    state = {
        "messages": [
            {"role": "Gemini", "content": "a"},
            {"role": "OpenAI", "content": "b"},
            {"role": "Human", "content": "c"},
        ],
        "paused": False,
        "is_asking": False,
        "user_id": "u1",
    }
    assert router(state) == "Gemini"


def test_router_human_after_gemini_goes_openai(reset_local_tokens):
    state = {
        "messages": [
            {"role": "OpenAI", "content": "a"},
            {"role": "Gemini", "content": "b"},
            {"role": "Human", "content": "c"},
        ],
        "paused": False,
        "is_asking": False,
        "user_id": "u1",
    }
    assert router(state) == "OpenAI"


def test_router_human_only_defaults_gemini(reset_local_tokens):
    state = {
        "messages": [{"role": "Human", "content": "only"}],
        "paused": False,
        "is_asking": False,
        "user_id": "u1",
    }
    assert router(state) == "Gemini"


def test_router_alternate_gemini_to_openai(reset_local_tokens):
    state = {
        "messages": [{"role": "Gemini", "content": "proposal"}],
        "paused": False,
        "is_asking": False,
        "user_id": "u1",
    }
    assert router(state) == "OpenAI"


def test_router_alternate_openai_to_gemini(reset_local_tokens):
    state = {
        "messages": [{"role": "OpenAI", "content": "<audit>x</audit>"}],
        "paused": False,
        "is_asking": False,
        "user_id": "u1",
    }
    assert router(state) == "Gemini"


def test_format_history_gemini_roles():
    role_map = {"self": "Gemini", "Gemini": "model", "gemini": True}
    messages = [
        {"role": "Human", "content": "h1"},
        {"role": "OpenAI", "content": "o1"},
        {"role": "Gemini", "content": "g1"},
    ]
    out = format_history(messages, role_map)
    assert out[0]["role"] == "user"
    assert "[CLARIFICATION FROM HUMAN]" in out[0]["parts"][0]["text"]
    assert "[OpenAI]" in out[1]["parts"][0]["text"]
    assert out[2]["parts"][0]["text"] == "g1"


def test_format_history_openai_roles():
    role_map = {"self": "OpenAI", "OpenAI": "assistant"}
    messages = [
        {"role": "Human", "content": "h1"},
        {"role": "Gemini", "content": "g1"},
    ]
    out = format_history(messages, role_map)
    assert "[CLARIFICATION FROM HUMAN]" in out[0]["content"]
    assert "[Gemini]" in out[1]["content"]


def test_process_attachments_no_at():
    assert _process_attachments("plain") == "plain"
    assert _process_attachments("") == ""
    assert _process_attachments(None) is None  # type: ignore[arg-type]


def test_process_attachments_resolves_absolute_file(tmp_path: Path):
    f = tmp_path / "att.txt"
    f.write_text("inside", encoding="utf-8")
    out = _process_attachments(f"See @{f}")
    assert "[ATTACHED FILE:" in out
    assert "inside" in out
    assert "[END OF ATTACHMENT]" in out


def test_process_attachments_missing_file():
    out = _process_attachments("ref @/no/such/file_zz_99.txt here")
    assert "@/no/such/file_zz_99.txt" in out
