"""API tests with main.graph replaced by a fake (no real LangGraph / LLM)."""
from __future__ import annotations

import json
from typing import Any, Optional

import pytest
from starlette.testclient import TestClient


class _Snapshot:
    __slots__ = ("values", "next")

    def __init__(self, values: Optional[dict[str, Any]] = None, next_: tuple = ()):
        self.values = values or {}
        self.next = next_


class FakeGraph:
    def __init__(self) -> None:
        self.snapshot = _Snapshot({})
        self.update_calls: list[tuple[dict[str, Any], Optional[str]]] = []
        self.astream_events: list[dict[str, Any]] = []

    def get_state(self, config: dict) -> _Snapshot:
        return self.snapshot

    def set_snapshot(self, values: dict[str, Any], next_: tuple = ()) -> None:
        self.snapshot = _Snapshot(values, next_)

    def update_state(
        self,
        config: dict,
        values: dict[str, Any],
        as_node: Optional[str] = None,
    ) -> None:
        self.update_calls.append((dict(values), as_node))
        merged = {**self.snapshot.values, **values}
        self.snapshot = _Snapshot(merged, self.snapshot.next)

    async def astream(self, input, config, stream_mode="updates"):
        for ev in self.astream_events:
            yield ev


@pytest.fixture
def fake_graph(monkeypatch) -> FakeGraph:
    import main

    fake = FakeGraph()
    monkeypatch.setattr(main, "graph", fake)
    monkeypatch.setattr(main, "generate_session_name", lambda topic, uid: f"named-{topic[:5]}")
    monkeypatch.setattr(main, "save_user_session", lambda uid, tid, name: None)
    monkeypatch.setattr(main, "list_user_sessions", lambda uid: [{"thread_id": "t1", "session_name": "S1", "updated_at": 123}])
    return fake


@pytest.fixture
def client(fake_graph: FakeGraph) -> TestClient:
    import main

    return TestClient(main.app)


def test_read_root(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "Nebula Glass API is running"
    assert "version" in data


def test_user_tokens_dev_user(client: TestClient):
    r = client.get("/user/tokens")
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 500_000
    assert "tokens_used" in body


def test_create_session(client: TestClient):
    r = client.post("/session", json={"thread_id": "tid-1"})
    assert r.status_code == 200
    assert r.json() == {"thread_id": "tid-1"}


def test_chat_stream_no_state(client: TestClient, fake_graph: FakeGraph):
    fake_graph.set_snapshot({})
    r = client.get("/chat/stream", params={"thread_id": "t1"})
    assert r.status_code == 200
    text = r.text
    assert "No state found" in text
    assert "error" in text


def test_chat_stream_messages_done(client: TestClient, fake_graph: FakeGraph):
    fake_graph.set_snapshot({"messages": [{"role": "Human", "content": "x"}]})
    fake_graph.astream_events = [
        {
            "Gemini": {
                "messages": [{"role": "Gemini", "content": "hello"}],
                "is_asking": False,
            }
        }
    ]
    r = client.get("/chat/stream", params={"thread_id": "t1"})
    assert r.status_code == 200
    lines = [ln for ln in r.text.splitlines() if ln.startswith("data: ") and not ln.endswith("[DONE]")]
    payloads = []
    for ln in lines:
        raw = ln.removeprefix("data: ").strip()
        if raw == "[DONE]":
            continue
        payloads.append(json.loads(raw))
    assert any(p.get("type") == "message" and p.get("node") == "Gemini" for p in payloads)
    assert "data: [DONE]" in r.text


def test_chat_stream_interrupt_key(client: TestClient, fake_graph: FakeGraph):
    fake_graph.set_snapshot({"messages": [{"role": "Human", "content": "x"}]})
    fake_graph.astream_events = [{"__interrupt__": ()}]
    r = client.get("/chat/stream", params={"thread_id": "t1"})
    assert r.status_code == 200
    assert "interrupt" in r.text


def test_chat_stream_is_asking(client: TestClient, fake_graph: FakeGraph):
    fake_graph.set_snapshot({"messages": [{"role": "Human", "content": "x"}]})
    fake_graph.astream_events = [
        {"Gemini": {"messages": [{"role": "Gemini", "content": "ok"}], "is_asking": True}}
    ]
    r = client.get("/chat/stream", params={"thread_id": "t1"})
    assert r.status_code == 200
    assert r.text.count("interrupt") >= 1


def test_chat_stream_astream_error(client: TestClient, fake_graph: FakeGraph):
    fake_graph.set_snapshot({"messages": [{"role": "Human", "content": "x"}]})

    async def boom(*a, **k):
        if False:
            yield {}
        raise RuntimeError("stream failed")

    fake_graph.astream = boom  # type: ignore[method-assign]
    r = client.get("/chat/stream", params={"thread_id": "t1"})
    assert r.status_code == 200
    assert "stream failed" in r.text
    assert "error" in r.text


def test_post_input_pause_only(client: TestClient, fake_graph: FakeGraph):
    fake_graph.set_snapshot({"paused": False})
    r = client.post(
        "/chat/input",
        json={"thread_id": "t1", "paused": True},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "updated"
    assert fake_graph.update_calls and fake_graph.update_calls[0][0].get("paused") is True


def test_post_input_seed_topic(client: TestClient, fake_graph: FakeGraph):
    r = client.post(
        "/chat/input",
        json={"thread_id": "t2", "seed_topic": "My topic"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "started"
    assert body["session_name"] == "named-My to"
    assert any("Topic:" in str(c[0]) for c in fake_graph.update_calls)


def test_post_input_content_no_next(client: TestClient, fake_graph: FakeGraph):
    fake_graph.set_snapshot({"messages": []}, next_=())
    r = client.post(
        "/chat/input",
        json={"thread_id": "t3", "content": "hello"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "updated"
    resume = [c for c in fake_graph.update_calls if c[1] == "Human"]
    assert not resume


def test_post_input_content_resume(client: TestClient, fake_graph: FakeGraph):
    fake_graph.set_snapshot({"messages": [{"role": "Gemini", "content": "q"}]}, next_=("Human",))
    r = client.post(
        "/chat/input",
        json={"thread_id": "t4", "content": "answer"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "resumed"
    resume = [c for c in fake_graph.update_calls if c[1] == "Human"]
    assert len(resume) == 1
    assert resume[0][0]["messages"][0]["content"] == "answer"


def test_get_sessions(client: TestClient):
    r = client.get("/sessions")
    assert r.status_code == 200
    data = r.json()
    assert "sessions" in data
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["thread_id"] == "t1"


def test_get_session_history(client: TestClient, fake_graph: FakeGraph):
    fake_graph.set_snapshot({"messages": [{"role": "Gemini", "content": "hello"}], "session_name": "S1"})
    r = client.get("/session/t1/history")
    assert r.status_code == 200
    data = r.json()
    assert data["session_name"] == "S1"
    assert len(data["messages"]) == 1
    assert data["messages"][0]["content"] == "hello"


def test_get_session_history_empty(client: TestClient, fake_graph: FakeGraph):
    fake_graph.set_snapshot({})
    r = client.get("/session/t2/history")
    assert r.status_code == 200
    data = r.json()
    assert data["messages"] == []
    assert data["session_name"] is None
