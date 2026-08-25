from __future__ import annotations

from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents import build_agent_input, create_participant_agent, finalize_agent_message
from models import GEMINI_MODEL, build_chat_model
from persistence import get_user_tokens
from state import GraphState, OrchestratorDecision
from usage import record_usage_from_messages

HATS = {
    "White": "Facts & Data: Focus strictly on information, available data, and neutral facts. What do we know?",
    "Red": "Emotions & Intuition: Share gut feelings and emotional reactions without needing justification.",
    "Black": "Caution & Risk: Logically identify potential obstacles, flaws, and risks. Why might this fail?",
    "Yellow": "Benefits & Value: Focus on the positive aspects, advantages, and why this will work.",
    "Green": "Creativity & Ideas: Propose alternatives, new possibilities, and creative solutions.",
    "Blue": "Orchestrator: Manage the thinking process, summarize findings, and decide which hat to use next.",
}


def generate_session_name(topic: str, user_id: str) -> str:
    clean_topic = (topic or "").strip() or "conversation"
    return f"Chat: {clean_topic[:15]}..."


def _run_agent(state: GraphState, participant_name: str, system_prompt: str, provider: str):
    agent = create_participant_agent(provider, participant_name, system_prompt)
    response = agent.invoke({"messages": build_agent_input(state, system_prompt)})
    output_messages = response.get("messages", []) if isinstance(response, dict) else []
    if not output_messages:
        raise RuntimeError(f"{participant_name} agent produced no output")
    final_message = finalize_agent_message(output_messages[-1], participant_name)
    user_id = state.get("user_id", "anonymous")
    record_usage_from_messages(user_id, [final_message])
    return final_message


def orchestrator_node(state: GraphState):
    current_hat = state.get("current_hat", "White")
    system_prompt = (
        "You are the Orchestrator (Blue Hat). Manage the Six Thinking Hats session. "
        "Use the web search tool when current facts are needed. Summarize progress and decide whether to delegate to Gemini/OpenAI, ask the human, or conclude."
    )
    final_message = _run_agent(state, "Orchestrator", system_prompt, "gemini")

    structured_model = build_chat_model("gemini", GEMINI_MODEL).with_structured_output(OrchestratorDecision)
    decision = structured_model.invoke([
        SystemMessage(
            content=(
                "Convert the orchestrator's response into a strict routing decision. "
                "Use delegate only if next_hat and next_model are both present. "
                "Use ask_human for clarification and conclude to end the session."
            )
        ),
        final_message,
    ])
    decision.validate()

    return {
        "messages": [final_message],
        "orchestrator_decision": decision.model_dump(),
        "last_participant": "Orchestrator",
        "current_hat": decision.next_hat or current_hat,
        "is_asking": False,
    }


def participant_node(state: GraphState, participant_name: str, provider: str):
    hat = state.get("current_hat", "Green")
    hat_desc = HATS.get(hat, HATS["Green"])
    system_prompt = (
        f"You are {participant_name}. You are currently wearing the {hat} Hat. {hat_desc}. "
        "Provide your answer from that perspective. Use the web search tool when needed. Do not route the graph."
    )
    final_message = _run_agent(state, participant_name, system_prompt, provider)
    return {
        "messages": [final_message],
        "last_participant": participant_name,
        "is_asking": False,
    }


def gemini_node(state: GraphState):
    return participant_node(state, "Gemini", "gemini")


def openai_node(state: GraphState):
    return participant_node(state, "OpenAI", "openai")


def human_node(state: GraphState):
    question = state.get("clarification_question") or "Please clarify the next step."
    human_input = interrupt(question)
    return {
        "messages": [HumanMessage(content=human_input)],
        "last_participant": "Human",
        "is_asking": False,
        "clarification_question": None,
    }


def limit_reached_node(state: GraphState):
    return {
        "messages": [AIMessage(content="Token limit reached. Input blocked.", name="System")],
        "paused": True,
        "is_asking": False,
    }


