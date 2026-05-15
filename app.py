"""Family Dashboard — Flask Backend"""
import os
import json
import time
import threading
import hashlib
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from io import BytesIO

from flask import Flask, render_template, jsonify, request, send_file, redirect, url_for, session
from PIL import Image
Image.MAX_IMAGE_PIXELS = None  # Disable decompression bomb limit for large photos
import feedparser
import requests

app = Flask(__name__)
app.secret_key = os.urandom(24)

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
NOTES_PATH = BASE_DIR / "notes.json"
CACHE_DIR = BASE_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# ==================== LOGGING ====================
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

log = logging.getLogger("dashboard")
log.setLevel(logging.DEBUG)

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

# File handler — 5 MB per file, keep 3 backups
_fh = RotatingFileHandler(LOG_DIR / "dashboard.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
log.addHandler(_fh)

# Console handler
_ch = logging.StreamHandler()
_ch.setLevel(logging.INFO)
_ch.setFormatter(_fmt)
log.addHandler(_ch)

log.info("=== Family Dashboard starting ===")

# ==================== ERROR HANDLERS ====================
@app.errorhandler(Exception)
def handle_exception(e):
    log.error(f"Unhandled exception on {request.path}: {e}", exc_info=True)
    return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def handle_404(e):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(405)
def handle_405(e):
    return jsonify({"error": "Method not allowed"}), 405

# Global crash handler — catches unhandled exceptions that would kill the process
import sys
def _crash_handler(exc_type, exc_value, exc_tb):
    log.critical(f"UNHANDLED CRASH: {exc_type.__name__}: {exc_value}", exc_info=(exc_type, exc_value, exc_tb))
    for h in log.handlers:
        h.flush()
sys.excepthook = _crash_handler

# ==================== CONFIG ====================
def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        log.error("CONFIG config.json not found — copy config.example.json to config.json")
        raise
    except (json.JSONDecodeError, ValueError) as e:
        log.error(f"CONFIG config.json is corrupt: {e}")
        raise

def save_config(cfg):
    tmp = CONFIG_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=4)
    tmp.replace(CONFIG_PATH)
    log.info("CONFIG saved")

# ==================== NOTES ====================
_notes_lock = threading.Lock()

def load_notes():
    with _notes_lock:
        if NOTES_PATH.exists():
            try:
                with open(NOTES_PATH, "r") as f:
                    data = f.read().strip()
                    if not data:
                        log.debug("NOTES file empty, returning []")
                        return []
                    return json.loads(data)
            except (json.JSONDecodeError, ValueError) as e:
                log.error(f"NOTES corrupt file, returning []: {e}")
                return []
        return []

def save_notes(notes):
    with _notes_lock:
        tmp = NOTES_PATH.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(notes, f, indent=2)
        tmp.replace(NOTES_PATH)
        log.debug(f"NOTES saved {len(notes)} notes")

# ==================== PHOTO SCANNER ====================
photo_manifest = {"photos": [], "lastScan": None, "scanning": False}

# Face detection setup
_face_cascade = None
def get_face_cascade():
    global _face_cascade
    if _face_cascade is None:
        import cv2
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = cv2.CascadeClassifier(cascade_path)
    return _face_cascade

def detect_face_center(filepath, img_width, img_height):
    """Detect faces and return focus point as (x%, y%). Returns (50, 50) if no faces."""
    try:
        import cv2
        import numpy as np
        # Read and resize for faster detection
        img = cv2.imread(str(filepath))
        if img is None:
            return 50, 50
        scale = min(800 / max(img.shape[1], 1), 1.0)
        if scale < 1.0:
            small = cv2.resize(img, None, fx=scale, fy=scale)
        else:
            small = img
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        cascade = get_face_cascade()
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        if len(faces) == 0:
            return 50, 50
        # Average center of all detected faces
        cx = sum(x + w/2 for x, y, w, h in faces) / len(faces)
        cy = sum(y + h/2 for x, y, w, h in faces) / len(faces)
        # Convert to percentage of original image
        fx = round((cx / small.shape[1]) * 100, 1)
        fy = round((cy / small.shape[0]) * 100, 1)
        return fx, fy
    except Exception:
        return 50, 50
SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff", ".arw", ".cr2", ".nef", ".dng", ".raf", ".heic", ".heif"}
RAW_EXT = {".arw", ".cr2", ".nef", ".dng", ".raf"}
HEIC_EXT = {".heic", ".heif"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

def load_cached_manifest():
    """Load manifest from disk cache on startup."""
    global photo_manifest
    cache_file = CACHE_DIR / "photo_manifest.json"
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                cached = json.load(f)
            photo_manifest["photos"] = cached.get("photos", [])
            photo_manifest["lastScan"] = cached.get("lastScan")
            photo_manifest["scanning"] = False
            log.info(f"PHOTOS loaded {len(photo_manifest['photos'])} photos from cache")
        except Exception as e:
            log.warning(f"PHOTOS failed to load cache: {e}")

def save_manifest():
    """Save current manifest to disk."""
    cache_file = CACHE_DIR / "photo_manifest.json"
    save_data = {
        "photos": photo_manifest["photos"],
        "lastScan": photo_manifest["lastScan"]
    }
    with open(cache_file, "w") as cf:
        json.dump(save_data, cf)

def process_single_file(f):
    """Process a single file — get dimensions, orientation, face detection."""
    ext = f.suffix.lower()
    pid = hashlib.md5(str(f).encode()).hexdigest()[:12]
    mtime = os.path.getmtime(str(f))

    if ext in VIDEO_EXT:
        return {
            "path": str(f), "name": f.name, "mtime": mtime,
            "width": 0, "height": 0, "orientation": "landscape",
            "type": "video", "focusX": 50, "focusY": 50, "id": pid
        }
    elif ext in HEIC_EXT:
        w, h, orientation = 0, 0, "landscape"
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
            with Image.open(f) as img:
                w, h = img.size
                orientation = "portrait" if h > w else "landscape"
        except Exception:
            pass
        fx, fy = detect_face_center(str(f), w, h)
        return {
            "path": str(f), "name": f.name, "mtime": mtime,
            "width": w, "height": h, "orientation": orientation,
            "type": "image", "focusX": fx, "focusY": fy, "id": pid
        }
    elif ext in RAW_EXT:
        return {
            "path": str(f), "name": f.name, "mtime": mtime,
            "width": 0, "height": 0, "orientation": "landscape",
            "type": "image", "focusX": 50, "focusY": 50, "id": pid
        }
    else:
        w, h = 0, 0
        try:
            with Image.open(f) as img:
                w, h = img.size
        except Exception as e:
            log.warning(f"PHOTOS could not open image {f.name}: {e}")
        orientation = "portrait" if h > w else "landscape"
        fx, fy = detect_face_center(str(f), w, h)
        return {
            "path": str(f), "name": f.name, "mtime": mtime,
            "width": w, "height": h, "orientation": orientation,
            "type": "image", "focusX": fx, "focusY": fy, "id": pid
        }

def scan_photos(photo_path, include_subfolders=True, full=False):
    """Incremental scan — only processes new/changed files."""
    global photo_manifest
    photo_manifest["scanning"] = True
    photo_manifest["scanProgress"] = 0
    photo_manifest["scanTotal"] = 0

    path = Path(photo_path)
    if not path.exists():
        photo_manifest["scanning"] = False
        photo_manifest["error"] = "Path not found"
        return

    # Build lookup of existing cached photos by path
    if full:
        cached_lookup = {}
    else:
        cached_lookup = {p["path"]: p for p in photo_manifest.get("photos", [])}

    # Get all current files on disk
    pattern = "**/*" if include_subfolders else "*"
    all_files = [f for f in path.glob(pattern) if f.suffix.lower() in (SUPPORTED_EXT | VIDEO_EXT) and f.is_file()]
    current_paths = set()
    to_process = []

    for f in all_files:
        fpath = str(f)
        current_paths.add(fpath)
        cached = cached_lookup.get(fpath)
        if cached:
            # Check if file was modified
            try:
                mtime = os.path.getmtime(fpath)
                if cached.get("mtime") == mtime:
                    continue  # Unchanged, skip
            except Exception:
                continue
        to_process.append(f)

    photo_manifest["scanTotal"] = len(to_process)
    new_count = len(to_process)
    log.info(f"PHOTOS found {len(all_files)} files, {new_count} new/changed to process")

    # Process new/changed files
    new_photos = {}
    for idx, f in enumerate(to_process):
        photo_manifest["scanProgress"] = idx + 1
        try:
            entry = process_single_file(f)
            new_photos[entry["path"]] = entry
        except Exception as e:
            log.warning(f"PHOTOS error processing {f.name}: {e}")
            continue

    # Build final list: keep unchanged cached entries + add new/updated ones
    final_photos = []
    for f in all_files:
        fpath = str(f)
        if fpath in new_photos:
            final_photos.append(new_photos[fpath])
        elif fpath in cached_lookup:
            final_photos.append(cached_lookup[fpath])

    # Remove deleted files (anything in cache but not on disk is already excluded)
    removed = len(cached_lookup) - (len(final_photos) - new_count)
    if removed > 0:
        log.info(f"PHOTOS removed {removed} deleted files from manifest")

    photo_manifest["photos"] = final_photos
    photo_manifest["lastScan"] = time.strftime("%Y-%m-%d %H:%M:%S")
    photo_manifest["scanning"] = False
    photo_manifest.pop("error", None)
    save_manifest()
    log.info(f"PHOTOS scan complete: {len(final_photos)} total ({new_count} processed)")

def start_scan_thread(full=False):
    try:
        cfg = load_config()
    except Exception as e:
        log.error(f"PHOTOS scan aborted — could not load config: {e}")
        return
    photo_path = cfg["photos"]["path"]
    if not photo_path:
        return
    include_sub = cfg["photos"]["includeSubfolders"]
    t = threading.Thread(target=scan_photos, args=(photo_path, include_sub, full), daemon=True)
    t.start()

def auto_scan_loop():
    """Background thread for periodic scanning."""
    while True:
        try:
            cfg = load_config()
            interval = cfg["photos"]["scanInterval"]
            if interval > 0 and cfg["photos"]["path"]:
                scan_photos(cfg["photos"]["path"], cfg["photos"]["includeSubfolders"])
            time.sleep(max(interval * 60, 60))
        except Exception as e:
            log.error(f"AUTO_SCAN loop error (will retry in 60s): {e}")
            time.sleep(60)

# Load cache on startup, then start auto-scan
load_cached_manifest()
threading.Thread(target=auto_scan_loop, daemon=True).start()

# ==================== WEATHER ====================
weather_cache = {"data": None, "lastFetch": 0}

def fetch_weather(cfg):
    """Fetch weather from Open-Meteo or OpenWeatherMap."""
    log.debug(f"WEATHER fetching from {cfg['weather']['source']} for {cfg['weather'].get('city', '?')}")
    try:
        city = cfg["weather"].get("city", "Seattle, WA")
        unit = cfg["weather"].get("unit", "f")

        if cfg["weather"]["source"] == "openmeteo":
            # Geocode city
            geo = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city.split(",")[0].strip(), "count": 1},
                timeout=10
            ).json()
            if not geo.get("results"):
                return None
            lat = geo["results"][0]["latitude"]
            lon = geo["results"][0]["longitude"]

            temp_unit = "fahrenheit" if unit == "f" else "celsius"
            resp = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon,
                    "hourly": "temperature_2m,weathercode,relative_humidity_2m,windspeed_10m,precipitation_probability",
                    "daily": "temperature_2m_max,temperature_2m_min,weathercode,precipitation_probability_max",
                    "current_weather": True,
                    "temperature_unit": temp_unit,
                    "windspeed_unit": "mph",
                    "timezone": "auto",
                    "forecast_days": 7
                },
                timeout=10
            ).json()
            weather_cache["data"] = resp
            weather_cache["lastFetch"] = time.time()
            return resp

        elif cfg["weather"]["source"] == "openweather":
            api_key = cfg["weather"].get("apiKey", "")
            if not api_key:
                return None
            units = "imperial" if unit == "f" else "metric"
            resp = requests.get(
                "https://api.openweathermap.org/data/2.5/forecast",
                params={"q": city, "appid": api_key, "units": units},
                timeout=10
            ).json()
            weather_cache["data"] = resp
            weather_cache["lastFetch"] = time.time()
            return resp
    except Exception as e:
        log.error(f"WEATHER fetch failed: {e}")
        return {"error": str(e)}

