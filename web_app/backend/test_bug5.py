print("Started.")
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
    return {"messages": [{"role": "Gemini", "content": "hello"}], "is_asking": False}

def human_node(state):
    val = interrupt("Waiting for human...")
    return {"messages": [{"role": "Human", "content": val}], "is_asking": False}

def router(state) -> Literal["Gemini", "Human", "__end__"]:
    try:
        if len(state.get("messages", [])) > 2: return END
    except: pass
    return "Human"

builder = StateGraph(State)
builder.add_node("Gemini", gemini_node)
builder.add_node("Human", human_node)
builder.add_edge(START, "Gemini")
builder.add_conditional_edges("Gemini", router)
builder.add_conditional_edges("Human", router)
graph = builder.compile(checkpointer=MemorySaver())

async def run():
    print("In run()")
    config = {"configurable": {"thread_id": "test_bug_5"}}
    try:
        graph.invoke({"messages": [{"role": "Human", "content": "start"}], "paused": False}, config)
    except Exception as e:
        print("invoke interrupted?", type(e))
    
    try:
        async for e in graph.astream(None, config, stream_mode="updates"):
            print("streamed:", e)
            for node_name, updates in e.items():
                print(f"updates ({type(updates)}):", updates)
    except Exception as exc:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run())
