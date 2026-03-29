# Nebula Glass — multi-participant AI chat

Web app where **several LLM agents and a human** share **one conversation thread**. The product direction is a **single chat** where every participant can see the full context: models address each other explicitly, human clarifications are labeled, and the UI streams turns in real time.

**Codename / UI:** “Nebula Glass” / “Nebula Chat”.

---

## Product goal

- **Shared thread:** One `thread_id` holds the full message history for Gemini, OpenAI, the human, and system notices.
- **Mutual awareness:** Backend prompts and `format_history()` prefix peer messages (e.g. `[OpenAI]: …`, `[CLARIFICATION FROM HUMAN]: …`) so each model is steered to treat others as present in the same room.
- **Human in the loop:** Models can ask for help with the `[ASK]` marker; the graph routes to a **Human** node that uses LangGraph **`interrupt()`** so the API can accept clarification and resume.
- **Watch and steer:** The human can start a topic, watch the autonomous back-and-forth, pause/resume, and send messages when the graph is waiting or when steering (same input path after the first message).

**Current scope:** The orchestration graph is **two providers** (Gemini + OpenAI) plus **Human**. Extending to *N* models would mean new nodes, router rules, and UI labels — update this README when that architecture changes.

---

## Repository layout

| Path | Role |
|------|------|
| `web_app/backend/` | FastAPI app, LangGraph definition, DynamoDB checkpointer, Lambda handler |
| `web_app/frontend/` | Vite + React SPA (Firebase Auth, SSE client) |
| `GEMINI.md` | Project conventions (e.g. Python `API_VERSION` bump in `main.py`) |

---

## Backend (`web_app/backend/`)

### Stack

- **FastAPI** — HTTP API and SSE stream.
- **LangGraph** — `StateGraph` with nodes `Gemini`, `OpenAI`, `Human`; conditional routing after each node.
- **State** (`graph.py` — `State` `TypedDict`):
  - `messages`: append-only list of `{ "role", "content" }` with roles `Human`, `Gemini`, `OpenAI`, `System`.
  - `paused`: when `True`, router returns **END** (conversation stops until unpaused via API).
  - `is_asking`: set by nodes when `[ASK]` appears in model output (used for SSE `interrupt` events).
- **Persistence:** Optional **`DynamoDBSaver`** (`persistence.py`) — LangGraph checkpointer storing checkpoints (and writes) in DynamoDB when `AWS_LAMBDA_FUNCTION_NAME` or `USE_DYNAMODB` is set. Set **`DYNAMODB_ENDPOINT_URL`** (or `AWS_ENDPOINT_URL_DYNAMODB`) to use **DynamoDB Local** instead of AWS. Local/dev without DynamoDB uses in-memory graph state only.
- **AWS SAM** (`template.yaml`) — HTTP API → Lambda (`main.handler` via **Mangum**), table `AI_Chat_Sessions` (keys `thread_id`, `checkpoint_id`).

### Conversation flow (high level)

1. **START** → always enters **Gemini** first.
2. **Router** (`router`):
   - If `paused` → **END**.
   - If last message contains `[ASK]` → **Human** (interrupt → wait for POST `/chat/input` with `content`).
   - If last role is **Human** → route to the *other* model than the one who spoke before the human turn.
   - Otherwise alternate **Gemini** ↔ **OpenAI** based on last speaker.

3. **Human node** calls `interrupt(...)`; resume path in `main.py` uses `update_state(..., as_node="Human")` then `invoke(None, config)`.

### HTTP API (authoritative list: `main.py`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/` | No | Health; returns `API_VERSION`. |
| `POST` | `/session` | Bearer (Firebase) or `DEV_MODE` | Acknowledges `thread_id` (placeholder for session creation). |
| `GET` | `/chat/stream?thread_id=…` | No (today) | **SSE:** streams graph `astream` updates as JSON lines (`type`: `message` \| `interrupt` \| `error`), then `[DONE]`. |
| `POST` | `/chat/input` | Bearer or `DEV_MODE` | `seed_topic` — seeds first message and starts graph; `content` — human reply / resume; `paused` — bool to pause or resume. |

**SSE payload shapes (conceptual):**

- `message` — `node`, `role`, `content` (last message from that graph step).
- `interrupt` — human clarification required.
- `error` — failure or “no state” (e.g. stream without prior seed).

### Environment variables

| Variable | Used for |
|----------|-----------|
| `GEMINI_API_KEY` | Google GenAI client (`graph.py`) |
| `OPENAI_API_KEY` | OpenAI client |
| `FIREBASE_CREDENTIALS` | JSON string of Firebase service account (Lambda) |
| Local file | `firebase-credentials.json` next to `main.py` as fallback |
| `DEV_MODE` | If set, auth bypass with `uid: dev_user` |
| `DYNAMODB_TABLE` | Table name (default `AI_Chat_Sessions`) |
| `DYNAMODB_ENDPOINT_URL` | Optional; DynamoDB API endpoint (e.g. `http://localhost:8000` for Uvicorn, `http://host.docker.internal:8000` for SAM Local → host) |
| `AWS_ENDPOINT_URL_DYNAMODB` | Optional; same intent as `DYNAMODB_ENDPOINT_URL` (AWS SDK–style) |
| `USE_DYNAMODB` | Force DynamoDB checkpointer locally |
| `AWS_LAMBDA_FUNCTION_NAME` | Set in Lambda; enables DynamoDB saver |

