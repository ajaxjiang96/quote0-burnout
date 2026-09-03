# ROADMAP

quote0-burnout now renders **4 providers** (Codex, Claude, DeepSeek, OpenCode Go) and is expected to keep growing. This document sets the order of work; each item has an issue.

## Order

| # | Item | Issue | Feasibility | Notes |
|---|---|---|---|---|
| 1 | **Provider refactor** — split providers into their own directory with a shared panel interface | [#8](https://github.com/ajaxjiang96/quote0-burnout/issues/8) | High | `display.py` is ~1300 lines and every parallel provider PR collides (see the PR #1/#2 history). Foundation for everything else; do tests first (also in #14). |
| 2 | **Layout engine** — `1+1` / `1+2` / `2+2`, max 4 panels, panel count from valid configured providers + startup override | [#9](https://github.com/ajaxjiang96/quote0-burnout/issues/9) | High | Needs the panel interface from #8. Per-provider content tiers: ½ screen vs ¼ screen. |
| 3 | **Recency ordering** — per-provider update timestamps + change detection; most-changed provider first, cell top-right shows update time | [#10](https://github.com/ajaxjiang96/quote0-burnout/issues/10) | High | Small data-model change; pairs well with #12. |
| 4 | **Stale marker** — `*` on panels serving cached data | [#12](https://github.com/ajaxjiang96/quote0-burnout/issues/12) | Trivial | `_cached` plumbing already exists from #6. |
| 5 | **Grid junctions** — box-drawing (┬ ┴ ├ ┤ ┼) where dashed separators meet | [#11](https://github.com/ajaxjiang96/quote0-burnout/issues/11) | Medium | Needs the layout engine's geometry. |
| 6 | **Refresh interval override** — `--interval` CLI param, self-scheduling | [#13](https://github.com/ajaxjiang96/quote0-burnout/issues/13) | Small | Unblocks docker; keep a sane minimum. |
| 7 | **Tests harness** — snapshot unit tests + render smoke tests per layout | [#14](https://github.com/ajaxjiang96/quote0-burnout/issues/14) | High | Existing: `tests/test_claude_usage.py` (#1). Do before the refactor lands. |
| 8 | **Contributing guide** — the provider contract, layout tiers, credit conventions | [#15](https://github.com/ajaxjiang96/quote0-burnout/issues/15) | Medium | Must follow the refactor's real interface. |
| 9 | **Docker deployment** | [#16](https://github.com/ajaxjiang96/quote0-burnout/issues/16) | Medium | Depends on #13. |
| 10 | **Experimental `1+1+1`** stacked layout | [#17](https://github.com/ajaxjiang96/quote0-burnout/issues/17) | Uncertain | Depends on #9; measure e-ink legibility with compressed content. |

## Why this order

- **#8 + #14 first**: the current single-file `display.py` is the root cause of every collision so far. But don't restructure without the test harness to catch regressions.
- **#9 next**: the layout engine needs the panel interface; it is the highest-value visible change (real multi-panel use).
- **#10/#12/#11/#13** are incremental on top of the new structure — each small, low-risk.
- **#16/#17** are polish/deployment; no scheduling pressure.

## Long-term aim

A "public panel contract": providers only implement fetch + snapshot + two content tiers; the layout engine owns rendering, ordering, and cell geometry. Adding provider #5 should be a new directory + docs entry, not another 4-file edit.
