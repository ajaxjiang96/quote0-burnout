# Contributing to quote0-burnout

This guide defines the architectural standards and provider contract for `quote0-burnout`. Following these conventions prevents PR merge conflicts and ensures consistency across rendering, configuration, and scheduling.

---

## 1. Provider Contract

Each provider implementation lives in `providers/<name>.py` and must export four canonical functions:

```python
def is_configured() -> bool:
    """Return True if credentials or required configs exist (env or local token file).
    MUST NOT make network requests; pure synchronous check."""
    ...

def get_usage() -> dict:
    """Fetch usage or balance data from provider API.
    Returns {"ok": True, "raw": ...} on success or {"ok": False, "status": "...", "detail": "..."} on error.
    Must specify timeouts (recommended: 10-15s) and catch network exceptions."""
    ...

def build_snapshot(raw_data: dict, **kwargs) -> dict:
    """Transform raw API response into a structured snapshot dict.
    Must contain 'ok': bool.
    For windowed quotas: include 'short_label', 'short_used_percent', 'short_reset',
    'long_label', 'long_used_percent', 'long_reset', and 'status' ('ok'|'warn'|'hot')."""
    ...

def format_text(snapshot: dict) -> str:
    """Return a single-line or compact string representation for Text API mode."""
    ...
```

### Shared Helpers
Common utilities (environment variable reading, countdown formatting, percent status clamping) live in [`providers/core.py`](providers/core.py). Use `providers.core.env` instead of bare `os.environ.get`.

### Registry Integration
After implementing `providers/<name>.py`:
1. Import the module in [`providers/__init__.py`](providers/__init__.py).
2. Add the provider name to `PROVIDER_ORDER` and `_MODULES`.
3. Wire the provider in [`display.py`](display.py) `build_snapshot()` and recency fingerprint tracking.

---

## 2. Layout Tiers & Rendering Specs

The Quote/0 display is **296×152, 1-bit black & white**. Layouts divide the canvas into 2 rows of 76px height:
- **½ Panel (296×76)**: Full row width. Used in `1+1` and `1+2` (top panel).
- **¼ Cell (148×76)**: Half row width. Used in `1+2` (bottom two cells) and `2+2` (four cells).

### Typography & Font Rules
- **Pixel fonts MUST NOT be scaled dynamically**. Scaling breaks pixel alignment (e.g. dots disappear).
- `PixelOperator.ttf` (16px native): Panel titles, row labels, metric values.
- `Minecraftia-Regular.ttf` (8px native): Timestamp, secondary annotations, reset notes.
- `VCR_OSD_MONO_1.001.ttf` (21px native): Hero balance numbers.

### Content per Tier
- **½ Panel**: 16px logo + 16px title. 2 to 3 content rows with dot-grid progress bars (e.g. 5h / Week) or 21px hero balance. Progress bars indicate **REMAINING** percentage (100 - used).
- **¼ Cell**: 16px logo + 16px title. Up to 3 compact text lines (`Label Remaining% ResetTime`) or hero balance with tier badge.
- **Logos**: 16×16 1-bit monochrome PNG saved in `assets/logos/<name>.png`.

### Recency & Dead Providers
- Dead/unauthenticated providers (`ok=False`) are hidden automatically from grid layouts.
- Live providers are ordered by recency: providers with recently changed data move to the most visible slot (top-left). Unchanged data drifts back.

---

## 3. Configuration & Conventions

### Environment Variables
- All provider-specific variables must be namespaced: `<PROVIDER>_*` (e.g. `CODEX_ACCESS_TOKEN`, `CLAUDE_ACCESS_TOKEN`, `DEEPSEEK_API_KEY`, `OPENCODE_GO_API_KEY`).
- Document all keys in:
  - [`config.example.env`](config.example.env)
  - [`README.md`](README.md)
  - [`README_EN.md`](README_EN.md)

### Widget Mirroring
When adding a new provider or changing snapshot structure, check [`widget/quote0-widget.js`](widget/quote0-widget.js) to ensure browser or iOS Scriptable widget mirrors the fields.

---

## 4. Testing Expectations

All contributions must include test coverage:
1. **Snapshot unit tests**: Pure-function tests in [`tests/test_snapshots.py`](tests/test_snapshots.py) verifying `build_snapshot` with various raw inputs (missing fields, edge cases, error payloads).
2. **Render smoke tests**: Tests in [`tests/test_render.py`](tests/test_render.py) or [`tests/test_layout.py`](tests/test_layout.py) ensuring no exceptions occur when rendering the provider in both ½ and ¼ tiers.
3. **No live network in tests**: All tests must run offline with fixtures or mock responses.

Run tests locally with:
```bash
python3 -m pytest
```

---

## 5. Git Commit & Credit Conventions

- Use conventional commit messages: `feat(<scope>): description (#issue)`.
- When building on previous contributors' work or co-authoring, include:
  ```
  Co-authored-by: Name <email>
  ```
- Use stacked PRs when submitting sequences of interdependent features.
