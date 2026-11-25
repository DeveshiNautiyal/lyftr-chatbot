# LLM Chatbot with Key Failover and Response Caching

React + FastAPI + LiteLLM + SQLite. Multi-turn chat where every reply shows whether it came from the cache or a live call, which model/key answered, latency, and per-request tokens.

## 1. Live URLs

- Frontend: `<add after deploy>`
- Backend: `<add after deploy>` (try `/health` and `/docs`)

## 2. Run locally

**With Docker**

```bash
cp .env.example .env     # put 2+ real keys in LLM_API_KEYS
make up                  # frontend http://localhost:3000, backend http://localhost:8000
make down
```

**Without Docker**

```bash
# backend
cd backend && pip install -r requirements.txt
cp ../.env.example .env && export $(grep -v '^#' .env | xargs)
export DATABASE_URL=sqlite:///./app.db
uvicorn app.asgi:app --port 8000

# frontend (new terminal)
cd frontend && npm install && VITE_API_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

Tests (no network or keys needed; the provider is mocked through LiteLLM's `mock_response`): `cd backend && python -m pytest -q`

**Deploy** (Render example, see `render.yaml`): create the backend as a Docker web service from `backend/`, set `LLM_API_KEYS`, `ENABLE_FAILURE_SIMULATION=true` and `ALLOWED_ORIGINS=<frontend url>`. Create the frontend as a static site from `frontend/` with `VITE_API_URL=<backend url>` (build-time variable, so redeploy the frontend after changing it). Without a persistent disk mounted at `/data`, SQLite history resets on redeploy; attach a disk (or use Fly.io volumes) to keep it.

## 3. Design decisions

- **Key fallback.** `LLM_API_KEYS` is parsed into `key_1..key_n`. For each request the gateway tries keys in order and calls `litellm.completion(api_key=...)` with `num_retries=0`. Any failure (429, quota, 5xx, auth, timeout) moves to the next key and increments `fallback_attempts`. If every key fails the API returns `503 {"detail":"all providers unavailable"}` and nothing is written to history. Keys are never returned or logged; only `key_N` ids are.
- **Failure simulation.** With `ENABLE_FAILURE_SIMULATION=true`, `X-Simulate-Failure` is parsed per request (`key_1=429,key_2=500` or `*=429`) and raises a simulated provider error for those keys before the LiteLLM call. It never touches shared state, so it only affects that request.
- **Caching.** LiteLLM's built-in in-memory cache (`litellm.cache = Cache(type="local")`) with `caching=True` per call. LiteLLM's cache key is built from the model and the full message list (system prompt + history + new message), and not from the API key, so a cache entry is shared across sessions and keys. `temperature=0` keeps answers stable. A cache hit is detected from `_hidden_params["cache_hit"]`, and it returns the identical reply, the stored token usage, `key_id: null` and `fallback_attempts: 0`. The cache is per process: it resets on restart and is not shared between instances.
- **SQLite sessions.** `messages` follows the required schema (plus an index on `session_id, id`) and a small `sessions` table stores the per-session system prompt. The client sends only the new message; the server rebuilds the prompt from SQLite. The user and assistant rows are written together only after a successful reply, so 422/503 requests leave no trace. Schema is created at startup; the file path comes from `DATABASE_URL` (WAL mode).
- **Tokens and latency.** Tokens come from the provider's `usage` for that single call (with a LiteLLM `token_counter` fallback if usage is missing). Latency is measured server-side across the whole request, including the DB reads, in integer milliseconds.
- **Errors.** Validation errors use FastAPI's 422 shape. A catch-all handler turns unexpected exceptions into JSON `{"detail": "internal server error"}`, never a stack trace or an HTML page.

## 4. Verification

```bash
B=http://localhost:8000
# live, then cache hit from a NEW session (same first message)
curl -s $B/chat -H 'content-type: application/json' -d '{"session_id":"a1","message":"What is the capital of France?"}'
curl -s $B/chat -H 'content-type: application/json' -d '{"session_id":"a2","message":"What is the capital of France?"}'   # LLM_CACHE, key_id null
# failover: key_2 answers, fallback_attempts = 1
curl -s $B/chat -H 'X-Simulate-Failure: key_1=429' -H 'content-type: application/json' -d '{"session_id":"a3","message":"Name a prime number"}'
# everything fails: 503, nothing stored
curl -si $B/chat -H 'X-Simulate-Failure: *=429' -H 'content-type: application/json' -d '{"session_id":"a4","message":"hello"}'
# history
curl -s $B/sessions/a1/messages
```

In the UI, open "Session settings" and pick a failure preset to demo failover. The pill on each reply is `LIVE_INFERENCE` (blue) or `LLM_CACHE` (green); input and output tokens are for that request only. To see a cache hit in the UI, send the same first message after reloading the page.

## 5. Setup Used

Claude (Anthropic) for scaffolding, code and tests; Python 3.12, FastAPI, LiteLLM 1.111, Vite + React 18, Docker.

## 6. Bonus features

- Per-session system prompt field in the UI (persisted per session).
- Failure-simulation dropdown in the UI so failover can be demoed without curl.
- `key_id` and `fallback_attempts` shown next to each reply.
- 11 backend tests covering cache, failover, 503 handling, validation, history isolation and CORS.
