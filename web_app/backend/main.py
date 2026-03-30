import os
import json
import asyncio
import logging
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from pydantic import BaseModel
import firebase_admin
from firebase_admin import auth, credentials

from debug_tracing import is_backend_debug, enable_debug_tracing, DebugRequestTimingMiddleware

if is_backend_debug():
    enable_debug_tracing()

_debug_log = logging.getLogger("nebula.debug")


def _trace(msg: str, *args: object) -> None:
    if is_backend_debug():
        _debug_log.info(msg, *args)

from langgraph.errors import GraphInterrupt

from graph import create_graph, generate_session_name
from persistence import DynamoDBSaver, save_user_session, list_user_sessions
from langgraph.checkpoint.memory import MemorySaver

app = FastAPI(title="AI Chat Nebula Glass API")
API_VERSION = "2.15.1"

# ... (skipped some parts for brevity in replace call, but I will include them in old_string/new_string)

# --- Attachment Processor ---
def _process_attachments(text: str) -> str:
    if not text or "@" not in text:
        return text
    
    import re
    # Match @ followed by non-space characters
    pattern = r'@([^\s]+)'
    matches = re.finditer(pattern, text)
    
    # Track position and final text
    last_pos = 0
    new_text = ""
    
    # Try to resolve files relative to workspace root (parent of web_app/backend)
    workspace_root = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    
    for match in matches:
        file_path = match.group(1)
        # Add text before the match
        new_text += text[last_pos:match.start()]
        last_pos = match.end()
        
        # Try finding the file
        possible_paths = [
            os.path.join(workspace_root, file_path), # Relative to workspace
            os.path.join(os.getcwd(), file_path), # Relative to CWD
            file_path # Absolute
        ]
        
        content = None
        found_path = None
        for p in possible_paths:
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        content = f.read()
                        found_path = p
                        break
                except Exception:
                    continue
        
        if content is not None:
            new_text += f"\n[ATTACHED FILE: {file_path}]\n{content}\n[END OF ATTACHMENT]\n"
        else:
            # Keep original text if file not found
            new_text += f"@{file_path}"
            
    new_text += text[last_pos:]
    return new_text.strip()

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if is_backend_debug():
    app.add_middleware(DebugRequestTimingMiddleware)

# --- Firebase Init ---
def init_firebase():
    try:
        firebase_admin.get_app()
        return "Already initialized"
    except ValueError:
        creds_json = os.getenv("FIREBASE_CREDENTIALS")
        # Look for the file in the same directory as this script
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firebase-credentials.json")
        
        try:
            if creds_json and len(creds_json.strip()) > 10:
                creds_dict = json.loads(creds_json)
                # Fix escaped newlines in the private key if they exist
                if "private_key" in creds_dict:
                    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
                
                cred = credentials.Certificate(creds_dict)
                firebase_admin.initialize_app(cred)
                return "Initialized from environment variable"
            elif os.path.exists(file_path):
                cred = credentials.Certificate(file_path)
                firebase_admin.initialize_app(cred)
                return "Initialized from local file"
            else:
                return f"Error: No credentials found. Env empty, File exists: {os.path.exists(file_path)} at {file_path}"
        except Exception as e:
            return f"Error during init: {str(e)}"

# Call it once at startup
init_status = init_firebase()
print(f"Firebase Status: {init_status}")

# --- Persistence ---
TABLE_NAME = os.getenv("DYNAMODB_TABLE", "AI_Chat_Sessions")
checkpointer = MemorySaver() # Default fallback for local dev
if os.getenv("AWS_LAMBDA_FUNCTION_NAME") or os.getenv("USE_DYNAMODB"):
    checkpointer = DynamoDBSaver(table_name=TABLE_NAME)

graph = create_graph(checkpointer=checkpointer)

# --- Schemas ---
class ChatInput(BaseModel):
    thread_id: str
    content: Optional[str] = None
    seed_topic: Optional[str] = None
    paused: Optional[bool] = None

# --- Auth Dependency ---
def _is_dev_mode() -> bool:
    return bool(os.getenv("DEV_MODE", "").strip())


async def get_current_user(request: Request):
    if _is_dev_mode():
        return {"uid": "dev_user"}

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = auth_header.split(" ")[1]

    status = init_firebase()
    if "Error" in status:
        raise HTTPException(status_code=401, detail=f"Firebase Init Error: {status}")

    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        print(f"Firebase Token Error v3: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Invalid token v3: {str(e)}")

# --- Endpoints ---


@app.get("/user/tokens")
async def get_tokens(user=Depends(get_current_user)):
    from persistence import get_user_tokens
    used = get_user_tokens(user["uid"])
    return {"tokens_used": used, "limit": 500000}

@app.get("/sessions")
async def get_sessions(user=Depends(get_current_user)):
    sessions = list_user_sessions(user["uid"])
    return {"sessions": sessions}

