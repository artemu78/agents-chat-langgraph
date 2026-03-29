import asyncio
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from typing import TypedDict, Annotated, List, Literal
import operator
from langgraph.checkpoint.memory import MemorySaver

class State(TypedDict):
    val: str

def A(state):
    interrupt("Wait here")
    return {"val": "A"}

builder = StateGraph(State)
builder.add_node("A", A)
builder.add_edge(START, "A")
builder.add_edge("A", END)
graph = builder.compile(checkpointer=MemorySaver())

async def run():
    config = {"configurable": {"thread_id": "test_bug_6"}}
    try:
        res = graph.invoke({"val": "init"}, config)
        print("invoke returned:", res)
    except Exception as e:
        print("invoke exception:", type(e))

if __name__ == "__main__":
    asyncio.run(run())
