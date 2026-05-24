# Family Dashboard — Agent Onboarding Notes

This file is for AI coding agents (Claude Code, etc.) and any new contributor
who needs to come up to speed quickly. User-facing docs are in `README.md`
and `docs/documentation.html`.

## What this is

A Flask app that drives a wall-mounted Windows kiosk: photo slideshow plus
weather, news, calendar, notes, music, voice assistant, commute. The
frontend (`static/app.js`) is a single ~2.5k-line vanilla-JS app — no build
step, no framework. Backend (`app.py`) is one file, ~1.5k lines, also no
framework beyond Flask.

Production target: a Windows machine on a home LAN, Chrome in `--kiosk`
mode pointed at `http://localhost:5000`. The same app also serves a phone
remote at `/remote`.

## Run it

Local development (Mac/Linux/Windows, has fallbacks for non-Windows):

```bash
pip install -r requirements.txt
cp config.example.json config.json   # if config.json does not exist
python app.py
# open http://localhost:5000
```

Windows kiosk: `start.bat` runs `python app.py` in an auto-restart loop and
opens Chrome in kiosk mode after a 4-second delay. The server runs under
**waitress** (8 threads); if waitress is missing, it falls back to the
Flask dev server with a logged warning.

There is no test suite. Verify changes by running the app and exercising
the affected feature.

## Layout

```
app.py                    # Flask backend — config, photos, weather, news, calendar,
                          # commute, voice (Gemini), notes, volume, OAuth, status
static/app.js             # Frontend — slideshow, panels, voice, settings, remote
static/styles.css         # Single stylesheet (frosted glass theme)
templates/index.html      # Main dashboard
templates/remote.html     # Phone remote control
config.json               # User config (gitignored)
config.example.json       # Template — copy to config.json on first run
credentials.json          # Google OAuth client secret (gitignored)
token.json                # Google OAuth refresh token (gitignored)
oauth_state.json          # Transient PKCE state (gitignored)
.secret_key               # Persisted Flask secret_key (gitignored)
notes.json                # User notes (gitignored)
cache/                    # Photo manifest cache + transcoded HEIC/RAW jpegs
logs/                     # Rotating dashboard.log (5 MB × 3)
docs/                     # User-facing HTML docs and design mockups
backups/                  # Manual config snapshots — not used by code
start.bat                 # Windows launcher (auto-restart loop)
setup.bat                 # One-time deps install + autostart shortcut
configure-kiosk.bat       # Optional Windows kiosk hardening
```

## Key conventions

- **One file per concern, not per layer.** `app.py` groups by section
  (`# ==================== NEWS ====================`). `static/app.js`
  follows the same pattern. New features go in a new section.
- **Logging** — module-level `log` (`dashboard` logger) with subsystem
  prefix in messages: `log.info("PHOTOS scan complete: ...")`,
  `log.warning("VOICE no Gemini API key ...")`. Stick to that pattern;
  it's how the kiosk owner greps the log.
- **No comments unless the why is non-obvious.** Most existing code has
  no inline comments. Match that.
- **Atomic writes for any user-state file** (`config.json`, `notes.json`,
  `photo_manifest.json`). Pattern: write to `path.with_suffix(".tmp")`,
  then `tmp.replace(path)`.
- **Errors return JSON with HTTP status code**, never plain text:
  `return jsonify({"error": ...}), 500`.
- **`request.get_json(silent=True) or {}`** — never bare `request.json`.
- **No tests.** Verify by running the app, opening DevTools, watching the log.

## Concurrency model — read this before touching shared state

The backend has several long-lived background threads. Locking matters.

| Lock              | Protects                                             |
|-------------------|------------------------------------------------------|
| `_manifest_lock`  | `photo_manifest` dict (photos list, lastScan, etc.)  |
| `_scan_lock`      | The scan operation itself (non-blocking acquire — re-entrancy is silently dropped) |
| `_notes_lock`     | `notes.json` read/write                              |
| `_voice_lock`     | `voice_history` list                                 |