### Python dependencies

See `web_app/backend/requirements.txt` (FastAPI, uvicorn, mangum, langgraph, google-genai, openai, boto3, firebase-admin, etc.).

### API versioning

Any change to Python under `web_app/backend/` should bump `API_VERSION` in `main.py` per `GEMINI.md` / Cursor rule `bump-api-version-on-python-changes`.

---

## Frontend (`web_app/frontend/`)

### Stack

- **Vite 8** + **React 19** + TypeScript.
- **Firebase Auth** (Google popup) — `src/firebase.ts`; env prefix `VITE_FIREBASE_*`.
- **SSE** — `EventSource` to `GET /chat/stream?thread_id=…` (`src/hooks/useSSE.ts`). Note: browser `EventSource` does not send `Authorization` headers; stream endpoint is currently unauthenticated while POST routes use Bearer tokens.

### Behavior

- On login, builds a client `thread_id` like `session_<uidPrefix>_<timestamp>`.
- **Seed topic:** POST `/chat/input` with `seed_topic`, then opens SSE stream.
- **After messages exist:** same input sends `content` (clarification / steering); optimistic append for human line on send.
- **Pause:** POST `paused: true/false`; stops or restarts stream when unpausing.
- **Base path:** `vite.config.ts` sets `base: '/agents-chat-langgraph/'` for deployment under a subpath.

### Frontend env

| Variable | Purpose |
|----------|---------|
| `VITE_API_URL` | Backend origin (default `http://localhost:8000`) |
| `VITE_FIREBASE_*` | Firebase web app config |

---

## Local development (typical)

**Backend** (from `web_app/backend/`):

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=... OPENAI_API_KEY=...
# Optional: export DEV_MODE=1 for auth bypass
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend** (from `web_app/frontend/`):

```bash
npm install
echo 'VITE_API_URL=http://localhost:8000' > .env.local  # plus Firebase vars
npm run dev
```

Firebase: configure client env vars; for secured POST routes, sign in with Google. For local-only testing, enable `DEV_MODE` on the API.

### Full local stack (SAM + DynamoDB Local)

Runs the **same Lambda handler** (FastAPI + Mangum) in Docker and talks to **DynamoDB Local** on your machine. Requires **Docker** (for DynamoDB Local and SAM’s Lambda container), **AWS SAM CLI**, and **AWS CLI**.

1. From `web_app/backend/`, start DynamoDB Local:

   ```bash
   docker compose -f docker-compose.local.yml up -d
   ```

2. Create the table once (matches [`web_app/backend/template.yaml`](web_app/backend/template.yaml); idempotent):

   ```bash
   ./scripts/init-local-dynamodb.sh
   ```

3. Copy [`web_app/backend/sam-local-env.json.example`](web_app/backend/sam-local-env.json.example) to **`sam-local-env.json`** (gitignored), set `GEMINI_API_KEY` and `OPENAI_API_KEY`, and optionally set `FIREBASE_CREDENTIALS` to a compact JSON string, e.g. `jq -c . < firebase-credentials.json`. With `DEV_MODE` set to `1`, POST routes work without Firebase tokens.

4. **`DYNAMODB_ENDPOINT_URL`** in that file must reach DynamoDB from **inside** the Lambda container: use **`http://host.docker.internal:8000`** on macOS and Windows (Docker Desktop). On Linux, if `host.docker.internal` is missing, try `http://172.17.0.1:8000` or configure Docker’s `host-gateway`.

5. Build and start the local API:

   ```bash
   sam build
   sam local start-api --env-vars sam-local-env.json
   ```

   SAM prints a local URL (often port 3000). Point the frontend’s `VITE_API_URL` at that origin for an end-to-end test.

**Uvicorn + DynamoDB Local:** You can also run `uvicorn main:app --reload` with `USE_DYNAMODB=1` and `DYNAMODB_ENDPOINT_URL=http://localhost:8000` (no `host.docker.internal` needed).

**Advanced:** Omit `DYNAMODB_ENDPOINT_URL` and use a **real** table in AWS (credentials on the host) if you only want SAM Local without DynamoDB Local.

---

## Deployment notes

- **SAM:** `web_app/backend/template.yaml` — package parameters for Gemini, OpenAI, Firebase credentials JSON; DynamoDB table name `AI_Chat_Sessions`.
- **CORS:** `allow_origins=["*"]` in `main.py` — tighten for production.
- **Frontend:** build with `npm run build`; serve static assets consistent with `base` path.

---

## Maintenance for agents

- **Architecture** (new nodes, persistence, auth on SSE, multi-model, routing): update **this README** in the same change. See Cursor rule **readme-architecture-sync**.
- **Backend Python behavior or public API:** bump **`API_VERSION`** in `web_app/backend/main.py` per project rules.

---

## Key source files

- `web_app/backend/main.py` — FastAPI routes, SSE, auth, graph wiring, Mangum handler.
- `web_app/backend/graph.py` — Models, state, `format_history`, router, `create_graph`.
- `web_app/backend/persistence.py` — `DynamoDBSaver` for LangGraph.
- `web_app/frontend/src/App.tsx` — Main UI and API calls.
- `web_app/frontend/src/hooks/useSSE.ts` — SSE parsing and message list.
