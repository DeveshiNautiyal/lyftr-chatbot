import logging
import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import load_settings
from .db import Database
from .llm import AllProvidersUnavailable, Gateway, parse_failure_header
from .schemas import ChatRequest

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")


def create_app(settings=None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="LLM Chatbot", docs_url="/docs")
    db = Database(settings.db_path)
    gateway = Gateway(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse({"detail": "internal server error"}, status_code=500)

    @app.get("/health")
    def health():
        try:
            db.ping()
        except Exception:
            raise HTTPException(503, "database unreachable")
        if not gateway.keys:
            raise HTTPException(503, "no api keys configured")
        return {"status": "ok", "keys_configured": len(gateway.keys), "cache_enabled": settings.cache_enabled}

    @app.post("/chat")
    def chat(body: ChatRequest, x_simulate_failure: str | None = Header(default=None)):
        started = time.perf_counter()
        rules = parse_failure_header(x_simulate_failure) if settings.enable_failure_simulation else {}

        stored_prompt = db.get_system_prompt(body.session_id)
        system_prompt = body.system_prompt or stored_prompt or settings.default_system_prompt
        messages = [{"role": "system", "content": system_prompt}]
        messages += [{"role": m["role"], "content": m["content"]} for m in db.history(body.session_id)]
        messages.append({"role": "user", "content": body.message})

        try:
            result = gateway.complete(messages, rules)
        except AllProvidersUnavailable:
            # Nothing is written to history on failure.
            return JSONResponse({"detail": "all providers unavailable"}, status_code=503)

        metadata = {
            "resolution_source": "LLM_CACHE" if result.cache_hit else "LIVE_INFERENCE",
            "model": result.model,
            "latency_ms": 0,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "key_id": result.key_id,
            "fallback_attempts": result.fallback_attempts,
        }
        metadata["latency_ms"] = max(0, int((time.perf_counter() - started) * 1000))
        db.save_exchange(body.session_id, body.system_prompt, body.message, result.reply, metadata)
        return {"session_id": body.session_id, "reply": result.reply, "metadata": metadata}

    @app.get("/sessions/{session_id}/messages")
    def messages(session_id: str):
        if not db.session_exists(session_id):
            raise HTTPException(404, "session not found")
        return {"session_id": session_id, "messages": db.history(session_id)}

    return app
