import asyncio
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
import main

async def run():
    config = {"configurable": {"thread_id": "test_bug_3"}}
    
    print("starting invoke")
    try:
        main.graph.invoke(
            {"messages": [{"role": "Human", "content": "Topic: short test. Start conversation."}], "paused": False},
            config
        )
    except Exception as e:
        print("invoke failed", e)
    
    print("starting stream")
    try:
        async for e in main.graph.astream(None, config, stream_mode="updates"):
            print("streamed:", e)
    except Exception as e:
        print("astream failed:", type(e), e)

if __name__ == "__main__":
    asyncio.run(run())
