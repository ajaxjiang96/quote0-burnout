"""Provider package.

Each provider module exposes a canonical API used by the display.py shell:

    get_usage()            -> {"ok": bool, ...} raw fetch result
    build_snapshot(raw)    -> structured snapshot dict (renderer input)
    format_text(snapshot)  -> one-line/compact text form (Text API)

Shared helpers live in providers.core. Panel-order/layout concerns are the
renderer's (render.py) and the layout engine's (roadmap #9); providers only
own fetch + snapshot + text format.
"""
