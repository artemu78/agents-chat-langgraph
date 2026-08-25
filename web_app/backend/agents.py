from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from models import GEMINI_MODEL, OPENAI_MODEL, build_chat_model
from tools import web_search_tool


def _coerce_message(message) -> BaseMessage:
    if isinstance(message, BaseMessage):
        return message
    if isinstance(message, dict):
        role = message.get("role", "Human")
        content = message.get("content", "")
        if role == "Human":
            return HumanMessage(content=content)
        if role in {"AI", "Assistant", "Gemini", "OpenAI", "Orchestrator"}:
            return AIMessage(content=content)
        return HumanMessage(content=content)
    return HumanMessage(content=str(message))


def create_participant_agent(provider: str, participant_name: str, system_prompt: str):
    model_name = GEMINI_MODEL if provider == "gemini" else OPENAI_MODEL
    model = build_chat_model(provider, model_name)
    return create_agent(model, [web_search_tool], system_prompt=system_prompt, name=participant_name)


def finalize_agent_message(message: BaseMessage, participant_name: str) -> AIMessage:
    if isinstance(message, AIMessage):
        message.name = participant_name
        return message
    return AIMessage(content=message.content, name=participant_name)


def build_agent_input(state, system_prompt: str) -> list[BaseMessage]:
    return [SystemMessage(content=system_prompt), *[_coerce_message(message) for message in state.get("messages", [])]]