Background threads:

- `auto_scan_loop` — periodic photo scan based on `config.photos.scanInterval`
- `news_refresh_loop` — periodic RSS fetch based on `config.news.refreshInterval`
- ad-hoc scan threads spawned by `start_scan_thread`

Crash handlers:

- `sys.excepthook` — main-thread crashes (logged at CRITICAL)
- `threading.excepthook` — background-thread crashes (logged at CRITICAL).
  Without this, a thread crash is silent.

Rules of thumb:
- If you read or write `photo_manifest`, take `_manifest_lock`. Snapshot
  with `list(photo_manifest["photos"])` before iterating in a route.
- If you spawn a new long-running background thread, document why and
  make sure top-level exceptions land in the log (the global threading
  hook does this automatically as long as the exception escapes the
  thread).

## API surface

All routes return JSON unless noted. Success is `{"ok": true, ...}`,
failure is `{"ok": false, "error": "..."}` with a 4xx/5xx status code.

| Route                           | Method | Purpose                                  |
|---------------------------------|--------|------------------------------------------|
| `/`                             | GET    | Main dashboard (renders `index.html`)    |
| `/remote`                       | GET    | Phone remote (renders `remote.html`)     |
| `/api/config`                   | GET    | Current config                           |
| `/api/config`                   | POST   | Deep-merges into existing config; validates required top-level keys |
| `/api/photos`                   | GET    | Manifest snapshot (photos + scanning state) |
| `/api/photos/scan`              | POST   | Trigger scan (`?full=true` for full rescan) |
| `/api/photo/<id>`               | GET    | Serves a photo (transcodes HEIC/RAW to JPEG, caches in `cache/`) |
| `/api/browse`                   | GET    | Folder browser for the settings UI       |
| `/api/resolve-folder`           | GET    | Resolve a folder name on common drives   |
| `/api/detect-location`          | GET    | IP geolocation                           |
| `/api/autocomplete/city`        | GET    | Open-Meteo geocoding                     |
| `/api/autocomplete/address`     | GET    | Google Places                            |
| `/api/youtube/search`           | GET    | YouTube Data API v3                      |
| `/api/weather`                  | GET    | Open-Meteo or OpenWeatherMap (10-min cache) |
| `/api/news`                     | GET    | Aggregated RSS (cache TTL = `news.refreshInterval`) |
| `/api/stocks`                   | GET    | Stock RSS (10-min cache)                 |
| `/api/calendar`                 | GET    | Upcoming Google Calendar events          |
| `/api/commute`                  | GET    | Google Maps Directions (schedule-aware)  |
| `/api/notes`                    | GET    | All notes                                |
| `/api/notes`                    | POST   | Add a note                               |
| `/api/notes/<id>`               | DELETE | Delete a note                            |
| `/api/notes/<id>/pin`           | POST   | Toggle pin                               |
| `/oauth/start`                  | GET    | Begin Google OAuth (PKCE)                |
| `/oauth/callback`               | GET    | OAuth redirect target — writes `token.json` |
| `/api/voice`                    | POST   | Gemini-powered voice command             |
| `/api/voice/reset`              | POST   | Clear conversation history               |
| `/api/status`                   | GET    | Health snapshot for all subsystems       |
| `/api/volume` / `/api/volume/mute` | GET/POST | Windows audio (pycaw)                |
| `/api/screen/off` / `/api/screen/on` | POST | PowerShell SendMessage to monitor    |

## Frontend conventions

- `static/app.js` is one global namespace; `init()` at the bottom
  registers everything.
- `currentIndex` walks `photos` array; `nextStartIndex` is the planned
  jump for the next advance (used for portrait-pair skipping).
  `slideHistory` lets `prevSlide` step back across pair boundaries.
