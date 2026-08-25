from __future__ import annotations

from typing import Annotated, Literal, NotRequired, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class OrchestratorDecision(BaseModel):
    message: str = Field(...)
    action: Literal["delegate", "ask_human", "conclude"] = Field(...)
    next_hat: Literal["White", "Red", "Black", "Yellow", "Green"] | None = None
    next_model: Literal["Gemini", "OpenAI"] | None = None

    def validate(self) -> None:
        if self.action == "delegate":
            if self.next_hat is None or self.next_model is None:
                raise ValueError("delegate requires next_hat and next_model")
        elif self.action == "ask_human":
            if self.next_hat is not None or self.next_model is not None:
                raise ValueError("ask_human must not specify routing targets")


class GraphState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    paused: bool
    is_asking: bool
    user_id: NotRequired[str]
    session_name: NotRequired[str]
    current_hat: NotRequired[str]
    clarification_question: NotRequired[str]
    orchestrator_decision: NotRequired[dict]
    last_participant: NotRequired[str]
    step_count: NotRequired[int]
