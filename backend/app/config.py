"""All configuration comes from environment variables (see .env.example)."""
import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    llm_api_keys: list = field(default_factory=list)
    model: str = "gemini/gemini-3-flash-preview"
    database_url: str = "sqlite:////data/app.db"
    allowed_origins: list = field(default_factory=list)
    enable_failure_simulation: bool = False
    default_system_prompt: str = "You are a helpful, concise assistant."
    request_timeout: float = 30.0
    cache_enabled: bool = True
    temperature: float = 1.0  # Google recommends the default 1.0 for Gemini 3
    mock_llm: bool = False  # tests / offline demo only: skips the network

    @property
    def db_path(self) -> str:
        url = self.database_url
        for prefix in ("sqlite:///", "sqlite://"):
            if url.startswith(prefix):
                return url[len(prefix):]
        return url


def load_settings() -> Settings:
    keys = [k.strip() for k in os.getenv("LLM_API_KEYS", "").split(",") if k.strip()]
    origins = [o.strip().rstrip("/") for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    if not origins:  # sensible local default so the UI works out of the box
        origins = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173"]
    return Settings(
        llm_api_keys=keys,
        model=os.getenv("MODEL", "gemini/gemini-3-flash-preview"),
        database_url=os.getenv("DATABASE_URL", "sqlite:////data/app.db"),
        allowed_origins=origins,
        enable_failure_simulation=_bool("ENABLE_FAILURE_SIMULATION"),
        default_system_prompt=os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful, concise assistant."),
        request_timeout=float(os.getenv("REQUEST_TIMEOUT", "30")),
        cache_enabled=_bool("CACHE_ENABLED", True),
        temperature=float(os.getenv("TEMPERATURE", "1.0")),
        mock_llm=_bool("MOCK_LLM", False),
    )