- Slideshow advance must go through `nextSlide()` / `prevSlide()`.
  Don't recompute `currentIndex` inline — that pattern caused a bug
  where partner photos re-appeared on the left after a portrait pair.
- Voice command actions match the JSON contract documented inline in
  the `system_prompt` inside `voice_command()` in `app.py`. Adding a new
  action means: (a) document it in the system prompt, (b) add a `case`
  to the action switch in `static/app.js` (search for `case "next_photo"`).
- Settings UI: each setting has an `s-<section>-<name>` element id and is
  read in `saveSettings()` / written in `populateSettings()`. Adding a
  setting means edits to `templates/index.html`, `populateSettings`, and
  `saveSettings`.

## Gotchas / footguns

- **pycaw version compat** — `_get_volume_interface` walks `speakers ->
  ._dev` because newer pycaw (20251023+) wraps `IMMDevice` in an
  `AudioDevice` object that doesn't expose `.Activate` directly. Don't
  "simplify" this back without testing on the kiosk.
- **`opencv-python-headless`**, not `opencv-python`. Face detection runs
  on the server during photo scan; the headless package is correct for a
  no-display environment.
- **HEIF opener registration** — `register_heif_opener()` is called once
  at module load. Don't add per-photo calls.
- **`config.json` shape** — required top-level keys are `photos`,
  `weather`, `news`, `calendar`, `commute` (see `_REQUIRED_CONFIG_KEYS`).
  If you add a new section, decide whether it's required and update the
  set if so.
- **Photo scanning is incremental** — `scan_photos` keys cache by
  `mtime`. Touching a photo's mtime forces re-processing. Use `?full=true`
  on `/api/photos/scan` to force a full rescan.
- **OAuth token expiry** — `invalid_grant` on calendar means the refresh
  token has been revoked (long inactivity, password change). Re-auth at
  `/oauth/start`. Not a bug.
- **`0.0.0.0` bind** — the server is reachable on the LAN with no auth.
  This is intentional for the phone remote, but be careful before
  exposing to a wider network.
- **Frontend caches aggressively in kiosk Chrome** — after pulling new
  JS/CSS, you may need a hard reload (Ctrl+Shift+R) or kiosk window
  restart, not just a server restart.

## Recent context (May 2026)

The last several rounds of work:

- **Server hardening** — added `threading.excepthook`, locks for
  `photo_manifest` and `voice_history`, `try/finally` around `scan_photos`
  to keep `scanning=False` from getting stuck, atomic manifest writes.
- **Switched to waitress** for production. Falls back to Flask dev server
  if waitress is not installed.
- **Persisted `secret_key`** to `.secret_key` (gitignored) so sessions
  survive restart.
- **News pipeline** — sort by `published_parsed` newest-first, drop
  articles older than 24h, conditional GET (`etag` / `modified`),
  background refresh thread, skip cache update on empty fetch. Per-feed
  limit raised from 10 to 20. Dedup was added then removed because the
  current feed set has minimal cross-feed overlap.
- **Slideshow portrait pair fix** — partner photos no longer re-appear
  on the left after the pair advances. Requires `nextStartIndex`
  bookkeeping (set in `renderSlide`, consumed by `nextSlide`).
  `prevSlide` is a real function now backed by `slideHistory`.
- **Volume API** — restored `_dev` walk for new pycaw.

The git history is the source of truth — `git log` for the full picture.

## When you finish a change

1. Run `python app.py` locally and exercise the change.
2. Tail `logs/dashboard.log` and confirm no new warnings.
3. Commit with Conventional Commits format (`fix(scope): ...`,
   `feat(scope): ...`, `refactor(scope): ...`, `docs: ...`).
4. Push to `origin/main` only when the user asks. The kiosk pulls from
   `https://github.com/sameermittal-lab/family-dashboard`.
5. Update this file if you changed something an agent would need to know
   on the next session (a new lock, a new background thread, a new
   gotcha).