# ==================== NEWS ====================
news_cache = {"articles": [], "lastFetch": 0}

def fetch_news(feeds):
    """Fetch and merge RSS feeds."""
    import random
    articles = []
    for feed_url in feeds:
        feed_url = feed_url.strip()
        if not feed_url:
            continue
        try:
            feed = feedparser.parse(feed_url)
            source = feed.feed.get("title", "News")
            # Shorten common source names
            if "WSJ" in source or "Wall Street" in source:
                # Differentiate WSJ feeds by URL
                if "WorldNews" in feed_url: source = "WSJ World"
                elif "Markets" in feed_url: source = "WSJ Markets"
                elif "RSSWSJD" in feed_url: source = "WSJ Tech"
                elif "USBusiness" in feed_url: source = "WSJ Business"
                else: source = "WSJ"
            for entry in feed.entries[:10]:
                articles.append({
                    "source": source,
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                })
        except Exception as e:
            log.warning(f"NEWS error fetching {feed_url}: {e}")
            continue
    # Shuffle so all feeds are mixed together
    random.shuffle(articles)
    log.info(f"NEWS fetched {len(articles)} articles from {len(feeds)} feeds")
    news_cache["articles"] = articles[:40]
    news_cache["lastFetch"] = time.time()
    return articles[:40]

# ==================== GOOGLE CALENDAR ====================
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"

