import asyncio
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from typing import TypedDict, Annotated, List, Literal
import operator
from langgraph.checkpoint.memory import MemorySaver

class State(TypedDict):
    val: str

def A(state):
    print("Executing A")
    return {"val": "A"}

def H(state):
    interrupt("wait")
    print("Executing H")
    return {"val": "H"}

def R(state) -> Literal["A", "H", "__end__"]:
    return "A" if state["val"] == "H" else "H"

builder = StateGraph(State)
builder.add_node("A", A)
builder.add_node("H", H)
builder.add_edge(START, "A")
builder.add_conditional_edges("A", R)
builder.add_conditional_edges("H", R)
graph = builder.compile(checkpointer=MemorySaver())

async def run():
    config = {"configurable": {"thread_id": "test_bug_9"}}
    # 1. Update state (Start)
    graph.update_state(config, {"val": "init"})
    print("1. Stream after start:")
    async for e in graph.astream(None, config, stream_mode="updates"):
        print(" ->", e)
        
    # 2. Update state (Resume as Human node H)
    graph.update_state(config, {"val": "H"}, as_node="H")
    print("\n2. Stream after resume:")
    async for e in graph.astream(None, config, stream_mode="updates"):
        print(" ->", e)

if __name__ == "__main__":
    asyncio.run(run())
