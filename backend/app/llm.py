"""LiteLLM gateway: key pool, ordered failover, built-in response cache."""
import logging
from dataclasses import dataclass

import litellm
from litellm.caching.caching import Cache

from .config import Settings

log = logging.getLogger("gateway")
litellm.suppress_debug_info = True
litellm.set_verbose = False

SIM_STATUSES = {429, 500, 502, 503}


class AllProvidersUnavailable(Exception):
    pass


class SimulatedProviderError(Exception):
    def __init__(self, status: int):
        super().__init__(f"simulated provider status {status}")
        self.status = status


@dataclass
class LLMResult:
    reply: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_hit: bool
    key_id: str | None
    fallback_attempts: int


def parse_failure_header(value: str | None) -> dict:
    """'key_1=429,key_2=500' or '*=429' -> {'key_1': 429, ...}. Bad pairs are ignored."""
    rules = {}
    if not value:
        return rules
    for pair in value.split(","):
        if "=" not in pair:
            continue
        k, v = (p.strip() for p in pair.split("=", 1))
        if v.isdigit() and int(v) in SIM_STATUSES and k:
            rules[k] = int(v)
    return rules


class Gateway:
    def __init__(self, settings: Settings):
        self.s = settings
        # Key ids are positional: key_1, key_2, ... (the key value is never exposed)
        self.keys = [(f"key_{i}", k) for i, k in enumerate(settings.llm_api_keys, start=1)]
        if settings.cache_enabled:
            litellm.cache = Cache(type="local")  # LiteLLM in-memory cache
        else:
            litellm.cache = None

    def _simulated(self, key_id: str, rules: dict):
        status = rules.get(key_id) or rules.get("*")
        if status:
            raise SimulatedProviderError(status)

    def complete(self, messages: list, rules: dict | None = None) -> LLMResult:
        rules = rules or {}
        failures = 0
        for key_id, key in self.keys:
            try:
                self._simulated(key_id, rules)
                kwargs = dict(
                    model=self.s.model,
                    messages=messages,
                    api_key=key,
                    timeout=self.s.request_timeout,
                    num_retries=0,  # we do our own key-level failover
                    caching=self.s.cache_enabled,
                    temperature=self.s.temperature,
                )
                if self.s.mock_llm:
                    kwargs["mock_response"] = "Mock reply to: " + messages[-1]["content"]
                resp = litellm.completion(**kwargs)
                text = (resp.choices[0].message.content or "").strip()
                if not text:
                    raise ValueError("empty completion")
                hit = bool(getattr(resp, "_hidden_params", {}).get("cache_hit"))
                usage = resp.usage
                in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
                out_tok = int(getattr(usage, "completion_tokens", 0) or 0)
                if not in_tok:  # provider omitted usage: estimate locally
                    in_tok = litellm.token_counter(model=self.s.model, messages=messages)
                if not out_tok:
                    out_tok = litellm.token_counter(model=self.s.model, text=text)
                return LLMResult(
                    reply=text,
                    model=self.s.model,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cache_hit=hit,
                    key_id=None if hit else key_id,
                    fallback_attempts=0 if hit else failures,
                )
            except Exception as e:  # 429, quota, 5xx, auth, timeout... -> next key
                failures += 1
                status = getattr(e, "status", None) or getattr(e, "status_code", None)
                detail = str(e)
                for _, secret in self.keys:  # never leak a key into logs
                    detail = detail.replace(secret, "***")
                log.warning("%s failed (%s) %s: %s", key_id, status, type(e).__name__, detail[:400])
        raise AllProvidersUnavailable()
