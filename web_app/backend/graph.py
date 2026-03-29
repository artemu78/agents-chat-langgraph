from persistence import add_user_tokens, get_user_tokens
import os
import operator
from typing import Annotated, TypedDict, List, Literal, NotRequired
from google import genai
from openai import OpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

# --- Configuration ---
# Default to a widely available model; override with GEMINI_MODEL if needed.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
OPENAI_MODEL = "gpt-4o" # Updated to a more standard model for broader compatibility

# --- State Definition ---
class State(TypedDict):
    messages: Annotated[List[dict], operator.add]
    paused: bool
    is_asking: bool
    user_id: NotRequired[str]
    session_name: NotRequired[str]

def format_history(messages: List[dict], target_role_map: dict) -> List[dict]:
    history = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "Human":
            display_content = f"[CLARIFICATION FROM HUMAN]: {content}"
        elif role in ["Gemini", "OpenAI"] and role != target_role_map["self"]:
            display_content = f"[{role}]: {content}"
        else:
            display_content = content
        mapped_role = target_role_map.get(role, "user")
        if "gemini" in target_role_map:
            history.append({"role": mapped_role, "parts": [{"text": display_content}]})
        else:
            history.append({"role": mapped_role, "content": display_content})
    return history

def generate_session_name(topic: str, user_id: str) -> str:
    try:
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        prompt = f"Summarize this topic into a short 3-5 words session name. Do not include quotes or punctuation at the end. Topic: {topic}"
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        text = response.text.strip()
        try:
            tokens = response.usage_metadata.candidates_token_count
        except Exception:
            tokens = len(text.split())
        add_user_tokens(user_id, tokens)
        return text
    except Exception:
        return f"Chat: {topic[:15]}..."

# --- Nodes ---
def gemini_node(state: State):
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    role_map = {"self": "Gemini", "Gemini": "model", "gemini": True}
    history = format_history(state["messages"], role_map)
    sys_instr = "You are Gemini, the Visionary Architect, talking to GPT. Your role is to propose innovative, high-level solutions and creative approaches to the topic. Use '[ASK]' for human clarification. Be concise but visionary."
    try:
        full_contents = [{"role": "user", "parts": [{"text": sys_instr}]}] + history
        response = client.models.generate_content(model=GEMINI_MODEL, contents=full_contents)
        text = response.text.strip()
        
        user_id = state.get("user_id", "anonymous")
        try:
            tokens = response.usage_metadata.candidates_token_count
        except Exception:
            tokens = len(text.split())
        add_user_tokens(user_id, tokens)
        
        return {"messages": [{"role": "Gemini", "content": text}], "is_asking": "[ASK]" in text}
    except Exception as e:
        return {"messages": [{"role": "System", "content": f"Gemini Error: {e}"}]}

def openai_node(state: State):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    role_map = {"self": "OpenAI", "OpenAI": "assistant"}
    history = format_history(state["messages"], role_map)
    sys_msg = {"role": "system", "content": "You are GPT, the Security & Logic Auditor, talking to Gemini. Your role is to critically analyze Gemini's proposals, find edge cases, and propose optimizations. You MUST wrap your analysis inside <audit>...</audit> tags. Use '[ASK]' for human clarification. Be concise and analytical."}
    try:
        response = client.chat.completions.create(model=OPENAI_MODEL, messages=[sys_msg] + history)
        text = response.choices[0].message.content.strip()
        
        user_id = state.get("user_id", "anonymous")
        try:
            tokens = response.usage.completion_tokens
        except Exception:
            tokens = len(text.split())
        add_user_tokens(user_id, tokens)
        
        return {"messages": [{"role": "OpenAI", "content": text}], "is_asking": "[ASK]" in text}
    except Exception as e:
        return {"messages": [{"role": "System", "content": f"OpenAI Error: {e}"}]}

def human_node(state: State):
    # Use LangGraph interrupt for human input
    human_input = interrupt("Waiting for human clarification...")
    return {"messages": [{"role": "Human", "content": human_input}], "is_asking": False}


def limit_reached_node(state: State):
    return {"messages": [{"role": "System", "content": "Token limit reached. Input blocked."}], "paused": True}

# --- Router ---
def router(state: State) -> Literal["Gemini", "OpenAI", "Human", "LimitReached", "__end__"]:
    # Check if we should pause (e.g., between turns)
    # The 'paused' state can be set via update_state from the API
    if state.get("paused", False):
        return END

    user_id = state.get("user_id", "anonymous")
    if get_user_tokens(user_id) >= 500000:
        # If limit reached, we want to stop and show error
        # Since router doesn't mutate state, we must route to a new node that emits the error,
        # but we don't have one. Instead, we can route to END, and the frontend will just see no more messages.
        # Let's route to a special node that returns the error message
        return "LimitReached" 

    last_msg = state["messages"][-1]
    # Error messages from nodes use role "System"; do not re-enter Gemini/OpenAI or we loop forever on API failures.
    if last_msg["role"] == "System":
        return END

    if "[ASK]" in last_msg["content"]: 
        return "Human"
    
    if last_msg["role"] == "Human":
        # Find who Gemini/OpenAI was talking to
        for i in range(len(state["messages"]) - 2, -1, -1):
            if state["messages"][i]["role"] == "Gemini":
                return "OpenAI"
            if state["messages"][i]["role"] == "OpenAI":
                return "Gemini"
        return "Gemini" # Default

    return "OpenAI" if last_msg["role"] == "Gemini" else "Gemini"

# --- Graph ---
def create_graph(checkpointer=None):
    builder = StateGraph(State)
    builder.add_node("Gemini", gemini_node)
    builder.add_node("OpenAI", openai_node)
    builder.add_node("Human", human_node)
    builder.add_node("LimitReached", limit_reached_node)
    builder.add_edge("LimitReached", END)
    builder.add_edge(START, "Gemini")
    builder.add_conditional_edges("Gemini", router)
    builder.add_conditional_edges("OpenAI", router)
    builder.add_conditional_edges("Human", router)
    return builder.compile(checkpointer=checkpointer)