def get_calendar_service():
    """Get authenticated Google Calendar service."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        if not TOKEN_FILE.exists():
            return None
        with open(TOKEN_FILE) as f:
            token_data = json.load(f)

        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes")
        )
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            token_data["token"] = creds.token
            with open(TOKEN_FILE, "w") as f:
                json.dump(token_data, f)
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        log.error(f"CALENDAR error: {e}")
        return None

def fetch_calendar_events(days=3):
    """Fetch upcoming calendar events."""
    service = get_calendar_service()
    if not service:
        return []
    try:
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        result = service.events().list(
            calendarId="primary", timeMin=now, timeMax=end,
            maxResults=50, singleEvents=True, orderBy="startTime"
        ).execute()
        return result.get("items", [])
    except Exception:
        return []

# ==================== COMMUTE ====================
def fetch_commute(origin, destination, api_key):
    """Fetch commute time from Google Directions API."""
    if not api_key or not origin or not destination:
        return None
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/directions/json",
            params={
                "origin": origin, "destination": destination,
                "departure_time": "now", "key": api_key
            },
            timeout=10
        ).json()
        if resp["status"] == "OK":
            leg = resp["routes"][0]["legs"][0]
            duration = leg.get("duration_in_traffic", leg["duration"])
            return {
                "duration": duration["text"],
                "durationValue": duration["value"],
                "distance": leg["distance"]["text"],
                "summary": resp["routes"][0]["summary"]
            }
    except Exception:
        pass
    return None

# ==================== ROUTES ====================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/remote")
def remote():
    return render_template("remote.html")

@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(load_config())

@app.route("/api/config", methods=["POST"])
def update_config():
    cfg = request.get_json(silent=True)
    if not isinstance(cfg, dict):
        return jsonify({"ok": False, "error": "Invalid JSON body"}), 400
    save_config(cfg)
    return jsonify({"ok": True})

@app.route("/api/photos")
def get_photos():
    log.debug(f"PHOTOS serving manifest: {len(photo_manifest.get('photos', []))} photos, scanning={photo_manifest.get('scanning')}")
    # Try live manifest, fall back to cache
    if photo_manifest["photos"]:
        return jsonify(photo_manifest)
    cache_file = CACHE_DIR / "photo_manifest.json"
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                cached = json.load(f)
            cached["fromCache"] = True
            return jsonify(cached)
        except Exception as e:
            log.warning(f"PHOTOS failed to read cache file: {e}")
    return jsonify({"photos": [], "lastScan": None})

@app.route("/api/photos/scan", methods=["POST"])
def trigger_scan():
    full = request.args.get("full", "false") == "true"
    log.info(f"PHOTOS scan triggered (full={full})")
    start_scan_thread(full=full)
    return jsonify({"ok": True, "message": "Full scan started" if full else "Incremental scan started"})

@app.route("/api/photo/<photo_id>")
def serve_photo(photo_id):
    for p in photo_manifest["photos"]:
        if p["id"] == photo_id:
            filepath = p["path"]
            if not Path(filepath).exists():
                log.warning(f"PHOTOS file missing from disk: {filepath}")
                return "File not found", 404
            ext = Path(filepath).suffix.lower()
            if ext in VIDEO_EXT:
                mime = {"mp4": "video/mp4", "mov": "video/quicktime", "avi": "video/x-msvideo", "mkv": "video/x-matroska", "webm": "video/webm"}
                return send_file(filepath, mimetype=mime.get(ext.lstrip("."), "video/mp4"))
            if ext in HEIC_EXT:
                cache_path = CACHE_DIR / f"{photo_id}.jpg"
                if not cache_path.exists():
                    try:
                        from pillow_heif import register_heif_opener
                        register_heif_opener()
                        img = Image.open(filepath)
                        img.save(str(cache_path), "JPEG", quality=90)
                        img.close()
                    except Exception as e:
                        return f"Error converting HEIC: {e}", 500
                return send_file(str(cache_path), mimetype="image/jpeg")
            if ext in RAW_EXT:
                # Convert RAW to JPEG on the fly, cache it
                cache_path = CACHE_DIR / f"{photo_id}.jpg"
                if not cache_path.exists():
                    try:
                        import rawpy
                        with rawpy.imread(filepath) as raw:
                            rgb = raw.postprocess()
                        img = Image.fromarray(rgb)
                        img.save(str(cache_path), "JPEG", quality=85)
                    except Exception as e:
                        return f"Error converting RAW: {e}", 500
                return send_file(str(cache_path), mimetype="image/jpeg")
            return send_file(filepath, mimetype="image/jpeg")
    return "Not found", 404

@app.route("/api/browse")
def browse_folder():
    """List directories for folder browser."""
    path = request.args.get("path", "")
    if not path:
        # Return drive letters on Windows
        import string
        drives = []
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if Path(drive).exists():
                drives.append({"name": f"{letter}:", "path": drive})
        return jsonify({"folders": drives, "current": ""})
    try:
        p = Path(path)
        if not p.exists():
            return jsonify({"folders": [], "current": path, "error": "Path not found"})
        folders = []
        for item in sorted(p.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                folders.append({"name": item.name, "path": str(item)})
        return jsonify({"folders": folders[:100], "current": str(p), "parent": str(p.parent)})
    except Exception as e:
        return jsonify({"folders": [], "current": path, "error": str(e)})

@app.route("/api/resolve-folder")
def resolve_folder():
    """Try to find a folder by name on common drives."""
    name = request.args.get("name", "")
    if not name:
        return jsonify({"path": ""})
    import string
    for letter in string.ascii_uppercase:
        candidate = Path(f"{letter}:\\{name}")
        if candidate.exists() and candidate.is_dir():
            return jsonify({"path": str(candidate)})
    # Also check user folders
    for base in [Path.home(), Path.home() / "Pictures", Path.home() / "Documents"]:
        candidate = base / name
        if candidate.exists() and candidate.is_dir():
            return jsonify({"path": str(candidate)})
    return jsonify({"path": ""})

@app.route("/api/detect-location")
def detect_location():
    """Auto-detect location via IP geolocation."""
    try:
        r = requests.get("https://ipapi.co/json/", timeout=5).json()
        city = r.get("city", "")
        region = r.get("region", "")
        return jsonify({"city": f"{city}, {region}" if region else city})
    except Exception:
        return jsonify({"city": "", "error": "Could not detect location"})

@app.route("/api/autocomplete/city")
def autocomplete_city():
    """City name autocomplete via Open-Meteo geocoding."""
    q = request.args.get("q", "")
    if len(q) < 2:
        return jsonify({"results": []})
    try:
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": q, "count": 6, "language": "en"},
            timeout=5
        ).json()
        results = []
        for item in r.get("results", []):
            name = item.get("name", "")
            admin = item.get("admin1", "")
            country = item.get("country", "")
            label = f"{name}, {admin}" if admin else f"{name}, {country}"
            results.append(label)
        return jsonify({"results": results})
    except Exception:
        return jsonify({"results": []})

@app.route("/api/autocomplete/address")
def autocomplete_address():
    """Address autocomplete via Google Places API (if Maps key available)."""
    q = request.args.get("q", "")
    cfg = load_config()
    api_key = cfg["commute"].get("googleMapsApiKey", "")
    if len(q) < 3 or not api_key:
        return jsonify({"results": []})
    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/place/autocomplete/json",
            params={"input": q, "key": api_key, "types": "address"},
            timeout=5
        ).json()
        results = [p["description"] for p in r.get("predictions", [])[:6]]
        return jsonify({"results": results})
    except Exception:
        return jsonify({"results": []})

@app.route("/api/youtube/search")
def youtube_search():
    """Search YouTube for music videos."""
    q = request.args.get("q", "")
    if len(q) < 2:
        return jsonify({"results": []})
    try:
        # Use YouTube Data API v3 (free quota)
        api_key = None
        # Try dedicated YouTube API key first, then fall back to Maps key
        cfg = load_config()
        api_key = cfg.get("music", {}).get("youtubeApiKey", "")
        if not api_key:
            api_key = cfg["commute"].get("googleMapsApiKey", "")
        if not api_key:
            # Fallback: try a simple scrape-free approach
            return jsonify({"results": [], "error": "No API key. Add Google Maps API key in Commute settings (same project)."})

        r = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet", "q": f"{q} music", "type": "video",
                "videoCategoryId": "10", "maxResults": 6, "key": api_key
            },
            timeout=10
        ).json()
        results = []
        for item in r.get("items", []):
            results.append({
                "videoId": item["id"]["videoId"],
                "title": item["snippet"]["title"],
                "channel": item["snippet"]["channelTitle"],
                "thumbnail": item["snippet"]["thumbnails"]["default"]["url"]
            })
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"results": [], "error": str(e)})

@app.route("/api/weather")
def get_weather():
    cfg = load_config()
    force = request.args.get("force", "false") == "true"
    if not force and time.time() - weather_cache["lastFetch"] < 600 and weather_cache["data"]:
        return jsonify(weather_cache["data"])
    data = fetch_weather(cfg)
    return jsonify(data or {"error": "Failed to fetch weather"})

@app.route("/api/news")
def get_news():
    cfg = load_config()
    force = request.args.get("force", "false") == "true"
    if not force and time.time() - news_cache["lastFetch"] < cfg["news"]["refreshInterval"] * 60:
        return jsonify({"articles": news_cache["articles"]})
    articles = fetch_news(cfg["news"]["feeds"])
    return jsonify({"articles": articles})

stock_cache = {"articles": [], "lastFetch": 0}

@app.route("/api/stocks")
def get_stocks():
    cfg = load_config()
    force = request.args.get("force", "false") == "true"
    feeds = cfg.get("stocks", {}).get("feeds", [])
    if not feeds:
        return jsonify({"articles": []})
    if not force and time.time() - stock_cache["lastFetch"] < 600 and stock_cache["articles"]:
        return jsonify({"articles": stock_cache["articles"]})
    articles = []
    import random
    for feed_url in feeds:
        feed_url = feed_url.strip()
        if not feed_url:
            continue
        try:
            feed = feedparser.parse(feed_url)
            source = feed.feed.get("title", "Stocks")
            for entry in feed.entries[:15]:
                articles.append({"source": source, "title": entry.get("title", "")})
        except Exception:
            continue
    random.shuffle(articles)
    stock_cache["articles"] = articles[:30]
    stock_cache["lastFetch"] = time.time()
    return jsonify({"articles": articles[:30]})

@app.route("/api/calendar")
def get_calendar():
    cfg = load_config()
    events = fetch_calendar_events(cfg["calendar"]["daysToShow"])
    return jsonify({"events": events})

@app.route("/api/commute")
def get_commute():
    cfg = load_config()
    api_key = cfg["commute"].get("googleMapsApiKey", "")
    results = {}
    from datetime import datetime
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    is_weekday = weekday < 5

    for key in ["commute1", "commute2"]:
        c = cfg["commute"][key]
        if not c["enabled"] or not c["from"] or not c["to"]:
            continue
        schedule = c.get("schedule", "always")
        show = False
        if schedule == "always":
            show = True
        elif schedule == "morning" and is_weekday and 6 <= hour < 9:
            show = True
        elif schedule == "evening" and is_weekday and 16 <= hour < 19:
            show = True
        elif schedule == "both" and is_weekday and (6 <= hour < 9 or 16 <= hour < 19):
            show = True
        if show:
            results[key] = fetch_commute(c["from"], c["to"], api_key)
    return jsonify(results)

# ==================== NOTES API ====================
@app.route("/api/notes", methods=["GET"])
def get_notes():
    return jsonify({"notes": load_notes()})

@app.route("/api/notes", methods=["POST"])
def add_note():
    data = request.get_json(silent=True) or {}
    notes = load_notes()
    note = {
        "id": hashlib.md5(f"{time.time()}{data.get('text','')}".encode()).hexdigest()[:10],
        "text": data.get("text", ""),
        "color": data.get("color", "#fbbc04"),
        "author": data.get("author", "Anonymous"),
        "pinned": False,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    notes.insert(0, note)
    save_notes(notes)
    log.info(f"NOTES added note '{note['text'][:50]}' by {note['author']}")
    return jsonify(note)

@app.route("/api/notes/<note_id>", methods=["DELETE"])
def delete_note(note_id):
    notes = load_notes()
    before = len(notes)
    notes = [n for n in notes if n["id"] != note_id]
    save_notes(notes)
    log.info(f"NOTES deleted note {note_id} ({before} -> {len(notes)})")
    return jsonify({"ok": True})

@app.route("/api/notes/<note_id>/pin", methods=["POST"])
def pin_note(note_id):
    notes = load_notes()
    for n in notes:
        if n["id"] == note_id:
            n["pinned"] = not n.get("pinned", False)
            log.info(f"NOTES {'pinned' if n['pinned'] else 'unpinned'} note {note_id}")
    save_notes(notes)
    return jsonify({"ok": True})

# ==================== GOOGLE OAUTH ====================
@app.route("/oauth/start")
def oauth_start():
    log.info("OAUTH starting Google Calendar authorization")
    if not CREDENTIALS_FILE.exists():
        return jsonify({"error": "credentials.json not found. Place it in the app folder."})
    try:
        import hashlib, base64, secrets
        with open(CREDENTIALS_FILE) as f:
            cred_data = json.load(f)
        client = cred_data.get("web", cred_data.get("installed", {}))
        client_id = client["client_id"]
        client_secret = client.get("client_secret", "")

        # Generate PKCE
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b'=').decode()

        # Store in a file instead of session (more reliable)
        oauth_state = {"code_verifier": code_verifier, "client_id": client_id, "client_secret": client_secret}
        with open(BASE_DIR / "oauth_state.json", "w") as f:
            json.dump(oauth_state, f)

        auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={client_id}"
            f"&redirect_uri=http://localhost:5000/oauth/callback"
            f"&response_type=code"
            f"&scope=https://www.googleapis.com/auth/calendar.readonly"
            f"&access_type=offline"
            f"&prompt=consent"
            f"&code_challenge={code_challenge}"
            f"&code_challenge_method=S256"
        )
        return redirect(auth_url)
    except Exception as e:
        return f"OAuth error: {e}"

@app.route("/oauth/callback")
def oauth_callback():
    try:
        code = request.args.get("code")
        if not code:
            return "OAuth error: No code received"

        # Read stored state
        state_file = BASE_DIR / "oauth_state.json"
        if not state_file.exists():
            return "OAuth error: State lost. Try again."
        with open(state_file) as f:
            oauth_state = json.load(f)

        # Exchange code for token
        token_resp = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": oauth_state["client_id"],
            "client_secret": oauth_state["client_secret"],
            "code": code,
            "code_verifier": oauth_state["code_verifier"],
            "grant_type": "authorization_code",
            "redirect_uri": "http://localhost:5000/oauth/callback"
        }).json()

        # Clean up state file
        state_file.unlink(missing_ok=True)

        if "error" in token_resp:
            return f"OAuth error: {token_resp['error']} - {token_resp.get('error_description', '')}"

        # Save token
        token_data = {
            "token": token_resp["access_token"],
            "refresh_token": token_resp.get("refresh_token"),
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": oauth_state["client_id"],
            "client_secret": oauth_state["client_secret"],
            "scopes": ["https://www.googleapis.com/auth/calendar.readonly"]
        }
        with open(TOKEN_FILE, "w") as f:
            json.dump(token_data, f)

        cfg = load_config()
        cfg["calendar"]["connected"] = True
        save_config(cfg)
        log.info("OAUTH Google Calendar connected successfully")
        return redirect("/")
    except Exception as e:
        log.error(f"OAUTH callback error: {e}")
        return f"OAuth error: {e}"

# ==================== VOICE ASSISTANT (GEMINI) ====================
voice_history = []

@app.route("/api/voice", methods=["POST"])
def voice_command():
    global voice_history
    try:
        data = request.json
        user_text = data.get("text", "")
        if not user_text:
            return jsonify({"error": "No text provided"})

        log.info(f"VOICE command: '{user_text}'")
        cfg = load_config()
        gemini_key = cfg.get("voice", {}).get("geminiApiKey", "")
        model_name = cfg.get("voice", {}).get("model", "gemini-2.5-flash-lite")

        if not gemini_key:
            log.warning("VOICE no Gemini API key configured")
            return jsonify({"error": "No Gemini API key configured. Add it in Settings → Voice Assistant."})

        from google import genai
        log.debug(f"VOICE calling Gemini model={model_name}")
        for h in log.handlers:
            h.flush()
        client = genai.Client(api_key=gemini_key)

        # Gather current dashboard context
        context_parts = []

        # Weather
        if weather_cache.get("data") and not weather_cache["data"].get("error"):
            wd = weather_cache["data"]
            cw = wd.get("current_weather", {})
            context_parts.append(f"Weather now: {cw.get('temperature', '?')}°, code {cw.get('weathercode', 0)}, wind {cw.get('windspeed', 0)}mph")
            daily = wd.get("daily", {})
            if daily.get("time"):
                for i in range(min(3, len(daily["time"]))):
                    context_parts.append(f"Weather {daily['time'][i]}: high {daily['temperature_2m_max'][i]}°, low {daily['temperature_2m_min'][i]}°, code {daily['weathercode'][i]}")

        # Calendar
        try:
            events = fetch_calendar_events(cfg["calendar"]["daysToShow"])
            for ev in events[:8]:
                start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
                summary = ev.get("summary", "No title")
                context_parts.append(f"Calendar: {summary} at {start}")
        except Exception:
            pass

        # Notes
        notes = load_notes()
        for n in notes[:5]:
            pinned = " (PINNED)" if n.get("pinned") else ""
            context_parts.append(f"Note{pinned}: {n['text']} — by {n.get('author', '?')}")

        context_str = "\n".join(context_parts) if context_parts else "No dashboard data available."

        # Build conversation
        system_prompt = f"""You are a friendly family dashboard voice assistant. You control a wall-mounted display showing photos, weather, calendar, news, music, and notes.

