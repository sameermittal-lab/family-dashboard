# Changelog

All notable changes to Family Dashboard. Newest entries at the top.

## 2026-05-23

### Server hardening (`1afdac8`)
- Background-thread crashes now logged via `threading.excepthook` (previously silent).
- `scan_photos` wrapped in `try/finally` with a non-blocking lock so the `scanning` flag never gets stuck and concurrent scans no longer race on `photo_manifest`.
- All `photo_manifest` reads/writes guarded by `_manifest_lock`; readers snapshot the list before iterating.
- `voice_history` mutations under `_voice_lock`.
- Atomic write for the photo manifest cache file.
- `update_config` deep-merges the POST body into the existing config and validates required top-level keys, so a partial POST cannot wipe sections.
- `request.get_json(silent=True)` everywhere (no more bare `request.json` raising on bad input).
- Calendar / commute / voice paths replace bare `except: pass` with logged warnings.
- `feedparser` `bozo` warnings logged for news + stocks feeds.
- `oauth_start` and `oauth_callback` return HTTP 500 on error; missing `credentials.json` returns 400.
- Flask `secret_key` persisted to `.secret_key` (gitignored), so sessions survive restart.
- HEIF opener registered once at module load (was per-photo, twice).

### Switched to waitress (`1afdac8`)
- Production server is now `waitress` (8-thread pool) instead of the Flask dev server. Flask dev server remains as a fallback if waitress is missing.
- `requirements.txt` adds `waitress>=3.0.0`.

### Volume API regression fix (`57f27db`)
- `_get_volume_interface` walks `speakers._dev` again to support newer pycaw (20251023+), which wraps `IMMDevice` in an `AudioDevice` object that doesn't expose `.Activate` directly.

### News pipeline (`54b2345`, `f1270bf`)
- Articles sorted newest-first by `published_parsed`; anything older than 24h is dropped.
- Background `news_refresh_loop` keeps the RSS cache warm regardless of frontend polling.
- Conditional GET via per-feed `etag` / `modified`; 304 responses short-circuit without reusing stale entries.
- Per-feed entry limit raised from 10 to 20 before the final cap of 40.
- Empty-fetch guard: if all feeds return zero articles, the cache is not poisoned and `lastFetch` does not advance.
- Cross-feed dedup was added then removed — the current feed set has minimal overlap and the extra logic wasn't paying for itself.

### Slideshow portrait-pair fix (`5f69618`)
- When `pairPortraits` is on, the partner photo no longer reappears on the left after the pair advances. `renderSlide` now sets `nextStartIndex` to skip past the partner.
- `nextSlide` reshuffles the deck when the index wraps, so order varies between full passes.
- `prevSlide` is a real function backed by `slideHistory`, replacing the buggy `currentIndex -= 2` math that didn't account for portrait pairs.
- ArrowLeft now binds to `prevSlide` (ArrowRight already bound to `nextSlide`).

## 2026-05 (earlier)

### Music widget (`2da79bb`, `4154f1c`)
- Progress bar, up-next list, shuffle, repeat.
- Controls separated into their own row.

### Initial public release (`a59045c`, `4d46a83`)
- Family Dashboard v1.0.
- README added; PII scrubbed from documentation.
