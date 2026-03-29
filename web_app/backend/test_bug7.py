import asyncio
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated, List, Literal
import operator
from langgraph.checkpoint.memory import MemorySaver

class State(TypedDict):
    val: str

def A(state):
    print("Executing A")
    return {"val": "A"}

builder = StateGraph(State)
builder.add_node("A", A)
builder.add_edge(START, "A")
builder.add_edge("A", END)
graph = builder.compile(checkpointer=MemorySaver())

async def run():
    config = {"configurable": {"thread_id": "test_bug_7"}}
    graph.update_state(config, {"val": "init"})
    
    print("Calling astream(None)")
    async for e in graph.astream(None, config, stream_mode="updates"):
        print(e)

if __name__ == "__main__":
    asyncio.run(run())
