import asyncio
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from typing import TypedDict, Annotated, List, Literal
import operator
from langgraph.checkpoint.memory import MemorySaver

class State(TypedDict):
    messages: Annotated[List[dict], operator.add]
    paused: bool
    is_asking: bool

def gemini_node(state):
    return {"messages": [{"role": "Gemini", "content": "hello from gemini"}], "is_asking": False}

def openai_node(state):
    return {"messages": [{"role": "OpenAI", "content": "hello from openai"}], "is_asking": False}

def human_node(state):
    return {"messages": [{"role": "Human", "content": "human clarification"}], "is_asking": False}

def router(state) -> Literal["Gemini", "OpenAI", "Human", "__end__"]:
    if state.get("paused", False): return END
    last_msg = state["messages"][-1]
    if "[ASK]" in last_msg["content"]: return "Human"
    if last_msg["role"] == "Human": return "OpenAI"
    if len(state["messages"]) > 3: return END # stop after 3
    return "OpenAI" if last_msg["role"] == "Gemini" else "Gemini"

builder = StateGraph(State)
builder.add_node("Gemini", gemini_node)
builder.add_node("OpenAI", openai_node)
builder.add_node("Human", human_node)
builder.add_edge(START, "Gemini")
builder.add_conditional_edges("Gemini", router)
builder.add_conditional_edges("OpenAI", router)
builder.add_conditional_edges("Human", router)
graph = builder.compile(checkpointer=MemorySaver())

async def run():
    config = {"configurable": {"thread_id": "test_bug_4"}}
    
    print("starting invoke")
    graph.invoke({"messages": [{"role": "Human", "content": "start"}], "paused": False}, config)
    
    print("starting stream")
    try:
        async for e in graph.astream(None, config, stream_mode="updates"):
            print("streamed:", e)
            for node_name, updates in e.items():
                print("updates type:", type(updates))
                if updates.get("is_asking"):
                    print("asking")
    except Exception as exc:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run())
