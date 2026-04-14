"""Family Dashboard — Flask Backend"""
import os
import json
import time
import threading
import hashlib
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

# ==================== CONFIG ====================
def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=4)

# ==================== NOTES ====================
def load_notes():
    if NOTES_PATH.exists():
        with open(NOTES_PATH, "r") as f:
            return json.load(f)
    return []

def save_notes(notes):
    with open(NOTES_PATH, "w") as f:
        json.dump(notes, f, indent=2)

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
            print(f"[PHOTOS] Loaded {len(photo_manifest['photos'])} photos from cache")
        except Exception as e:
            print(f"[PHOTOS] Failed to load cache: {e}")

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
        with Image.open(f) as img:
            w, h = img.size
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
    print(f"[PHOTOS] Found {len(all_files)} files, {new_count} new/changed to process")

    # Process new/changed files
    new_photos = {}
    for idx, f in enumerate(to_process):
        photo_manifest["scanProgress"] = idx + 1
        try:
            entry = process_single_file(f)
            new_photos[entry["path"]] = entry
        except Exception as e:
            print(f"[PHOTOS] Error processing {f.name}: {e}")
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
        print(f"[PHOTOS] Removed {removed} deleted files from manifest")

    photo_manifest["photos"] = final_photos
    photo_manifest["lastScan"] = time.strftime("%Y-%m-%d %H:%M:%S")
    photo_manifest["scanning"] = False
    photo_manifest.pop("error", None)
    save_manifest()
    print(f"[PHOTOS] Scan complete: {len(final_photos)} total ({new_count} processed)")

def start_scan_thread(full=False):
    cfg = load_config()
    photo_path = cfg["photos"]["path"]
    if not photo_path:
        return
    include_sub = cfg["photos"]["includeSubfolders"]
    t = threading.Thread(target=scan_photos, args=(photo_path, include_sub, full), daemon=True)
    t.start()

def auto_scan_loop():
    """Background thread for periodic scanning."""
    while True:
        cfg = load_config()
        interval = cfg["photos"]["scanInterval"]
        if interval > 0 and cfg["photos"]["path"]:
            scan_photos(cfg["photos"]["path"], cfg["photos"]["includeSubfolders"])
        time.sleep(max(interval * 60, 60))

# Load cache on startup, then start auto-scan
load_cached_manifest()
threading.Thread(target=auto_scan_loop, daemon=True).start()

# ==================== WEATHER ====================
weather_cache = {"data": None, "lastFetch": 0}

def fetch_weather(cfg):
    """Fetch weather from Open-Meteo or OpenWeatherMap."""
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
            print(f"[NEWS] Error fetching {feed_url}: {e}")
            continue
    # Shuffle so all feeds are mixed together
    random.shuffle(articles)
    print(f"[NEWS] Fetched {len(articles)} articles from {len(feeds)} feeds")
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
        print(f"[CALENDAR] Error: {e}")
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
    cfg = request.json
    save_config(cfg)
    return jsonify({"ok": True})

@app.route("/api/photos")
def get_photos():
    # Try live manifest, fall back to cache
    if photo_manifest["photos"]:
        return jsonify(photo_manifest)
    cache_file = CACHE_DIR / "photo_manifest.json"
    if cache_file.exists():
        with open(cache_file) as f:
            cached = json.load(f)
            cached["fromCache"] = True
            return jsonify(cached)
    return jsonify({"photos": [], "lastScan": None})

@app.route("/api/photos/scan", methods=["POST"])
def trigger_scan():
    full = request.args.get("full", "false") == "true"
    start_scan_thread(full=full)
    return jsonify({"ok": True, "message": "Full scan started" if full else "Incremental scan started"})

@app.route("/api/photo/<photo_id>")
def serve_photo(photo_id):
    for p in photo_manifest["photos"]:
        if p["id"] == photo_id:
            filepath = p["path"]
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
    data = request.json
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
    return jsonify(note)

@app.route("/api/notes/<note_id>", methods=["DELETE"])
def delete_note(note_id):
    notes = load_notes()
    notes = [n for n in notes if n["id"] != note_id]
    save_notes(notes)
    return jsonify({"ok": True})

@app.route("/api/notes/<note_id>/pin", methods=["POST"])
def pin_note(note_id):
    notes = load_notes()
    for n in notes:
        n["pinned"] = (n["id"] == note_id and not n.get("pinned", False))
    save_notes(notes)
    return jsonify({"ok": True})

# ==================== GOOGLE OAUTH ====================
@app.route("/oauth/start")
def oauth_start():
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
        return redirect("/")
    except Exception as e:
        return f"OAuth error: {e}"

# ==================== NETWORK STATUS ====================
@app.route("/api/status")
def network_status():
    cfg = load_config()
    status = {"internet": False, "nas": False}
    # Check internet
    try:
        requests.get("https://dns.google", timeout=3)
        status["internet"] = True
    except Exception:
        pass
    # Check NAS
    nas_path = cfg["photos"]["path"]
    if nas_path:
        status["nas"] = Path(nas_path).exists()
    else:
        status["nas"] = True  # No path configured, not an error
    return jsonify(status)

# ==================== MAIN ====================
if __name__ == "__main__":
    # Initial scan on startup
    cfg = load_config()
    if cfg["photos"]["path"]:
        start_scan_thread()
    
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # Allow HTTP for localhost OAuth
    app.run(host="0.0.0.0", port=5000, debug=False)
