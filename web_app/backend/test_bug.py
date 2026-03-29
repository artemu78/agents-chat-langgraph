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
    graph.invoke({"val": "init"}, config)
    print("Done invoke")
    try:
        async for e in graph.astream(None, config, stream_mode="updates"):
            print("Event:", e)
    except Exception as e:
        import traceback
        traceback.print_exc()
    print("Done astream")

if __name__ == "__main__":
    asyncio.run(main())
