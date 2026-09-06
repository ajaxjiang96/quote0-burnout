# Quote/0 API Reference

## Image API

```
POST https://dot.mindreset.tech/api/authV2/open/device/{device_id}/image
Authorization: Bearer {api_key}
Content-Type: application/json

{
    "image": "<base64 png>",
    "refreshNow": true,
    "ditherType": "DIFFUSION",
    "ditherKernel": "FLOYD_STEINBERG",
    "border": 0
}
```

## Image API — Single Card (no taskKey)

When the device has exactly **one** IMAGE_API card, push **without** `taskKey`.
The API targets the sole slot automatically. Adding `taskKey` with a single card may return 404.

```python
payload = {"image": b64, "refreshNow": True, "ditherType": "DIFFUSION", ...}
# NO taskKey when only one card exists
```

## Refresh Behavior

- `refreshNow: true` → display updates immediately (loop slots only, or single-card).
- Fixed content slots may return "将在下次内容切换时显示" — they don't support instant refresh.
- With a single IMAGE_API card, `refreshNow=true` works regardless of slot type.

## Error Patterns

| Error | Cause | Fix |
|-------|-------|-----|
| 404 "未找到图像 API 内容" | IMAGE_API card uninitialized | Delete and re-add card in Content Studio |
| 404 with taskKey | taskKey mismatch or single-card conflict | Remove taskKey for single-card setups |
| 401 | Invalid API key | Check QUOTE0_API_KEY in .env |
| Device offline | Device sleeping/out of range | Content queued, displays on next wake |

## Listing Tasks

```
GET https://dot.mindreset.tech/api/authV2/open/device/{device_id}/fixed/list
GET https://dot.mindreset.tech/api/authV2/open/device/{device_id}/loop/list
```

Use `python display.py --list-tasks` to view current slots.