@app.get("/session/{thread_id}/history")
async def get_session_history(thread_id: str, user=Depends(get_current_user)):
    config = {"configurable": {"thread_id": thread_id}}
    state = await asyncio.to_thread(graph.get_state, config)
    if not state.values:
        return {"messages": [], "session_name": None}
    
    return {
        "messages": state.values.get("messages", []),
        "session_name": state.values.get("session_name"),
        "paused": state.values.get("paused", False),
        "is_asking": state.values.get("is_asking", False)
    }

@app.get("/")
def read_root():
    out = {"status": "Nebula Glass API is running", "version": API_VERSION}
    if is_backend_debug():
        out["debug"] = True
    return out

@app.post("/session")
async def create_session(chat_input: ChatInput, user=Depends(get_current_user)):
    # Initialize a new session or return existing thread_id
    thread_id = chat_input.thread_id
    # You could also generate a UUID if thread_id is empty
    return {"thread_id": thread_id}

@app.get("/chat/stream")
async def chat_stream(thread_id: str, request: Request):
    # SSE Endpoint
    config = {"configurable": {"thread_id": thread_id}}
    
    async def event_generator():
        # Check if the graph is currently interrupted (waiting for human)
        state = await asyncio.to_thread(graph.get_state, config)
        
        # If no state, we need a seed topic to start
        if not state.values:
            # This is handled by a different flow or we expect first message
            yield f"data: {json.dumps({'type': 'error', 'content': 'No state found. Please start with a topic.'})}\n\n"
            return

        # Stream graph updates
        try:
            # We use asyncio.to_thread because LangGraph's stream is synchronous in some versions
            # or we use the async version if available.
            async for event in graph.astream(None, config, stream_mode="updates"):
                if await request.is_disconnected():
                    break
                
                # Format event for SSE
                # Each event represents a node finishing
                for node_name, updates in event.items():
                    if node_name == "__interrupt__":
                        yield f"data: {json.dumps({'type': 'interrupt', 'content': 'AI is waiting for clarification'})}\n\n"
                        continue

                    if "messages" in updates:
                        last_msg = updates["messages"][-1]
                        yield f"data: {json.dumps({'type': 'message', 'node': node_name, 'content': last_msg['content'], 'role': last_msg['role']})}\n\n"
                    
                    if isinstance(updates, dict) and updates.get("is_asking"):
                        yield f"data: {json.dumps({'type': 'interrupt', 'content': 'AI is waiting for clarification'})}\n\n"
                    
                    # If the graph just paused itself because state["paused"] was True
                    # the router will point to END, and loop will finish.

            yield "data: [DONE]\n\n"
        except Exception as e:
            # Important: log the exception so it appears in CloudWatch
            _debug_log.exception("Error in event_generator: %s", str(e))
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/chat/input")
async def post_input(chat_input: ChatInput, user=Depends(get_current_user)):
    config = {"configurable": {"thread_id": chat_input.thread_id}}
    _trace(
        "post_input: thread_id=%s seed_topic=%r content=%r paused=%r",
        chat_input.thread_id,
        chat_input.seed_topic,
        (chat_input.content[:80] + "…") if chat_input.content and len(chat_input.content) > 80 else chat_input.content,
        chat_input.paused,
    )

    if chat_input.paused is not None:
        _trace("post_input: graph.update_state(paused=%s)", chat_input.paused)
        await asyncio.to_thread(graph.update_state, config, {"paused": chat_input.paused})
        if not chat_input.paused:
            # If unpausing, we might want to trigger the graph to continue
            # The frontend should call /chat/stream right after this
            pass

    if chat_input.seed_topic:
        processed_topic = _process_attachments(chat_input.seed_topic)
        # Start a new conversation by updating state. Graph will run when /chat/stream calls astream
        session_name = await asyncio.to_thread(generate_session_name, chat_input.seed_topic, user["uid"])
        # Save session metadata
        save_user_session(user["uid"], chat_input.thread_id, session_name)
        
        initial_state = {
            "messages": [{"role": "Human", "content": f"Topic: {processed_topic}. Start conversation."}], 
            "paused": False, 
            "user_id": user["uid"],
            "session_name": session_name
        }
        _trace("post_input: graph.update_state(initial_state) starting")
        await asyncio.to_thread(graph.update_state, config, initial_state)
        _trace("post_input: graph.update_state finished")
        return {"status": "started", "session_name": session_name}
    
    if chat_input.content:
        processed_content = _process_attachments(chat_input.content)
        # Resume with human input by updating state as Human node
        _trace("post_input: graph.get_state")
        state = await asyncio.to_thread(graph.get_state, config)
        
        # Update session metadata to bump timestamp
        session_name = state.values.get("session_name") if state.values else None
        if not session_name:
            session_name = f"Chat: {chat_input.content[:15]}..."
        save_user_session(user["uid"], chat_input.thread_id, session_name)

        if state.next:
            # Since we used interrupt() in human_node:
            _trace("post_input: graph.update_state (resume from interrupt)")
            await asyncio.to_thread(graph.update_state, config, {"messages": [{"role": "Human", "content": processed_content}], "paused": False, "user_id": user["uid"]}, as_node="Human")
            return {"status": "resumed"}
            
    return {"status": "updated"}

# --- Lambda Handler ---
handler = Mangum(app)
