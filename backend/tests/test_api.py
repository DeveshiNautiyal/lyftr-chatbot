import json
import sqlite3

import litellm
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def env(tmp_path):
    litellm.cache = None
    db = tmp_path / "t.db"
    s = Settings(
        llm_api_keys=["k-one", "k-two"],
        database_url=f"sqlite:///{db}",
        allowed_origins=["http://localhost:3000"],
        enable_failure_simulation=True,
        mock_llm=True,
    )
    return TestClient(create_app(s), raise_server_exceptions=False), db


def chat(c, sid, msg, headers=None, **extra):
    return c.post("/chat", json={"session_id": sid, "message": msg, **extra}, headers=headers or {})


def test_health(env):
    c, _ = env
    assert c.get("/health").json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_live_then_cache_across_sessions(env):
    c, _ = env
    a = chat(c, "s1", "What is the capital of France?").json()
    assert a["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert a["metadata"]["key_id"] == "key_1"
    assert a["metadata"]["fallback_attempts"] == 0
    b = chat(c, "s2", "What is the capital of France?").json()
    assert b["metadata"]["resolution_source"] == "LLM_CACHE"
    assert b["reply"] == a["reply"]
    assert b["metadata"]["key_id"] is None and b["metadata"]["fallback_attempts"] == 0
    assert b["metadata"]["input_tokens"] == a["metadata"]["input_tokens"]
    assert b["metadata"]["output_tokens"] == a["metadata"]["output_tokens"]
    assert isinstance(b["metadata"]["latency_ms"], int)


def test_different_message_not_cached(env):
    c, _ = env
    chat(c, "s1", "hello there")
    r = chat(c, "s2", "a completely different question").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_tokens_are_per_request_not_cumulative(env):
    c, _ = env
    r1 = chat(c, "a", "aaaa bbbb").json()["metadata"]["input_tokens"]
    chat(c, "b", "one two three four five six")
    r3 = chat(c, "c", "cccc dddd").json()["metadata"]["input_tokens"]
    assert abs(r1 - r3) <= 2
    # a later turn reports that request's usage only (never a running total)
    t2 = chat(c, "a", "eeee ffff").json()["metadata"]
    assert t2["input_tokens"] == r1 and t2["output_tokens"] > 0


def test_history_endpoint_and_isolation(env):
    c, db = env
    chat(c, "s1", "hi")
    chat(c, "s1", "again")
    chat(c, "s2", "other")
    h = c.get("/sessions/s1/messages").json()
    assert [m["role"] for m in h["messages"]] == ["user", "assistant", "user", "assistant"]
    assert "metadata" in h["messages"][1] and "resolution_source" in h["messages"][1]["metadata"]
    assert len(c.get("/sessions/s2/messages").json()["messages"]) == 2
    assert c.get("/sessions/nope/messages").status_code == 404
    assert c.get("/sessions/nope/messages").json() == {"detail": "session not found"}
    rows = sqlite3.connect(db).execute("select count(*) from messages where session_id='s1'").fetchone()[0]
    assert rows == 4


def test_history_is_sent_to_llm(env, monkeypatch):
    c, _ = env
    seen = []
    orig = litellm.completion

    def spy(**kw):
        seen.append(kw["messages"])
        return orig(**kw)

    monkeypatch.setattr(litellm, "completion", spy)
    chat(c, "s1", "my name is Ravi", system_prompt="Be terse.")
    chat(c, "s1", "what is my name?")
    last = seen[-1]
    assert last[0] == {"role": "system", "content": "Be terse."}  # session prompt persists
    assert [m["role"] for m in last] == ["system", "user", "assistant", "user"]


def test_failover_single_key(env):
    c, _ = env
    for h, kid in [("key_1=429", "key_2"), ("key_1=500", "key_2")]:
        r = chat(c, "s-" + h, "hi " + h, {"X-Simulate-Failure": h})
        assert r.status_code == 200
        assert r.json()["metadata"]["key_id"] == kid
        assert r.json()["metadata"]["fallback_attempts"] == 1


def test_all_fail_503_and_not_stored(env):
    c, _ = env
    for h in ["*=429", "key_1=429,key_2=500", "*=503"]:
        r = chat(c, "s503", "hi", {"X-Simulate-Failure": h})
        assert r.status_code == 503
        assert r.json() == {"detail": "all providers unavailable"}
    assert c.get("/sessions/s503/messages").status_code == 404


def test_simulation_disabled(tmp_path):
    s = Settings(llm_api_keys=["a", "b"], database_url=f"sqlite:///{tmp_path}/x.db", mock_llm=True,
                 enable_failure_simulation=False)
    litellm.cache = None
    c = TestClient(create_app(s))
    r = chat(c, "s", "hi", {"X-Simulate-Failure": "*=429"})
    assert r.status_code == 200


def test_validation(env):
    c, _ = env
    assert chat(c, "s", "   ").status_code == 422
    assert chat(c, "s", "x" * 4001).status_code == 422
    assert chat(c, "", "hi").status_code == 422
    assert chat(c, "s" * 129, "hi").status_code == 422
    assert c.post("/chat", json={"session_id": "s"}).status_code == 422
    r = c.post("/chat", content="{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422 and "detail" in r.json()
    assert chat(c, "s", "x" * 4000).status_code == 200
    assert c.get("/sessions/s/messages").json()["messages"][0]["content"] == "x" * 4000


def test_cors(env):
    c, _ = env
    r = c.options("/chat", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
                                    "Access-Control-Request-Headers": "x-simulate-failure,content-type"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
