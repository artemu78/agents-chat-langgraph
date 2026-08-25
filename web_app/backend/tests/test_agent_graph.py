from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from graph import router
from state import OrchestratorDecision
from tools import web_search


def test_web_search_rejects_empty_query():
    result = web_search("   ")
    assert "Search query is empty" in result


def test_web_search_handles_failure(monkeypatch):
    def boom(_query: str):
        raise RuntimeError("offline")

    monkeypatch.setattr("tools._ddg.invoke", boom)
    assert "currently unavailable" in web_search("weather")


def test_orchestrator_decision_validation_requires_targets():
    decision = OrchestratorDecision(message="please clarify", action="delegate")
    with pytest.raises(ValueError):
        decision.validate()


def test_router_routes_to_gemini():
    state = {
        "messages": [AIMessage(content="ok", name="Orchestrator")],
        "orchestrator_decision": {"action": "delegate", "next_model": "Gemini", "next_hat": "White"},
        "paused": False,
        "step_count": 0,
    }
    assert router(state) == "Gemini"


def test_router_routes_to_openai():
    state = {
        "messages": [AIMessage(content="ok", name="Orchestrator")],
        "orchestrator_decision": {"action": "delegate", "next_model": "OpenAI", "next_hat": "Black"},
        "paused": False,
        "step_count": 0,
    }
    assert router(state) == "OpenAI"


def test_router_routes_to_human():
    state = {
        "messages": [AIMessage(content="ok", name="Orchestrator")],
        "orchestrator_decision": {"action": "ask_human", "next_hat": None, "next_model": None},
        "paused": False,
        "step_count": 0,
    }
    assert router(state) == "Human"


def test_router_routes_to_end_on_conclude():
    state = {
        "messages": [AIMessage(content="ok", name="Orchestrator")],
        "orchestrator_decision": {"action": "conclude"},
        "paused": False,
        "step_count": 0,
    }
    assert router(state) == "__end__"


def test_router_returns_orchestrator_after_participant_reply():
    state = {
        "messages": [AIMessage(content="done", name="Gemini")],
        "paused": False,
        "step_count": 0,
    }
    assert router(state) == "Orchestrator"


def test_router_stops_on_token_limit(monkeypatch):
    monkeypatch.setattr("graph.get_user_tokens", lambda uid: 500_000)
    state = {"messages": [AIMessage(content="hi", name="Gemini")], "user_id": "u1", "paused": False, "step_count": 0}
    assert router(state) == "LimitReached"


def test_router_stops_after_iteration_limit():
    state = {"messages": [AIMessage(content="hi", name="Gemini")], "paused": False, "step_count": 11}
    assert router(state) == "__end__"
