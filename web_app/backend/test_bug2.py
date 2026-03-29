import asyncio
from typing import TypedDict, Annotated, operator
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

class State(TypedDict):
    val: str

def A(state: State):
    return {"val": state["val"] + "x"}

builder = StateGraph(State)
builder.add_node("A", A)
builder.add_edge(START, "A")
builder.add_edge("A", END)
checkpointer = MemorySaver()
graph = builder.compile(checkpointer=checkpointer)

async def main():
    config = {"configurable": {"thread_id": "1"}}
    # Simulate /chat/input:
    print("Invoke...")
    graph.invoke({"val": "init"}, config)
    
    print("Stream...")
    # Simulate /chat/stream:
    async for event in graph.astream(None, config, stream_mode="updates"):
        print("Event:", event)
        for node_name, updates in event.items():
            print("Updates type:", type(updates))
            if "messages" in updates:
                pass
            if updates.get("is_asking"):
                pass

if __name__ == "__main__":
    asyncio.run(main())
