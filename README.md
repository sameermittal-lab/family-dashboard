# Family Dashboard

A wall-mounted photo frame and family hub — photos, weather, calendar, news, music, notes, voice assistant, and commute times in one beautiful display.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![Flask](https://img.shields.io/badge/Flask-3.0+-green) ![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **Photo Slideshow** — NAS/local photos with face-centered cropping, portrait pairing, HEIC/RAW/video support, configurable transitions
- **Clock & Date** — Customizable font, size, color, position, 12/24h format
- **Weather** — Open-Meteo (free, no API key) or OpenWeatherMap, hourly/daily/weekly views
- **News Ticker** — RSS feeds with content-aware scroll speed, configurable font and size
- **Stock Ticker** — Separate RSS-based stock news ticker
- **Google Calendar** — OAuth integration with agenda, week, and month views
- **YouTube Music** — Search and play music via YouTube Data API
- **Voice Assistant** — Gemini-powered, controls the entire dashboard via natural language
- **Family Notes** — Add, pin (multiple), and display notes on the slideshow overlay
- **Commute Times** — Google Maps Directions API with schedule-based display
- **Remote Control** — Phone-friendly web UI at `/remote`
- **Virtual Keyboard** — Touch-friendly on-screen keyboard for kiosk use
- **Display Controls** — Auto-hide, burn-in protection, screen scheduling, overlay themes

## Quick Start

### Prerequisites

- Python 3.10+
- Chrome browser (for kiosk mode)

### Install

```bash
cd family-dashboard
pip install -r requirements.txt
cp config.example.json config.json
```

### Run

```bash
python app.py
```

Open http://localhost:5000 in your browser. For kiosk mode:

```bash
chrome --kiosk --app=http://localhost:5000
```

Or on Windows, double-click `start.bat` (auto-restarts on crash).

### Remote Control

From your phone, open `http://<YOUR-PC-IP>:5000/remote`

## Configuration

All settings are managed through the in-app Settings panel (click the gear icon). Configuration is stored in `config.json`.

Copy `config.example.json` to `config.json` to get started with defaults.

### API Keys (all optional)

| Service | Key | Free Tier |
|---------|-----|-----------|
| Weather | None needed | Open-Meteo is free, no key required |
| Google Calendar | OAuth credentials | Free (Google Cloud Console) |
| Commute | Google Maps API key | $200/month free credit |
| YouTube Music | YouTube Data API key | 10,000 units/day free |
| Voice Assistant | Gemini API key | Free tier at aistudio.google.com |

### Google Calendar Setup

1. Create a project in [Google Cloud Console](https://console.cloud.google.com)
2. Enable the Google Calendar API
3. Create OAuth 2.0 credentials (Web application type)
4. Add `http://localhost:5000/oauth/callback` as an authorized redirect URI
5. Download the credentials JSON and save as `credentials.json` in the app folder
6. In the dashboard, go to Settings → Google Calendar → Connect

## Architecture

```
family-dashboard/
├── app.py                 # Flask backend (API, photo scanning, weather, voice, etc.)
├── config.json            # User configuration (gitignored)
├── config.example.json    # Template configuration
├── requirements.txt       # Python dependencies
├── start.bat              # Windows launcher with auto-restart
├── setup.bat              # One-time Windows setup (deps + auto-start)
├── static/
│   ├── app.js             # Frontend application (~2400 lines)
│   └── styles.css         # UI styles (frosted glass theme)
├── templates/
│   ├── index.html         # Main dashboard
│   └── remote.html        # Phone remote control
├── docs/
│   └── documentation.html # Detailed documentation
└── logs/                  # Auto-created, rotating log files
```

## Logging

Logs are written to `logs/dashboard.log` with automatic rotation (5 MB, 3 backups). Covers all subsystems: photos, weather, news, calendar, voice, notes, volume, and startup.

## Kiosk Setup (Windows)

Run `setup.bat` to install dependencies and create a Windows startup shortcut. The dashboard will auto-launch on boot in Chrome kiosk mode.

`configure-kiosk.bat` provides additional kiosk hardening options.

## License

MIT
