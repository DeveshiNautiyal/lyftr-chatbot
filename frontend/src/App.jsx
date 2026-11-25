import { useEffect, useRef, useState } from "react";

const API = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

const newSessionId = () => "s-" + Math.random().toString(36).slice(2, 10);

const FAILURE_PRESETS = [
  { label: "None", value: "" },
  { label: "key_1 returns 429", value: "key_1=429" },
  { label: "key_1 429, key_2 500", value: "key_1=429,key_2=500" },
  { label: "Every key returns 429", value: "*=429" },
];

function readableError(status, body) {
  if (status === 503) return "All AI providers are unavailable right now. Your message was not saved. Try again in a moment.";
  if (status === 422) {
    const d = body && body.detail;
    if (Array.isArray(d) && d[0] && d[0].msg) return "Message not sent: " + d[0].msg.replace(/^Value error, /, "") + ".";
    return "Message not sent: check the length (1 to 4000 characters).";
  }
  if (body && typeof body.detail === "string") return body.detail;
  return `Something went wrong (status ${status}).`;
}

function Meta({ m }) {
  const cached = m.resolution_source === "LLM_CACHE";
  return (
    <dl className="meta">
      <div>
        <dt>Source</dt>
        <dd>
          <span data-testid="meta-source" className={"pill " + (cached ? "cache" : "live")}>
            {m.resolution_source}
          </span>
        </dd>
      </div>
      <div>
        <dt>Model</dt>
        <dd data-testid="meta-model">{m.model}</dd>
      </div>
      <div>
        <dt>Latency</dt>
        <dd data-testid="meta-latency">{m.latency_ms} ms</dd>
      </div>
      <div>
        <dt>Input tokens</dt>
        <dd data-testid="meta-input-tokens">{m.input_tokens}</dd>
      </div>
      <div>
        <dt>Output tokens</dt>
        <dd data-testid="meta-output-tokens">{m.output_tokens}</dd>
      </div>
      <div>
        <dt>Key</dt>
        <dd>
          {m.key_id ?? "none (cache)"}
          {m.fallback_attempts > 0 && <span className="fb"> after {m.fallback_attempts} failed</span>}
        </dd>
      </div>
    </dl>
  );
}

export default function App() {
  const [sessionId] = useState(newSessionId); // new session on every page load
  const [items, setItems] = useState([]);
  const [text, setText] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [simulate, setSimulate] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [items, busy]);

  async function send() {
    const message = text.trim();
    if (!message || busy) return;
    setText("");
    setBusy(true);
    setItems((p) => [...p, { kind: "user", text: message }]);
    try {
      const body = { session_id: sessionId, message };
      if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim();
      const headers = { "Content-Type": "application/json" };
      if (simulate) headers["X-Simulate-Failure"] = simulate;
      const res = await fetch(`${API}/chat`, { method: "POST", headers, body: JSON.stringify(body) });
      let data = null;
      try {
        data = await res.json();
      } catch {
        /* non-JSON body */
      }
      if (!res.ok) {
        setItems((p) => [...p, { kind: "error", text: readableError(res.status, data) }]);
      } else {
        setItems((p) => [...p, { kind: "assistant", text: data.reply, meta: data.metadata }]);
      }
    } catch {
      setItems((p) => [...p, { kind: "error", text: "Can't reach the server. Check your connection and try again." }]);
    } finally {
      setBusy(false);
    }
  }

  function onKey(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="app">
      <header className="top">
        <div>
          <h1>Chat with provenance</h1>
          <p className="sub">Every reply shows whether it was generated live or served from cache, and what it cost in tokens.</p>
        </div>
        <span className="sid" title="Session id for this page load">{sessionId}</span>
      </header>

      <details className="settings">
        <summary>Session settings</summary>
        <label>
          System prompt
          <textarea
            data-testid="system-prompt-input"
            rows={2}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="Optional. Sets how the assistant behaves in this session."
          />
        </label>
        <label>
          Simulate provider failure (demo)
          <select value={simulate} onChange={(e) => setSimulate(e.target.value)}>
            {FAILURE_PRESETS.map((p) => (
              <option key={p.label} value={p.value}>{p.label}</option>
            ))}
          </select>
        </label>
      </details>

      <main className="thread" aria-live="polite">
        {items.length === 0 && (
          <div className="empty">
            <p>Ask something to begin. Send the same first question from a fresh page to see a cache hit.</p>
          </div>
        )}
        {items.map((it, i) => {
          if (it.kind === "user") return <div key={i} className="bubble user">{it.text}</div>;
          if (it.kind === "error") return <div key={i} className="bubble error" role="alert">{it.text}</div>;
          return (
            <div key={i} className="bubble assistant" data-testid="assistant-message">
              <div className="reply">{it.text}</div>
              <Meta m={it.meta} />
            </div>
          );
        })}
        {busy && <div className="bubble assistant pending">Thinking…</div>}
        <div ref={endRef} />
      </main>

      <footer className="composer">
        <textarea
          data-testid="chat-input"
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          placeholder="Type a message"
          aria-label="Message"
        />
        <button data-testid="send-button" onClick={send} disabled={busy || !text.trim()}>
          Send
        </button>
      </footer>
    </div>
  );
}