Available actions (respond with exactly one in your JSON):
- {{"action":"play_music","query":"search term"}} — search and play music
- {{"action":"pause_music"}} — pause current music
- {{"action":"resume_music"}} — resume paused music
- {{"action":"next_song"}} — skip to next song
- {{"action":"volume_up"}} or {{"action":"volume_down"}}
- {{"action":"show_calendar","view":"agenda|week|month"}}
- {{"action":"show_weather","view":"hourly|daily|weekly"}}
- {{"action":"add_note","text":"note content","pin":false}}
- {{"action":"pin_note"}} — pin most recent note to overlay
- {{"action":"hide_note"}} — unpin/hide note overlay
- {{"action":"show_notes"}} — open notes panel
- {{"action":"next_photo"}} — skip to next slideshow photo
- {{"action":"prev_photo"}} — go to previous slideshow photo
- {{"action":"pause_slideshow"}} — pause the photo slideshow
- {{"action":"resume_slideshow"}} — resume the photo slideshow
- {{"action":"set_volume","level":0-100}} — set system volume (0-100)
- {{"action":"close_panels"}} — close any open panel
- {{"action":"mute"}} or {{"action":"unmute"}} — toggle system mute
- {{"action":"none"}} — just respond verbally, no UI change

Current dashboard data:
{context_str}

