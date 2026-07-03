import os
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5.4")

    # --- Authentication ---------------------------------------------
    # Signs admin session cookies and API bearer tokens. MUST be
    # overridden in production; the default exists so the demo boots.
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-change-me")

    # Shared secret between the web gateway and the MCP server. The MCP
    # server rejects any request that doesn't present it, so tool calls
    # can only enter through the trusted gateway.
    MCP_GATEWAY_KEY: str = os.getenv("MCP_GATEWAY_KEY", "dev-gateway-key-change-me")

    # Admin session lifetime (hours).
    ADMIN_SESSION_TTL_HOURS: int = int(os.getenv("ADMIN_SESSION_TTL_HOURS", "8"))

    # DEMO_MODE=true lets the console switch identities freely on
    # /api/v1/execute (classroom demo of RBAC differences). Set to
    # false to require a Bearer token from POST /api/v1/auth/login.
    # The admin dashboard and the MCP server are ALWAYS authenticated,
    # regardless of this flag.
    DEMO_MODE: bool = _env_bool("DEMO_MODE", True)


settings = Settings()