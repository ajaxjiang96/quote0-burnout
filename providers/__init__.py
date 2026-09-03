"""Provider package.

Each provider module exposes a canonical API used by the display.py shell:

    get_usage()            -> {"ok": bool, ...} raw fetch result
    build_snapshot(raw)    -> structured snapshot dict (renderer input)
    format_text(snapshot)  -> one-line/compact text form (Text API)
    is_configured()        -> credentials available (env/file), no network

Shared helpers live in providers.core. Panel-order/layout concerns are the
renderer's (render.py) and the layout engine's (roadmap #9); providers only
own fetch + snapshot + text format.
"""

from . import claude, codex, deepseek, opencode

PROVIDER_ORDER = ["codex", "claude", "deepseek", "opencode"]

_MODULES = {"codex": codex, "claude": claude, "deepseek": deepseek, "opencode": opencode}


def configured_providers() -> list[str]:
    """Providers whose credentials are configured (env or credential file),
    in render priority order. No network calls; runtime-env read.
    Looked up per-call so tests (and #10's ordering) can patch predicates."""
    return [name for name in PROVIDER_ORDER if _MODULES[name].is_configured()]