IMPORTANT: Respond ONLY with valid JSON in this format:
{{"speech":"your spoken response","action":"action_name",...additional params}}

Keep responses natural, warm, and concise (1-3 sentences). You can answer general knowledge questions too using action "none"."""

        # Build messages with history
        messages = []
        for h in voice_history[-10:]:
            messages.append({"role": "user", "parts": [{"text": h["user"]}]})
            messages.append({"role": "model", "parts": [{"text": h["ai"]}]})
        messages.append({"role": "user", "parts": [{"text": user_text}]})

        response = client.models.generate_content(
            model=model_name,
            contents=messages,
            config={"system_instruction": system_prompt}
        )

        ai_text = response.text.strip()
        # Try to parse JSON from response
        import re
        json_match = re.search(r'\{.*\}', ai_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = {"speech": ai_text, "action": "none"}

        # Store in history
        voice_history.append({"user": user_text, "ai": json.dumps(result)})
        if len(voice_history) > 20:
            voice_history = voice_history[-10:]

        log.info(f"VOICE response: action={result.get('action')}, speech='{result.get('speech', '')[:80]}'")
        return jsonify(result)

    except Exception as e:
        log.error(f"VOICE error: {e}")
        return jsonify({"speech": f"Sorry, I had trouble with that. {str(e)[:100]}", "action": "none", "error": str(e)})

@app.route("/api/voice/reset", methods=["POST"])
def voice_reset():
    global voice_history
    voice_history = []
    log.info("VOICE history reset")
    return jsonify({"ok": True})

# ==================== NETWORK STATUS ====================
@app.route("/api/status")
def network_status():
    cfg = load_config()
    import socket
    status = {
        "internet": False,
        "nas": False,
        "ip": "",
        "weather": {"ok": False, "error": "", "lastFetch": weather_cache.get("lastFetch", 0)},
        "news": {"ok": False, "count": 0, "lastFetch": news_cache.get("lastFetch", 0)},
        "calendar": {"ok": False, "error": ""},
        "commute": {"ok": False, "error": ""},
        "youtube": {"ok": False, "error": ""},
        "voice": {"ok": False, "error": ""},
        "photos": {"ok": False, "count": len(photo_manifest.get("photos", [])), "scanning": photo_manifest.get("scanning", False)}
    }

    # IP address
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        status["ip"] = s.getsockname()[0]
        s.close()
    except Exception:
        status["ip"] = "unknown"

    # Internet
    try:
        requests.get("https://dns.google", timeout=3)
        status["internet"] = True
    except Exception:
        pass

    # NAS
    nas_path = cfg.get("photos", {}).get("path", "")
    if nas_path:
        status["nas"] = Path(nas_path).exists()
        status["photos"]["ok"] = status["nas"] and len(photo_manifest.get("photos", [])) > 0
    else:
        status["nas"] = True
        status["photos"]["ok"] = len(photo_manifest.get("photos", [])) > 0

    # Weather
    wd = weather_cache.get("data")
    if wd and not (isinstance(wd, dict) and wd.get("error")):
        status["weather"]["ok"] = True
    elif isinstance(wd, dict) and wd.get("error"):
        status["weather"]["error"] = str(wd["error"])[:100]

    # News
    if news_cache.get("articles"):
        status["news"]["ok"] = True
        status["news"]["count"] = len(news_cache["articles"])

    # Calendar
    if cfg.get("calendar", {}).get("connected"):
        if TOKEN_FILE.exists():
            status["calendar"]["ok"] = True
        else:
            status["calendar"]["error"] = "Token missing"
    else:
        status["calendar"]["error"] = "Not connected"

    # Commute
    api_key = cfg.get("commute", {}).get("googleMapsApiKey", "")
    if api_key:
        status["commute"]["ok"] = True
    else:
        status["commute"]["error"] = "No API key"

    # YouTube
    yt_key = cfg.get("music", {}).get("youtubeApiKey", "")
    if yt_key:
        status["youtube"]["ok"] = True
    else:
        status["youtube"]["error"] = "No API key"

    # Voice
    gemini_key = cfg.get("voice", {}).get("geminiApiKey", "")
    if gemini_key:
        status["voice"]["ok"] = True
    else:
        status["voice"]["error"] = "No API key"

    return jsonify(status)

# ==================== SYSTEM VOLUME ====================
def _get_volume_interface():
    """Get Windows audio endpoint volume interface using pycaw."""
    import comtypes
    comtypes.CoInitialize()
    from pycaw.pycaw import AudioUtilities
    import pycaw.pycaw as pycaw_mod
    speakers = AudioUtilities.GetSpeakers()
    obj = speakers
    for attr in ['Activate', '_dev', 'iunknown']:
        if hasattr(obj, 'Activate'):
            break
        if hasattr(obj, attr):
            obj = getattr(obj, attr)
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume
    interface = obj.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))

def _with_volume(fn):
    """Run fn(volume_interface) with proper COM init/cleanup."""
    import comtypes
    comtypes.CoInitialize()
    try:
        volume = _get_volume_interface()
        return fn(volume)
    finally:
        comtypes.CoUninitialize()

@app.route("/api/volume", methods=["GET"])
def get_volume():
    try:
        def _get(vol):
            v = int(vol.GetMasterVolumeLevelScalar() * 100)
            m = vol.GetMute()
            return jsonify({"volume": v, "muted": bool(m)})
        return _with_volume(_get)
    except Exception as e:
        log.warning(f"VOLUME get error: {e}")
        return jsonify({"volume": 50, "muted": False, "error": str(e)})

@app.route("/api/volume", methods=["POST"])
def set_volume():
    data = request.get_json(silent=True) or {}
    vol = max(0, min(100, int(data.get("volume", 50))))
    try:
        def _set(v):
            v.SetMasterVolumeLevelScalar(vol / 100, None)
            return jsonify({"ok": True, "volume": vol})
        return _with_volume(_set)
    except Exception as e:
        log.warning(f"VOLUME set error: {e}")
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/volume/mute", methods=["POST"])
def toggle_mute():
    try:
        def _mute(vol):
            current = vol.GetMute()
            vol.SetMute(not current, None)
            return jsonify({"ok": True, "muted": not current})
        return _with_volume(_mute)
    except Exception as e:
        log.warning(f"VOLUME mute error: {e}")
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/screen/off", methods=["POST"])
def screen_off():
    """Turn off the monitor (Windows only)."""
    try:
        import subprocess
        # Send monitor to sleep using PowerShell
        subprocess.run(
            ["powershell", "-Command",
             "(Add-Type '[DllImport(\"user32.dll\")]public static extern int SendMessage(int hWnd,int hMsg,int wParam,int lParam);' -Name a -Pas)::SendMessage(-1,0x0112,0xF170,2)"],
            capture_output=True, timeout=5
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/api/screen/on", methods=["POST"])
def screen_on():
    """Wake up the monitor (Windows only)."""
    try:
        import subprocess
        subprocess.run(
            ["powershell", "-Command",
             "(Add-Type '[DllImport(\"user32.dll\")]public static extern int SendMessage(int hWnd,int hMsg,int wParam,int lParam);' -Name b -Pas)::SendMessage(-1,0x0112,0xF170,-1)"],
            capture_output=True, timeout=5
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

# ==================== MAIN ====================
if __name__ == "__main__":
    # Initial scan on startup
    cfg = load_config()
    log.info(f"CONFIG loaded — photos path: '{cfg['photos']['path']}', weather: {cfg['weather']['source']}, voice: {'enabled' if cfg.get('voice', {}).get('enabled') else 'disabled'}")
    if cfg["photos"]["path"]:
        log.info("PHOTOS starting initial scan thread")
        start_scan_thread()
    
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # Allow HTTP for localhost OAuth
    log.info("SERVER starting on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