def _last_message_role(state: GraphState):
    messages = state.get("messages", []) or []
    if not messages:
        return None, None
    last = messages[-1]
    if isinstance(last, dict):
        return last.get("role"), last.get("content")
    if hasattr(last, "name") and last.name:
        return last.name, getattr(last, "content", "")
    return getattr(last, "type", None), getattr(last, "content", "")


def format_history(messages, target_role_map: dict):
    history = []
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role", "Human")
            content = msg.get("content", "")
        else:
            role = getattr(msg, "name", None) or getattr(msg, "type", "Human")
            content = getattr(msg, "content", "")
        if role == "Human":
            display_content = f"[CLARIFICATION FROM HUMAN]: {content}"
        elif role in ["Gemini", "OpenAI", "Orchestrator"] and role != target_role_map.get("self"):
            display_content = f"[{role}]: {content}"
        else:
            display_content = content
        mapped_role = target_role_map.get(role, "user")
        if "gemini" in target_role_map:
            history.append({"role": mapped_role, "parts": [{"text": display_content}]})
        else:
            history.append({"role": mapped_role, "content": display_content})
    return history


def router(state: GraphState) -> Literal["Gemini", "OpenAI", "Orchestrator", "Human", "LimitReached", "__end__"]:
    if state.get("paused", False):
        return END

    user_id = state.get("user_id", "anonymous")
    if get_user_tokens(user_id) >= 500_000:
        return "LimitReached"

    step_count = state.get("step_count", 0)
    if step_count >= 10:
        return END

    last_participant = state.get("last_participant")
    if last_participant in {"Gemini", "OpenAI", "Human"}:
        return "Orchestrator"

    decision = state.get("orchestrator_decision")
    if decision:
        action = decision.get("action")
        if action == "delegate":
            return decision.get("next_model") or "Gemini"
        if action == "ask_human":
            return "Human"
        return END

    role, content = _last_message_role(state)
    if role == "System":
        return END
    if isinstance(content, str) and "[ASK]" in content:
        return "Human"
    if isinstance(content, str) and "[SESSION CONCLUDED]" in content:
        return END

    messages = state.get("messages", []) or []
    last_message = messages[-1] if messages else None

    if role == "Human":
        prior_participant = None
        for message in reversed(messages[:-1]):
            if isinstance(message, dict):
                msg_role = message.get("role")
            else:
                msg_role = getattr(message, "name", None) or getattr(message, "type", None)
            if msg_role in {"Gemini", "OpenAI"}:
                prior_participant = msg_role
                break
        return "OpenAI" if prior_participant == "Gemini" else "Gemini"

    if role in {"Gemini", "OpenAI"}:
        if isinstance(last_message, BaseMessage) and getattr(last_message, "name", None) in {"Gemini", "OpenAI"}:
            return "Orchestrator"
        return "OpenAI" if role == "Gemini" else "Gemini"

    if role == "Orchestrator":
        import re
        match = re.search(r"\[NEXT: (White|Red|Black|Yellow|Green) Hat for (Gemini|OpenAI)\]", content or "")
        if match:
            return match.group(2)
        return "Gemini"
    return "Orchestrator"


def create_graph(checkpointer=None):
    builder = StateGraph(GraphState)
    builder.add_node("Orchestrator", orchestrator_node)
    builder.add_node("Gemini", gemini_node)
    builder.add_node("OpenAI", openai_node)
    builder.add_node("Human", human_node)
    builder.add_node("LimitReached", limit_reached_node)
    builder.add_edge("LimitReached", END)
    builder.add_edge(START, "Orchestrator")
    builder.add_conditional_edges("Orchestrator", router)
    builder.add_conditional_edges("Gemini", router)
    builder.add_conditional_edges("OpenAI", router)
    builder.add_conditional_edges("Human", router)
    return builder.compile(checkpointer=checkpointer)
