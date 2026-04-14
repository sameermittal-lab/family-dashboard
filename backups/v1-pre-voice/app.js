/**
 * Family Dashboard — Main Application
 */
let config = {};
let photos = [];
let currentIndex = 0;
let slideshowTimer = null;
let overlaysVisible = true;
let cycleTimer = null;
let autohideTimer = null;

// ==================== INIT ====================
async function init() {
    config = await fetchJSON("/api/config");
    applyConfig();
    await loadPhotos();
    startSlideshow();
    startClock();
    loadWeather();
    loadNews();
    loadNotes();
    loadCommute();
    loadStocks();
    loadCalendar();
    checkNetwork();
    setupPanels();
    setupSettings();
    setupVirtualKeyboard();
    setupWeatherToggle();
    setupOverlayCycle();
    // Show/hide music widget
    if (config.music.show) document.getElementById("music-widget").style.display = "";
    setInterval(checkNetwork, 30000);
    setInterval(loadWeather, 600000);
    setInterval(loadCommute, 300000);
}

async function fetchJSON(url) {
    try {
        const r = await fetch(url);
        return await r.json();
    } catch { return null; }
}

// ==================== PHOTOS & SLIDESHOW ====================
async function loadPhotos() {
    const data = await fetchJSON("/api/photos");
    if (!data || !data.photos) return;
    if (data.scanning) {
        document.getElementById("photo-count").textContent = `Scanning... ${data.scanProgress || 0} of ${data.scanTotal || "?"}`;
        setTimeout(loadPhotos, 2000); // Poll again
        return;
    }
    photos = data.photos;
    if (config.slideshow.shuffle) shuffleArray(photos);
    const imageCount = photos.filter(p => p.type !== "video").length;
    const videoCount = photos.filter(p => p.type === "video").length;
    document.getElementById("photo-count").textContent = `${imageCount} photos, ${videoCount} videos`;
    document.getElementById("about-photos").textContent = `Photos: ${imageCount}, Videos: ${videoCount}`;
    document.getElementById("about-scan").textContent = `Last scan: ${data.lastScan || "Never"}`;
    if (data.fromCache) {
        document.getElementById("about-scan").textContent += " (cached)";
    }
}

function shuffleArray(arr) {
    for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [arr[i], arr[j]] = [arr[j], arr[i]];
    }
}

function renderSlide(container, index) {
    container.innerHTML = "";
    if (!photos.length) {
        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%;font-size:18px;opacity:0.4;">No photos — set your NAS path in Settings</div>';
        return;
    }

    const pairPortraits = config.slideshow.pairPortraits;
    const photo = photos[index % photos.length];

    if (pairPortraits && photo.orientation === "portrait") {
        // Find next portrait
        let nextIdx = (index + 1) % photos.length;
        let partner = null;
        for (let i = 0; i < photos.length; i++) {
            const candidate = photos[(index + 1 + i) % photos.length];
            if (candidate.orientation === "portrait" && candidate.id !== photo.id) {
                partner = candidate;
                break;
            }
        }
        if (partner) {
            const pair = document.createElement("div");
            pair.className = "portrait-pair";
            const img1 = document.createElement("img");
            img1.src = `/api/photo/${photo.id}`;
            img1.alt = photo.name;
            if (photo.focusX !== undefined) img1.style.objectPosition = `${photo.focusX}% ${photo.focusY}%`;
            const img2 = document.createElement("img");
            img2.src = `/api/photo/${partner.id}`;
            img2.alt = partner.name;
            if (partner.focusX !== undefined) img2.style.objectPosition = `${partner.focusX}% ${partner.focusY}%`;
            pair.appendChild(img1);
            pair.appendChild(img2);
            container.appendChild(pair);
            updatePhotoInfo(`${photo.name} + ${partner.name}`, "Portrait Pair");
            return;
        }
    }

    // Single photo or video (landscape or unpaired portrait)
    if (photo.type === "video") {
        const vid = document.createElement("video");
        vid.className = "slide-photo";
        vid.src = `/api/photo/${photo.id}`;
        vid.autoplay = true;
        vid.muted = config.slideshow.muteVideo !== false;
        vid.loop = false;
        vid.playsInline = true;
        // Auto-advance when video ends (if shorter than slideshow interval)
        vid.addEventListener("ended", () => {
            nextSlide();
            clearInterval(slideshowTimer);
            const ms = (config.slideshow.intervalMin * 60 + config.slideshow.intervalSec) * 1000;
            slideshowTimer = setInterval(nextSlide, Math.max(ms, 3000));
        });
        container.appendChild(vid);
    } else {
        const img = document.createElement("img");
        img.className = "slide-photo";
        img.src = `/api/photo/${photo.id}`;
        img.alt = photo.name;
        if (photo.focusX !== undefined && photo.focusY !== undefined) {
            img.style.objectPosition = `${photo.focusX}% ${photo.focusY}%`;
        }
        container.appendChild(img);
    }
    updatePhotoInfo(photo.name, `${(index % photos.length) + 1} of ${photos.length} · ${photo.type === "video" ? "Video" : photo.orientation}`);
}

function updatePhotoInfo(name, meta) {
    document.getElementById("photo-filename").textContent = name;
    document.getElementById("photo-meta").textContent = meta;
}

function nextSlide() {
    const cur = document.getElementById("slide-current");
    const nxt = document.getElementById("slide-next");
    currentIndex++;
    renderSlide(nxt, currentIndex);
    // Crossfade: show next, then after transition completes, move content to current
    nxt.classList.add("active");
    cur.classList.remove("active");
    setTimeout(() => {
        // Stop any video in the old slide
        cur.querySelectorAll("video").forEach(v => { v.pause(); v.src = ""; });
        // Move next content to current
        cur.innerHTML = nxt.innerHTML;
        // Re-trigger video play on the moved content
        cur.querySelectorAll("video").forEach(v => v.play());
        cur.classList.add("active");
        nxt.classList.remove("active");
        nxt.innerHTML = "";
    }, 1400);
    startProgress();
}

function startProgress() {
    const bar = document.getElementById("progress-bar");
    const duration = (config.slideshow.intervalMin * 60 + config.slideshow.intervalSec) * 1000;
    bar.style.transition = "none";
    bar.style.width = "0%";
    bar.offsetHeight;
    bar.style.transition = `width ${duration}ms linear`;
    bar.style.width = "100%";
}

function startSlideshow() {
    clearInterval(slideshowTimer);
    renderSlide(document.getElementById("slide-current"), currentIndex);
    startProgress();
    const ms = (config.slideshow.intervalMin * 60 + config.slideshow.intervalSec) * 1000;
    slideshowTimer = setInterval(nextSlide, Math.max(ms, 3000));
}

// ==================== CLOCK ====================
function startClock() {
    updateClock();
    setInterval(updateClock, 1000);
}

function updateClock() {
    if (!config.clock.show) {
        document.getElementById("clock-overlay").style.display = "none";
        return;
    }
    document.getElementById("clock-overlay").style.display = "";
    const now = new Date();
    let h = now.getHours(), m = now.getMinutes(), s = now.getSeconds();
    if (config.clock.format === "12") h = h % 12 || 12;
    let timeStr = `${h}:${m.toString().padStart(2, "0")}`;
    if (config.clock.showSeconds) timeStr += `:${s.toString().padStart(2, "0")}`;
    document.getElementById("clock-time").textContent = timeStr;

    if (config.clock.showDate) {
        document.getElementById("clock-date").style.display = "";
        const days = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
        const months = ["January","February","March","April","May","June","July","August","September","October","November","December"];
        const shortMonths = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
        const d = now.getDate(), day = days[now.getDay()], mon = months[now.getMonth()], smon = shortMonths[now.getMonth()];
        let dateStr = "";
        if (config.clock.dateFormat === "long") dateStr = `${day}, ${mon} ${d}`;
        else if (config.clock.dateFormat === "medium") dateStr = `${smon} ${d}, ${now.getFullYear()}`;
        else dateStr = `${(now.getMonth()+1).toString().padStart(2,"0")}/${d.toString().padStart(2,"0")}/${now.getFullYear()}`;
        document.getElementById("clock-date").textContent = dateStr;
    } else {
        document.getElementById("clock-date").style.display = "none";
    }
}

// ==================== WEATHER ====================
const WMO_CODES = {0:"☀️",1:"🌤️",2:"⛅",3:"☁️",45:"🌫️",48:"🌫️",51:"🌦️",53:"🌧️",55:"🌧️",61:"🌧️",63:"🌧️",65:"🌧️",71:"🌨️",73:"🌨️",75:"🌨️",77:"🌨️",80:"🌦️",81:"🌧️",82:"🌧️",85:"🌨️",86:"🌨️",95:"⛈️",96:"⛈️",99:"⛈️"};
const WMO_DESC = {0:"Clear",1:"Mostly Clear",2:"Partly Cloudy",3:"Overcast",45:"Foggy",48:"Fog",51:"Light Drizzle",53:"Drizzle",55:"Heavy Drizzle",61:"Light Rain",63:"Rain",65:"Heavy Rain",71:"Light Snow",73:"Snow",75:"Heavy Snow",80:"Showers",81:"Rain",82:"Heavy Rain",95:"Thunderstorm"};

async function loadWeather() {
    if (!config.weather.show) { document.getElementById("weather-widget").style.display = "none"; return; }
    const data = await fetchJSON("/api/weather");
    if (!data || data.error) return;
    document.getElementById("weather-widget").style.display = "";
    renderWeather(data);
}

function renderWeather(data) {
    const w = document.getElementById("weather-widget");
    const unit = config.weather.unit === "f" ? "°F" : "°C";
    const sym = config.weather.unit === "f" ? "°" : "°";
    const cw = data.current_weather || {};
    const code = cw.weathercode || 0;
    const icon = WMO_CODES[code] || "🌡️";
    const desc = WMO_DESC[code] || "Unknown";
    const temp = Math.round(cw.temperature || 0);
    const wind = Math.round(cw.windspeed || 0);

    const hourly = data.hourly || {};
    const daily = data.daily || {};
    const nowHour = new Date().getHours();

    let hourlyHTML = "";
    for (let i = 0; i < 8; i++) {
        const idx = nowHour + i;
        if (idx >= (hourly.time || []).length) break;
        const t = Math.round(hourly.temperature_2m[idx]);
        const c = WMO_CODES[hourly.weathercode[idx]] || "🌡️";
        const precip = hourly.precipitation_probability ? hourly.precipitation_probability[idx] : 0;
        const label = i === 0 ? "Now" : `${(idx % 24) > 12 ? (idx%24)-12 : (idx%24)||12}${idx%24>=12?"p":"a"}`;
        const precipHTML = precip > 20 ? `<span class="wf-precip">${precip}%</span>` : "";
        hourlyHTML += `<div class="weather-forecast-item${i===0?" now":""}"><span class="wf-time">${label}</span><span class="wf-icon">${c}</span><span class="wf-temp">${t}${sym}</span>${precipHTML}</div>`;
    }

    let dailyHTML = "";
    let daily3HTML = "";
    const dayNames = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
    for (let i = 0; i < Math.min(7, (daily.time || []).length); i++) {
        const hi = Math.round(daily.temperature_2m_max[i]);
        const lo = Math.round(daily.temperature_2m_min[i]);
        const c = WMO_CODES[daily.weathercode[i]] || "🌡️";
        const precip = daily.precipitation_probability_max ? daily.precipitation_probability_max[i] : 0;
        const d = new Date(daily.time[i]);
        const label = i === 0 ? "Today" : dayNames[d.getDay()];
        const precipHTML = precip > 20 ? `<span class="wf-precip">${precip}%</span>` : "";
        const item = `<div class="weather-forecast-item${i===0?" now":""}"><span class="wf-time">${label}</span><span class="wf-icon">${c}</span><span class="wf-temp">${hi}${sym}</span><span class="wf-temp-range">${lo}${sym}</span>${precipHTML}</div>`;
        dailyHTML += item;
        if (i < 3) daily3HTML += item;
    }

    const humidity = hourly.relative_humidity_2m ? hourly.relative_humidity_2m[nowHour] : "—";
    w.innerHTML = `
        <div class="weather-header">
            <span class="weather-location"><i class="fas fa-map-marker-alt"></i> ${config.weather.city}</span>
            <div class="weather-view-toggle">
                <button class="weather-view-btn active" data-wview="hourly">Hourly</button>
                <button class="weather-view-btn" data-wview="daily">Daily</button>
                <button class="weather-view-btn" data-wview="weekly">Weekly</button>
            </div>
        </div>
        <div class="weather-current">
            <div class="weather-icon-big">${icon}</div>
            <div class="weather-temp-big">${temp}${sym}</div>
            <div><div class="weather-condition">${desc}</div>
            <div class="weather-current-details">Humidity ${humidity}% · Wind ${wind}mph</div></div>
        </div>
        <div id="weather-hourly" class="weather-forecast">${hourlyHTML}</div>
        <div id="weather-daily" class="weather-forecast" style="display:none;">${daily3HTML}</div>
        <div id="weather-weekly" class="weather-forecast" style="display:none;">${dailyHTML}</div>
    `;
}

function setupWeatherToggle() {
    document.getElementById("slideshow-container").addEventListener("click", e => {
        const btn = e.target.closest(".weather-view-btn");
        if (!btn) return;
        e.stopPropagation();
        document.querySelectorAll(".weather-view-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const view = btn.dataset.wview;
        const hourly = document.getElementById("weather-hourly");
        const daily = document.getElementById("weather-daily");
        const weekly = document.getElementById("weather-weekly");
        if (hourly) hourly.style.display = view === "hourly" ? "flex" : "none";
        if (daily) daily.style.display = view === "daily" ? "flex" : "none";
        if (weekly) weekly.style.display = view === "weekly" ? "flex" : "none";
    });
}

// ==================== NEWS ====================
async function loadNews(force) {
    if (!config.news.show) {
        document.getElementById("news-ticker").style.display = "none";
        document.getElementById("news-cards").style.display = "none";
        return;
    }
    const url = force ? "/api/news?force=true" : "/api/news";
    const data = await fetchJSON(url);
    if (!data || !data.articles || !data.articles.length) return;

    // Ticker
    const tickerEl = document.getElementById("ticker-content");
    let tickerHTML = "";
    data.articles.forEach(a => {
        tickerHTML += `<span class="ticker-item"><span class="ticker-source">${a.source}</span> ${a.title}</span><span class="ticker-sep">•</span>`;
    });
    tickerEl.innerHTML = tickerHTML + tickerHTML; // duplicate for seamless loop

    // Cards
    const cardsEl = document.getElementById("news-cards");
    let cardsHTML = "";
    data.articles.slice(0, 5).forEach(a => {
        cardsHTML += `<div class="news-card"><span class="news-card-source">${a.source}</span><span class="news-card-title">${a.title}</span></div>`;
    });
    cardsEl.innerHTML = cardsHTML;

    if (config.news.style === "ticker") {
        document.getElementById("news-ticker").style.display = "flex";
        document.getElementById("news-cards").style.display = "none";
    } else {
        document.getElementById("news-ticker").style.display = "none";
        document.getElementById("news-cards").style.display = "flex";
    }
    // Apply font sizes after content is loaded
    applyNewsTickerStyle();
}

function applyNewsTickerStyle() {
    const ticker = document.getElementById("news-ticker");
    if (!ticker) return;
    const nfs = config.news.fontSize || 14;
    ticker.style.height = `${config.news.height || 42}px`;
    ticker.querySelectorAll(".ticker-item").forEach(i => i.style.fontSize = `${nfs}px`);
    ticker.querySelectorAll(".ticker-source").forEach(i => i.style.fontSize = `${Math.max(nfs - 3, 8)}px`);
    const label = ticker.querySelector(".ticker-label");
    if (label) label.style.fontSize = `${Math.max(nfs - 3, 8)}px`;
    // Apply scroll speed
    const speed = config.news.speed || "40";
    const content = ticker.querySelector(".ticker-content");
    if (content) content.style.animationDuration = `${speed}s`;
}

// ==================== STOCKS ====================
async function loadStocks(force) {
    if (!config.stocks || !config.stocks.show) {
        document.getElementById("stock-ticker").style.display = "none";
        return;
    }
    const url = force ? "/api/stocks?force=true" : "/api/stocks";
    const data = await fetchJSON(url);
    if (!data || !data.articles || !data.articles.length) {
        document.getElementById("stock-ticker").style.display = "none";
        return;
    }
    const el = document.getElementById("stock-ticker-content");
    let html = "";
    data.articles.forEach(a => {
        html += `<span class="ticker-item"><span class="ticker-source">${a.source}</span> ${a.title}</span><span class="ticker-sep">•</span>`;
    });
    el.innerHTML = html + html;
    document.getElementById("stock-ticker").style.display = "flex";
    applyStockTickerStyle();
}

function applyStockTickerStyle() {
    const st = document.getElementById("stock-ticker");
    if (!st || !config.stocks) return;
    const sfs = config.stocks.fontSize || 12;
    st.style.height = `${config.stocks.height || 36}px`;
    st.querySelectorAll(".ticker-item").forEach(i => i.style.fontSize = `${sfs}px`);
    st.querySelectorAll(".ticker-source").forEach(i => i.style.fontSize = `${Math.max(sfs - 2, 8)}px`);
    const label = st.querySelector(".ticker-label");
    if (label) label.style.fontSize = `${Math.max(sfs - 2, 8)}px`;
    // Position news ticker below stock ticker
    const newsTicker = document.getElementById("news-ticker");
    if (newsTicker && st.style.display !== "none") {
        newsTicker.style.bottom = "0";
        st.style.bottom = `${newsTicker.offsetHeight || 42}px`;
    }
}

// ==================== NOTES ====================
async function loadNotes() {
    const data = await fetchJSON("/api/notes");
    if (!data) return;
    renderNotes(data.notes || []);
}

function renderNotes(notes) {
    const list = document.getElementById("notes-list");
    list.innerHTML = "";
    notes.forEach(n => {
        const card = document.createElement("div");
        card.className = "note-card";
        card.style.borderLeftColor = n.color || "#fbbc04";
        card.dataset.id = n.id;
        const timeAgo = getTimeAgo(n.timestamp);
        card.innerHTML = `<div class="note-text">${escapeHTML(n.text)}</div>
            <div class="note-meta"><span class="note-author">${escapeHTML(n.author)}</span> · <span class="note-time">${timeAgo}</span>
            <button class="note-pin${n.pinned ? " active" : ""}" title="Pin to overlay"><i class="fas fa-thumbtack"></i></button>
            <button class="note-delete"><i class="fas fa-trash"></i></button></div>`;
        list.appendChild(card);
        if (n.pinned) showPinnedNote(n);
    });
    setupNoteButtons();
}

function escapeHTML(str) { const d = document.createElement("div"); d.textContent = str; return d.innerHTML; }

function getTimeAgo(ts) {
    const diff = (Date.now() - new Date(ts).getTime()) / 1000;
    if (diff < 60) return "Just now";
    if (diff < 3600) return `${Math.floor(diff/60)} min ago`;
    if (diff < 86400) return `${Math.floor(diff/3600)} hr ago`;
    return `${Math.floor(diff/86400)} days ago`;
}

function showPinnedNote(note) {
    const el = document.getElementById("pinned-note");
    el.querySelector(".pinned-note-text").textContent = note.text;
    el.querySelector(".pinned-note-meta").textContent = `${note.author} · ${getTimeAgo(note.timestamp)}`;
    applyNoteOverlayStyle();
    el.style.display = "block";
}

function applyNoteOverlayStyle() {
    const el = document.getElementById("pinned-note");
    const textEl = el.querySelector(".pinned-note-text");
    textEl.style.fontFamily = `'${config.notes.overlayFont}', sans-serif`;
    textEl.style.fontSize = `${config.notes.overlayFontSize}px`;
    textEl.style.color = config.notes.overlayColor;
    textEl.style.fontWeight = config.notes.overlayWeight || "500";
    textEl.style.fontStyle = config.notes.overlayItalic ? "italic" : "normal";
    el.style.maxWidth = `${config.notes.overlayWidth}px`;
    const alpha = (config.notes.overlayOpacity / 100) * 0.7;
    el.style.background = `rgba(0,0,0,${alpha})`;
}

function setupNoteButtons() {
    document.querySelectorAll(".note-delete").forEach(btn => {
        btn.onclick = async (e) => {
            e.stopPropagation();
            const id = btn.closest(".note-card").dataset.id;
            await fetch(`/api/notes/${id}`, { method: "DELETE" });
            loadNotes();
        };
    });
    document.querySelectorAll(".note-pin").forEach(btn => {
        btn.onclick = async (e) => {
            e.stopPropagation();
            const id = btn.closest(".note-card").dataset.id;
            await fetch(`/api/notes/${id}/pin`, { method: "POST" });
            loadNotes();
        };
    });
}

// Add note
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btn-add-note").addEventListener("click", async () => {
        const text = document.getElementById("note-input").value.trim();
        if (!text) return;
        const author = document.getElementById("note-author").value.trim() || "Anonymous";
        const color = document.getElementById("note-color").value;
        await fetch("/api/notes", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text, author, color })
        });
        document.getElementById("note-input").value = "";
        loadNotes();
    });

    document.getElementById("pinned-note-close").addEventListener("click", (e) => {
        e.stopPropagation();
        document.getElementById("pinned-note").style.display = "none";
        // Unpin all via API
        document.querySelectorAll(".note-pin.active").forEach(async btn => {
            const id = btn.closest(".note-card").dataset.id;
            await fetch(`/api/notes/${id}/pin`, { method: "POST" });
            btn.classList.remove("active");
        });
    });
});

// ==================== CALENDAR ====================
async function loadCalendar() {
    if (!config.calendar.connected) return;
    const data = await fetchJSON("/api/calendar");
    if (!data || !data.events || !data.events.length) {
        document.getElementById("agenda-events").innerHTML = '<p style="opacity:0.4;text-align:center;padding:40px;">No upcoming events</p>';
        return;
    }

    // Group events by day
    const days = {};
    const dayNames = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
    const monthNames = ["January","February","March","April","May","June","July","August","September","October","November","December"];
    const colors = ["#4285f4","#ea4335","#34a853","#fbbc04","#a259ff","#ff6d01"];

    data.events.forEach((ev, i) => {
        const start = ev.start.dateTime || ev.start.date;
        const d = new Date(start);
        const key = d.toDateString();
        if (!days[key]) days[key] = { date: d, events: [] };
        days[key].events.push({ ...ev, color: colors[i % colors.length] });
    });

    let html = "";
    const today = new Date().toDateString();
    const tomorrow = new Date(Date.now() + 86400000).toDateString();

    Object.values(days).forEach(day => {
        const d = day.date;
        let label = `${dayNames[d.getDay()]}, ${monthNames[d.getMonth()]} ${d.getDate()}`;
        if (d.toDateString() === today) label = `Today — ${label}`;
        else if (d.toDateString() === tomorrow) label = `Tomorrow — ${label}`;

        html += `<div class="events-section"><h3>${label}</h3>`;
        day.events.forEach(ev => {
            const start = ev.start.dateTime ? new Date(ev.start.dateTime).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'}) : "All day";
            const end = ev.end.dateTime ? new Date(ev.end.dateTime).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'}) : "";
            const time = end ? `${start} – ${end}` : start;
            const loc = ev.location ? `<div class="event-location"><i class="fas fa-map-marker-alt"></i> ${escapeHTML(ev.location)}</div>` : "";
            html += `<div class="event-card" style="border-left-color:${ev.color};"><div class="event-time">${time}</div><div class="event-title">${escapeHTML(ev.summary || "No title")}</div>${loc}</div>`;
        });
        html += `</div>`;
    });

    document.getElementById("agenda-events").innerHTML = html;

    // Also build week and month views
    loadCalendarEmbeds();
}

function loadCalendarEmbeds() {
    const embedUrl = config.calendar.embedUrl || "";
    if (!embedUrl) {
        document.getElementById("cal-embed-week").src = "";
        document.getElementById("cal-embed-month").src = "";
        return;
    }
    // Set week view embed (add mode=WEEK)
    let weekUrl = embedUrl;
    if (weekUrl.includes("?")) weekUrl += "&mode=WEEK";
    else weekUrl += "?mode=WEEK";
    weekUrl += "&showTitle=0&showNav=1&showPrint=0&showTabs=0&showCalendars=0";
    document.getElementById("cal-embed-week").src = weekUrl;

    // Set month view embed (default mode)
    let monthUrl = embedUrl;
    if (monthUrl.includes("?")) monthUrl += "&mode=MONTH";
    else monthUrl += "?mode=MONTH";
    monthUrl += "&showTitle=0&showNav=1&showPrint=0&showTabs=0&showCalendars=0";
    document.getElementById("cal-embed-month").src = monthUrl;
}

// ==================== COMMUTE ====================
async function loadCommute() {
    const data = await fetchJSON("/api/commute");
    if (!data) { document.getElementById("commute-widget").style.display = "none"; return; }
    const items = [];
    ["commute1", "commute2"].forEach(key => {
        const c = config.commute[key];
        if (c.enabled && data[key]) {
            const d = data[key];
            const traffic = d.durationValue < 1800 ? "light" : d.durationValue < 3600 ? "moderate" : "heavy";
            const trafficLabel = traffic === "light" ? "Light" : traffic === "moderate" ? "Moderate" : "Heavy";
            items.push(`<div class="commute-item">
                <div class="commute-icon"><i class="fas fa-car"></i></div>
                <div class="commute-info"><div class="commute-name">${escapeHTML(c.label || key)}</div><div class="commute-route">via ${d.summary || ""}</div></div>
                <div class="commute-eta"><div class="commute-time">${d.duration}</div><div class="commute-traffic traffic-${traffic}"><i class="fas fa-circle"></i> ${trafficLabel}</div></div>
            </div>`);
        }
    });
    if (items.length) {
        document.getElementById("commute-widget").innerHTML = items.join('<div class="commute-divider"></div>');
        document.getElementById("commute-widget").style.display = "";
    } else {
        document.getElementById("commute-widget").style.display = "none";
    }
}

// ==================== NETWORK STATUS ====================
async function checkNetwork() {
    const data = await fetchJSON("/api/status");
    const el = document.getElementById("network-status");
    if (!data || !data.internet || !data.nas) {
        el.className = "network-error";
    } else {
        el.className = "network-ok";
    }
}

// ==================== OVERLAY CYCLE ====================
function setupOverlayCycle() {
    if (!config.display.autoCycle) return;
    const showMs = (config.display.cycleShowMin * 60 + config.display.cycleShowSec) * 1000;
    const hideMs = (config.display.cycleHideMin * 60 + config.display.cycleHideSec) * 1000;
    if (showMs <= 0 || hideMs <= 0) return;

    function cycle() {
        showOverlays();
        setTimeout(() => {
            hideOverlays();
            setTimeout(cycle, hideMs);
        }, showMs);
    }
    setTimeout(cycle, showMs);
}

function showOverlays() {
    overlaysVisible = true;
    document.getElementById("slideshow-container").classList.remove("overlays-hidden");
}

function hideOverlays() {
    overlaysVisible = false;
    document.getElementById("slideshow-container").classList.add("overlays-hidden");
}

// ==================== PANELS ====================
function setupPanels() {
    const cal = document.getElementById("calendar-panel");
    const settings = document.getElementById("settings-panel");
    const notes = document.getElementById("notes-panel");

    const closeAll = () => {
        cal.classList.remove("panel-visible", "panel-fullscreen");
        settings.classList.remove("panel-visible");
        notes.classList.remove("panel-visible");
    };

    document.getElementById("btn-calendar").addEventListener("click", e => { e.stopPropagation(); closeAll(); cal.classList.toggle("panel-visible"); });
    document.getElementById("btn-settings").addEventListener("click", e => { e.stopPropagation(); closeAll(); settings.classList.toggle("panel-visible"); });
    document.getElementById("btn-notes").addEventListener("click", e => { e.stopPropagation(); closeAll(); notes.classList.toggle("panel-visible"); });
    document.getElementById("btn-close-calendar").addEventListener("click", closeAll);
    document.getElementById("btn-close-settings").addEventListener("click", () => settings.classList.remove("panel-visible"));
    document.getElementById("btn-close-notes").addEventListener("click", () => notes.classList.remove("panel-visible"));

    // Virtual keyboard toggle
    let vkbEnabled = false;
    document.getElementById("btn-keyboard").addEventListener("click", e => {
        e.stopPropagation();
        vkbEnabled = !vkbEnabled;
        document.getElementById("btn-keyboard").classList.toggle("fab-active", vkbEnabled);
        if (vkbEnabled) {
            // Enable: listen for focus on text fields
            document.addEventListener("focusin", vkbFocusHandler);
        } else {
            document.removeEventListener("focusin", vkbFocusHandler);
            document.getElementById("vkb-overlay").style.display = "none";
        }
    });

    function vkbFocusHandler(e) {
        if ((e.target.tagName === "INPUT" && e.target.type === "text" && !e.target.readOnly) ||
            (e.target.tagName === "TEXTAREA" && !e.target.readOnly)) {
            // Trigger VKB show — need to access the showVKB function
            vkbTarget = e.target;
            document.getElementById("vkb-preview").textContent = e.target.value;
            document.getElementById("vkb-label").textContent = (e.target.placeholder || e.target.id || "Input") + ":";
            document.getElementById("vkb-overlay").style.display = "block";
        }
    }

    [cal, settings, notes].forEach(p => p.addEventListener("click", e => e.stopPropagation()));

    document.getElementById("slideshow-container").addEventListener("click", e => {
        if (e.target.closest("#fab-container,#weather-widget,#commute-widget,#music-widget,#pinned-note")) return;
        closeAll();
    });

    // Calendar view toggle
    document.querySelectorAll(".view-toggle-btn").forEach(btn => {
        btn.addEventListener("click", e => {
            e.stopPropagation();
            document.querySelectorAll(".view-toggle-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const view = btn.dataset.view;
            document.querySelectorAll(".cal-view-content").forEach(v => v.style.display = "none");
            document.getElementById(`cal-view-${view}`).style.display = (view === "week" || view === "month") ? "flex" : "block";
            cal.classList.toggle("panel-fullscreen", view === "week" || view === "month");
        });
    });

    // Keyboard shortcuts
    document.addEventListener("keydown", e => {
        if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
        switch (e.key.toLowerCase()) {
            case "c": document.getElementById("btn-calendar").click(); break;
            case "s": document.getElementById("btn-settings").click(); break;
            case "n": document.getElementById("btn-notes").click(); break;
            case "k": document.getElementById("btn-keyboard").click(); break;
            case "escape": closeAll(); break;
            case "arrowright": nextSlide(); clearInterval(slideshowTimer); startSlideshow(); break;
        }
    });

    // Rescan button
    document.getElementById("btn-rescan").addEventListener("click", async () => {
        await fetch("/api/photos/scan", { method: "POST" });
        setTimeout(loadPhotos, 2000);
    });

    // Full rescan button
    document.getElementById("btn-full-rescan").addEventListener("click", async () => {
        await fetch("/api/photos/scan?full=true", { method: "POST" });
        setTimeout(loadPhotos, 2000);
    });

    // Folder browser — in-app navigator
    document.getElementById("btn-browse-folder").addEventListener("click", () => openFolderBrowser());

    // Auto-detect location
    document.getElementById("btn-detect-location").addEventListener("click", async () => {
        const btn = document.getElementById("btn-detect-location");
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        const data = await fetchJSON("/api/detect-location");
        if (data && data.city) {
            document.getElementById("s-weather-city").value = data.city;
            saveSettings();
            loadWeather();
        }
        btn.innerHTML = '<i class="fas fa-crosshairs"></i>';
    });
}

// ==================== SETTINGS ====================
function applyConfig() {
    // Clock
    const clockEl = document.getElementById("clock-overlay");
    clockEl.style.fontFamily = `'${config.clock.fontFamily}', sans-serif`;
    document.getElementById("clock-time").style.fontSize = `${config.clock.fontSize}px`;
    document.getElementById("clock-time").style.fontWeight = config.clock.fontWeight;
    clockEl.style.color = config.clock.color;
    clockEl.style.fontStyle = config.clock.italic ? "italic" : "normal";
    document.getElementById("clock-date").style.fontSize = `${config.clock.dateFontSize}px`;
    applyPosition(clockEl, config.clock.position);

    // Weather
    const weatherEl = document.getElementById("weather-widget");
    applyPosition(weatherEl, config.weather.position);
    const wAlpha = (config.weather.opacity / 100) * 0.7;
    weatherEl.style.background = `rgba(0,0,0,${wAlpha})`;

    // Progress bar
    document.getElementById("progress-bar-container").style.display = config.display.showProgressBar ? "" : "none";
    document.getElementById("photo-info").style.display = config.display.showPhotoInfo ? "" : "none";

    // News ticker size
    const ticker = document.getElementById("news-ticker");
    if (ticker) {
        const nfs = config.news.fontSize || 14;
        ticker.style.height = `${config.news.height || 42}px`;
        ticker.querySelectorAll(".ticker-item").forEach(i => i.style.fontSize = `${nfs}px`);
        ticker.querySelectorAll(".ticker-source").forEach(i => i.style.fontSize = `${Math.max(nfs - 3, 8)}px`);
        const label = ticker.querySelector(".ticker-label");
        if (label) label.style.fontSize = `${Math.max(nfs - 3, 8)}px`;
    }
}

function applyPosition(el, pos) {
    el.style.top = el.style.bottom = el.style.left = el.style.right = el.style.transform = "";
    switch (pos) {
        case "tl": el.style.top = "30px"; el.style.left = "36px"; break;
        case "tc": el.style.top = "30px"; el.style.left = "50%"; el.style.transform = "translateX(-50%)"; break;
        case "tr": el.style.top = "30px"; el.style.right = "36px"; break;
        case "bl": el.style.bottom = "70px"; el.style.left = "36px"; break;
        case "bc": el.style.bottom = "70px"; el.style.left = "50%"; el.style.transform = "translateX(-50%)"; break;
        case "br": el.style.bottom = "70px"; el.style.right = "36px"; break;
        case "cl": el.style.top = "50%"; el.style.left = "36px"; el.style.transform = "translateY(-50%)"; break;
        case "cr": el.style.top = "50%"; el.style.right = "36px"; el.style.transform = "translateY(-50%)"; break;
    }
}

function setupSettings() {
    // Populate MM:SS pickers
    populateMMSS("s-slide-interval", config.slideshow.intervalMin, config.slideshow.intervalSec);
    populateMMSS("s-cycle-show", config.display.cycleShowMin, config.display.cycleShowSec);
    populateMMSS("s-cycle-hide", config.display.cycleHideMin, config.display.cycleHideSec);

    // Populate time dropdowns
    populateTimeDropdowns();

    // Set values from config
    setVal("s-photos-path", config.photos.path);
    setChecked("s-photos-subfolders", config.photos.includeSubfolders);
    setVal("s-photos-scan", config.photos.scanInterval);
    setVal("s-slide-transition", config.slideshow.transition);
    setChecked("s-slide-shuffle", config.slideshow.shuffle);
    setChecked("s-slide-pair", config.slideshow.pairPortraits);
    setChecked("s-slide-audio", config.slideshow.muteVideo !== false);
    setChecked("s-clock-show", config.clock.show);
    setVal("s-clock-pos", config.clock.position);
    setVal("s-clock-font", config.clock.fontFamily);
    setVal("s-clock-fontsize", config.clock.fontSize);
    document.getElementById("s-clock-fontsize-val").textContent = `${config.clock.fontSize}px`;
    setVal("s-clock-weight", config.clock.fontWeight);
    setVal("s-clock-color", config.clock.color);
    activateSwatch("s-clock-color", config.clock.color);
    setChecked("s-clock-italic", config.clock.italic || false);
    setVal("s-clock-format", config.clock.format);
    setChecked("s-clock-seconds", config.clock.showSeconds);
    setChecked("s-clock-date", config.clock.showDate);
    setVal("s-date-fontsize", config.clock.dateFontSize);
    document.getElementById("s-date-fontsize-val").textContent = `${config.clock.dateFontSize}px`;
    setVal("s-date-format", config.clock.dateFormat);
    setChecked("s-weather-show", config.weather.show);
    setVal("s-weather-source", config.weather.source);
    setVal("s-weather-apikey", config.weather.apiKey);
    setVal("s-weather-pos", config.weather.position);
    setVal("s-weather-unit", config.weather.unit);
    setVal("s-weather-city", config.weather.city);
    setVal("s-weather-opacity", config.weather.opacity);
    document.getElementById("s-weather-opacity-val").textContent = `${config.weather.opacity}%`;
    setVal("s-commute-apikey", config.commute.googleMapsApiKey);
    setChecked("s-c1-enabled", config.commute.commute1.enabled);
    setVal("s-c1-label", config.commute.commute1.label);
    setVal("s-c1-from", config.commute.commute1.from);
    setVal("s-c1-to", config.commute.commute1.to);
    setVal("s-c1-schedule", config.commute.commute1.schedule);
    setChecked("s-c2-enabled", config.commute.commute2.enabled);
    setVal("s-c2-label", config.commute.commute2.label);
    setVal("s-c2-from", config.commute.commute2.from);
    setVal("s-c2-to", config.commute.commute2.to);
    setVal("s-c2-schedule", config.commute.commute2.schedule);
    setChecked("s-news-show", config.news.show);
    setVal("s-news-style", config.news.style);
    setVal("s-news-height", config.news.height || 42);
    document.getElementById("s-news-height-val").textContent = `${config.news.height || 42}px`;
    setVal("s-news-fontsize", config.news.fontSize || 14);
    document.getElementById("s-news-fontsize-val").textContent = `${config.news.fontSize || 14}px`;
    setVal("s-news-speed", config.news.speed || "40");
    setChecked("s-music-show", config.music.show);
    setVal("s-music-pos", config.music.position);
    // Stocks
    if (config.stocks) {
        setChecked("s-stock-show", config.stocks.show);
        setVal("s-stock-height", config.stocks.height || 36);
        document.getElementById("s-stock-height-val").textContent = `${config.stocks.height || 36}px`;
        setVal("s-stock-fontsize", config.stocks.fontSize || 12);
        document.getElementById("s-stock-fontsize-val").textContent = `${config.stocks.fontSize || 12}px`;
        renderStockFeeds();
    }
    setVal("s-note-font", config.notes.overlayFont);
    setVal("s-note-fontsize", config.notes.overlayFontSize);
    document.getElementById("s-note-fontsize-val").textContent = `${config.notes.overlayFontSize}px`;
    setVal("s-note-color", config.notes.overlayColor);
    activateSwatch("s-note-color", config.notes.overlayColor);
    setVal("s-note-weight", config.notes.overlayWeight || "400");
    setChecked("s-note-italic", config.notes.overlayItalic || false);
    setVal("s-note-width", config.notes.overlayWidth);
    setVal("s-note-opacity", config.notes.overlayOpacity);
    document.getElementById("s-note-opacity-val").textContent = `${config.notes.overlayOpacity}%`;
    setVal("s-note-pos", config.notes.overlayPosition);
    setVal("s-cal-days", config.calendar.daysToShow);
    setVal("s-cal-embed", config.calendar.embedUrl || "");
    // Load calendar embeds
    loadCalendarEmbeds();
    setChecked("s-disp-photoinfo", config.display.showPhotoInfo);
    setChecked("s-disp-progress", config.display.showProgressBar);
    setVal("s-disp-theme", config.display.overlayTheme);
    setChecked("s-disp-autohide", config.display.autoHide);
    setChecked("s-disp-autocycle", config.display.autoCycle);
    setChecked("s-disp-burnin", config.display.burnInProtection);
    setVal("s-disp-schedule", config.display.screenSchedule);

    // Calendar status
    const calStatus = document.getElementById("cal-status");
    const calText = document.getElementById("cal-status-text");
    if (config.calendar.connected) {
        calStatus.className = "status-badge connected";
        calText.textContent = "Connected";
    } else {
        calStatus.className = "status-badge disconnected";
        calText.textContent = "Not Connected";
    }

    // RSS feeds
    renderFeeds();

    // Auto-save on any change
    document.getElementById("settings-content").addEventListener("change", saveSettings);
    document.getElementById("settings-content").addEventListener("input", debounce(saveSettings, 500));

    // Also listen for note overlay settings in notes panel
    const notesContent = document.getElementById("notes-content");
    if (notesContent) {
        notesContent.addEventListener("change", saveSettings);
        notesContent.addEventListener("input", debounce(saveSettings, 500));
    }

    // Live preview handlers
    document.getElementById("s-clock-fontsize").addEventListener("input", e => {
        document.getElementById("s-clock-fontsize-val").textContent = `${e.target.value}px`;
        document.getElementById("clock-time").style.fontSize = `${e.target.value}px`;
    });
    document.getElementById("s-date-fontsize").addEventListener("input", e => {
        document.getElementById("s-date-fontsize-val").textContent = `${e.target.value}px`;
        document.getElementById("clock-date").style.fontSize = `${e.target.value}px`;
    });
    document.getElementById("s-clock-color").addEventListener("input", e => {
        document.getElementById("clock-overlay").style.color = e.target.value;
    });
    document.getElementById("s-weather-opacity").addEventListener("input", e => {
        document.getElementById("s-weather-opacity-val").textContent = `${e.target.value}%`;
    });
    document.getElementById("s-note-fontsize").addEventListener("input", e => {
        document.getElementById("s-note-fontsize-val").textContent = `${e.target.value}px`;
    });
    document.getElementById("s-note-opacity").addEventListener("input", e => {
        document.getElementById("s-note-opacity-val").textContent = `${e.target.value}%`;
    });
    document.getElementById("s-note-color").addEventListener("input", e => {
        // Applied via swatch handler and saveSettings
    });

    // News live preview
    document.getElementById("s-news-height").addEventListener("input", e => {
        document.getElementById("s-news-height-val").textContent = `${e.target.value}px`;
        document.getElementById("news-ticker").style.height = `${e.target.value}px`;
    });
    document.getElementById("s-news-fontsize").addEventListener("input", e => {
        document.getElementById("s-news-fontsize-val").textContent = `${e.target.value}px`;
        document.querySelectorAll(".ticker-item").forEach(i => i.style.fontSize = `${e.target.value}px`);
    });

    // Add feed button
    document.getElementById("btn-add-feed").addEventListener("click", () => {
        config.news.feeds.push("");
        renderFeeds();
    });

    // Add stock feed button
    document.getElementById("btn-add-stock-feed").addEventListener("click", () => {
        if (!config.stocks) config.stocks = { show: false, height: 36, fontSize: 12, feeds: [] };
        config.stocks.feeds.push("");
        renderStockFeeds();
    });

    // Stock ticker live preview
    document.getElementById("s-stock-height").addEventListener("input", e => {
        document.getElementById("s-stock-height-val").textContent = `${e.target.value}px`;
    });
    document.getElementById("s-stock-fontsize").addEventListener("input", e => {
        document.getElementById("s-stock-fontsize-val").textContent = `${e.target.value}px`;
    });

    // Color swatch click handler (global)
    document.addEventListener("click", e => {
        const swatch = e.target.closest(".color-swatch");
        if (!swatch) return;
        const row = swatch.closest(".color-swatch-row");
        const targetId = row.dataset.target;
        const color = swatch.dataset.color;
        row.querySelectorAll(".color-swatch").forEach(s => s.classList.remove("active"));
        swatch.classList.add("active");
        const input = document.getElementById(targetId);
        if (input) { input.value = color; input.dispatchEvent(new Event("input", { bubbles: true })); }
    });

    // Custom color picker in swatch rows
    document.querySelectorAll(".color-input-mini").forEach(picker => {
        picker.addEventListener("input", e => {
            const row = picker.closest(".color-swatch-row");
            row.querySelectorAll(".color-swatch").forEach(s => s.classList.remove("active"));
            const targetId = row.dataset.target;
            const input = document.getElementById(targetId);
            if (input) { input.value = e.target.value; input.dispatchEvent(new Event("input", { bubbles: true })); }
        });
    });

    // Force weather refresh when unit or city changes
    document.getElementById("s-weather-unit").addEventListener("change", () => {
        saveSettings();
        fetchJSON("/api/weather?force=true").then(data => { if (data && !data.error) renderWeather(data); });
    });
    document.getElementById("s-weather-city").addEventListener("change", () => {
        saveSettings();
        fetchJSON("/api/weather?force=true").then(data => { if (data && !data.error) renderWeather(data); });
    });
}

function setVal(id, val) { const el = document.getElementById(id); if (el) el.value = val; }
function setChecked(id, val) { const el = document.getElementById(id); if (el) el.checked = val; }
function activateSwatch(targetId, color) {
    const row = document.querySelector(`.color-swatch-row[data-target="${targetId}"]`);
    if (!row) return;
    row.querySelectorAll(".color-swatch").forEach(s => {
        s.classList.toggle("active", s.dataset.color === color);
    });
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

// ==================== FOLDER BROWSER ====================
async function openFolderBrowser(startPath) {
    const data = await fetchJSON(`/api/browse?path=${encodeURIComponent(startPath || "")}`);
    if (!data) return;

    // Create modal
    let modal = document.getElementById("folder-browser-modal");
    if (!modal) {
        modal = document.createElement("div");
        modal.id = "folder-browser-modal";
        modal.style.cssText = "position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.7);z-index:600;display:flex;align-items:center;justify-content:center;";
        document.body.appendChild(modal);
    }

    let html = `<div style="background:#1a1a1e;border-radius:16px;border:1px solid rgba(255,255,255,0.1);width:420px;max-height:70vh;display:flex;flex-direction:column;overflow:hidden;">
        <div style="padding:16px 20px;border-bottom:1px solid rgba(255,255,255,0.06);display:flex;justify-content:space-between;align-items:center;">
            <div style="font-size:14px;font-weight:600;">Select Folder</div>
            <button onclick="document.getElementById('folder-browser-modal').remove()" style="background:rgba(255,255,255,0.08);border:none;color:#fff;width:28px;height:28px;border-radius:50%;cursor:pointer;font-size:12px;">✕</button>
        </div>
        <div style="padding:8px 16px;font-size:11px;opacity:0.4;border-bottom:1px solid rgba(255,255,255,0.04);">${data.current || "Drives"}</div>
        <div style="flex:1;overflow-y:auto;padding:8px;">`;

    if (data.parent && data.current) {
        html += `<div class="fb-item" data-path="${data.parent}" style="padding:10px 12px;border-radius:8px;cursor:pointer;font-size:13px;display:flex;align-items:center;gap:8px;color:rgba(255,255,255,0.5);" onmouseover="this.style.background='rgba(255,255,255,0.06)'" onmouseout="this.style.background=''"><i class="fas fa-arrow-up"></i> ..</div>`;
    }
    (data.folders || []).forEach(f => {
        html += `<div class="fb-item" data-path="${f.path}" style="padding:10px 12px;border-radius:8px;cursor:pointer;font-size:13px;display:flex;align-items:center;gap:8px;" onmouseover="this.style.background='rgba(255,255,255,0.06)'" onmouseout="this.style.background=''"><i class="fas fa-folder" style="color:#fbbc04;"></i> ${f.name}</div>`;
    });
    if (!data.folders || !data.folders.length) {
        html += `<div style="padding:20px;text-align:center;opacity:0.3;font-size:12px;">No subfolders</div>`;
    }

    html += `</div><div style="padding:12px 16px;border-top:1px solid rgba(255,255,255,0.06);display:flex;gap:8px;justify-content:flex-end;">
        <button onclick="document.getElementById('folder-browser-modal').remove()" class="btn-secondary btn-sm">Cancel</button>
        <button id="fb-select" class="btn-primary btn-sm"><i class="fas fa-check"></i> Select This Folder</button>
    </div></div>`;

    modal.innerHTML = html;

    // Click folder to navigate
    modal.querySelectorAll(".fb-item").forEach(item => {
        item.addEventListener("click", () => openFolderBrowser(item.dataset.path));
    });

    // Select current folder
    document.getElementById("fb-select").addEventListener("click", () => {
        document.getElementById("s-photos-path").value = data.current;
        saveSettings();
        modal.remove();
        // Trigger scan
        fetch("/api/photos/scan", { method: "POST" });
        setTimeout(loadPhotos, 3000);
    });
}

function saveSettings() {
    config.photos.path = document.getElementById("s-photos-path").value;
    config.photos.includeSubfolders = document.getElementById("s-photos-subfolders").checked;
    config.photos.scanInterval = parseInt(document.getElementById("s-photos-scan").value);
    const si = document.getElementById("s-slide-interval");
    config.slideshow.intervalMin = parseInt(si.querySelector(".mmss-min").value);
    config.slideshow.intervalSec = parseInt(si.querySelector(".mmss-sec").value);
    config.slideshow.transition = document.getElementById("s-slide-transition").value;
    config.slideshow.shuffle = document.getElementById("s-slide-shuffle").checked;
    config.slideshow.pairPortraits = document.getElementById("s-slide-pair").checked;
    config.slideshow.muteVideo = document.getElementById("s-slide-audio").checked;
    config.clock.show = document.getElementById("s-clock-show").checked;
    config.clock.position = document.getElementById("s-clock-pos").value;
    config.clock.fontFamily = document.getElementById("s-clock-font").value;
    config.clock.fontSize = parseInt(document.getElementById("s-clock-fontsize").value);
    config.clock.fontWeight = document.getElementById("s-clock-weight").value;
    config.clock.color = document.getElementById("s-clock-color").value;
    config.clock.italic = document.getElementById("s-clock-italic").checked;
    config.clock.format = document.getElementById("s-clock-format").value;
    config.clock.showSeconds = document.getElementById("s-clock-seconds").checked;
    config.clock.showDate = document.getElementById("s-clock-date").checked;
    config.clock.dateFontSize = parseInt(document.getElementById("s-date-fontsize").value);
    config.clock.dateFormat = document.getElementById("s-date-format").value;
    config.weather.show = document.getElementById("s-weather-show").checked;
    config.weather.source = document.getElementById("s-weather-source").value;
    config.weather.apiKey = document.getElementById("s-weather-apikey").value;
    config.weather.position = document.getElementById("s-weather-pos").value;
    config.weather.unit = document.getElementById("s-weather-unit").value;
    config.weather.city = document.getElementById("s-weather-city").value;
    config.weather.opacity = parseInt(document.getElementById("s-weather-opacity").value);
    config.commute.googleMapsApiKey = document.getElementById("s-commute-apikey").value;
    config.commute.commute1.enabled = document.getElementById("s-c1-enabled").checked;
    config.commute.commute1.label = document.getElementById("s-c1-label").value;
    config.commute.commute1.from = document.getElementById("s-c1-from").value;
    config.commute.commute1.to = document.getElementById("s-c1-to").value;
    config.commute.commute1.schedule = document.getElementById("s-c1-schedule").value;
    config.commute.commute2.enabled = document.getElementById("s-c2-enabled").checked;
    config.commute.commute2.label = document.getElementById("s-c2-label").value;
    config.commute.commute2.from = document.getElementById("s-c2-from").value;
    config.commute.commute2.to = document.getElementById("s-c2-to").value;
    config.commute.commute2.schedule = document.getElementById("s-c2-schedule").value;
    config.news.show = document.getElementById("s-news-show").checked;
    config.news.style = document.getElementById("s-news-style").value;
    config.news.height = parseInt(document.getElementById("s-news-height").value);
    config.news.fontSize = parseInt(document.getElementById("s-news-fontsize").value);
    config.news.speed = document.getElementById("s-news-speed").value;
    config.music.show = document.getElementById("s-music-show").checked;
    config.music.position = document.getElementById("s-music-pos").value;
    // Stocks
    if (!config.stocks) config.stocks = { show: false, height: 36, fontSize: 12, feeds: [] };
    config.stocks.show = document.getElementById("s-stock-show").checked;
    config.stocks.height = parseInt(document.getElementById("s-stock-height").value);
    config.stocks.fontSize = parseInt(document.getElementById("s-stock-fontsize").value);
    const stockFeedInputs = document.querySelectorAll("#stock-feeds-container .feed-entry input");
    config.stocks.feeds = Array.from(stockFeedInputs).map(i => i.value.trim()).filter(v => v);
    config.notes.overlayFont = document.getElementById("s-note-font").value;
    config.notes.overlayFontSize = parseInt(document.getElementById("s-note-fontsize").value);
    config.notes.overlayColor = document.getElementById("s-note-color").value;
    config.notes.overlayWeight = document.getElementById("s-note-weight").value;
    config.notes.overlayItalic = document.getElementById("s-note-italic").checked;
    config.notes.overlayWidth = parseInt(document.getElementById("s-note-width").value);
    config.notes.overlayOpacity = parseInt(document.getElementById("s-note-opacity").value);
    config.notes.overlayPosition = document.getElementById("s-note-pos").value;
    config.calendar.daysToShow = parseInt(document.getElementById("s-cal-days").value);
    config.calendar.embedUrl = document.getElementById("s-cal-embed").value;
    config.display.showPhotoInfo = document.getElementById("s-disp-photoinfo").checked;
    config.display.showProgressBar = document.getElementById("s-disp-progress").checked;
    config.display.overlayTheme = document.getElementById("s-disp-theme").value;
    config.display.autoHide = document.getElementById("s-disp-autohide").checked;
    config.display.autoCycle = document.getElementById("s-disp-autocycle").checked;
    const cs = document.getElementById("s-cycle-show");
    config.display.cycleShowMin = parseInt(cs.querySelector(".mmss-min").value);
    config.display.cycleShowSec = parseInt(cs.querySelector(".mmss-sec").value);
    const ch = document.getElementById("s-cycle-hide");
    config.display.cycleHideMin = parseInt(ch.querySelector(".mmss-min").value);
    config.display.cycleHideSec = parseInt(ch.querySelector(".mmss-sec").value);
    config.display.burnInProtection = document.getElementById("s-disp-burnin").checked;
    config.display.screenSchedule = document.getElementById("s-disp-schedule").value;

    // Save feeds
    const feedInputs = document.querySelectorAll("#feeds-container .feed-entry input");
    config.news.feeds = Array.from(feedInputs).map(i => i.value.trim()).filter(v => v);

    applyConfig();
    fetch("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config) });

    // Live-apply widgets
    loadWeather();
    loadNews(true);
    loadStocks(true);
    loadCommute();
    if (config.music.show) document.getElementById("music-widget").style.display = "";
    else document.getElementById("music-widget").style.display = "none";
    applyNoteOverlayStyle();
    startSlideshow();
}

function renderFeeds() {
    const container = document.getElementById("feeds-container");
    container.innerHTML = "";
    config.news.feeds.forEach((url, i) => {
        const div = document.createElement("div");
        div.className = "feed-entry";
        div.innerHTML = `<input type="text" value="${escapeHTML(url)}" placeholder="RSS feed URL"><button class="feed-remove" data-idx="${i}"><i class="fas fa-times"></i></button>`;
        div.querySelector(".feed-remove").addEventListener("click", () => { config.news.feeds.splice(i, 1); renderFeeds(); saveSettings(); });
        container.appendChild(div);
    });
}

function renderStockFeeds() {
    const container = document.getElementById("stock-feeds-container");
    if (!container) return;
    container.innerHTML = "";
    (config.stocks.feeds || []).forEach((url, i) => {
        const div = document.createElement("div");
        div.className = "feed-entry";
        div.innerHTML = `<input type="text" value="${escapeHTML(url)}" placeholder="Stock RSS feed URL"><button class="feed-remove"><i class="fas fa-times"></i></button>`;
        div.querySelector(".feed-remove").addEventListener("click", () => { config.stocks.feeds.splice(i, 1); renderStockFeeds(); saveSettings(); });
        container.appendChild(div);
    });
}

function populateMMSS(containerId, minVal, secVal) {
    const container = document.getElementById(containerId);
    const minSel = container.querySelector(".mmss-min");
    const secSel = container.querySelector(".mmss-sec");
    for (let i = 0; i <= 60; i++) { const o = document.createElement("option"); o.value = i; o.textContent = i.toString().padStart(2, "0"); if (i === minVal) o.selected = true; minSel.appendChild(o); }
    [0,5,10,15,20,30,45].forEach(s => { const o = document.createElement("option"); o.value = s; o.textContent = s.toString().padStart(2, "0"); if (s === secVal) o.selected = true; secSel.appendChild(o); });
}

function populateTimeDropdowns() {
    const times = [];
    for (let h = 5; h <= 23; h++) { for (let m = 0; m < 60; m += 30) { const hr = h > 12 ? h - 12 : h; const ampm = h >= 12 ? "PM" : "AM"; times.push(`${hr}:${m.toString().padStart(2,"0")} ${ampm}`); } }
    times.push("12:00 AM", "12:30 AM");
    ["s-wd-on","s-wd-off","s-we-on","s-we-off"].forEach(id => {
        const sel = document.getElementById(id);
        const defaultVal = id === "s-wd-on" ? config.display.weekdayOn : id === "s-wd-off" ? config.display.weekdayOff : id === "s-we-on" ? config.display.weekendOn : config.display.weekendOff;
        times.forEach(t => { const o = document.createElement("option"); o.value = t; o.textContent = t; if (t === defaultVal) o.selected = true; sel.appendChild(o); });
    });
}

// ==================== VIRTUAL KEYBOARD ====================
let vkbTarget = null;
let vkbShift = false;

function setupVirtualKeyboard() {
    const overlay = document.getElementById("vkb-overlay");
    const preview = document.getElementById("vkb-preview");
    const label = document.getElementById("vkb-label");

    function syncToField() {
        if (!vkbTarget) return;
        // Directly set the native value and fire events
        const nativeSetter = Object.getOwnPropertyDescriptor(
            vkbTarget.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, "value"
        ).set;
        nativeSetter.call(vkbTarget, vkbTarget.value);
        vkbTarget.dispatchEvent(new Event("input", { bubbles: true }));
        vkbTarget.dispatchEvent(new Event("change", { bubbles: true }));
        preview.textContent = vkbTarget.value;

        // Trigger autocomplete if applicable
        if (vkbTarget.dataset.autocomplete && vkbTarget.value.length >= 2) {
            triggerAutocomplete(vkbTarget);
        }
    }

    function showVKB(input) {
        vkbTarget = input;
        preview.textContent = input.value;
        label.textContent = (input.placeholder || input.id || "Input") + ":";
        overlay.style.display = "block";
        // Hide any open autocomplete
        hideAutocomplete();
    }

    function hideVKB() {
        overlay.style.display = "none";
        if (vkbTarget) {
            vkbTarget.dispatchEvent(new Event("input", { bubbles: true }));
            vkbTarget.dispatchEvent(new Event("change", { bubbles: true }));
        }
        vkbTarget = null;
        vkbShift = false;
        hideAutocomplete();
    }

    document.addEventListener("focusin", e => {
        // VKB no longer auto-opens on focus — user clicks keyboard FAB to enable
    });

    document.getElementById("vkb").addEventListener("click", e => {
        e.stopPropagation();
        const btn = e.target.closest(".vkb-key");
        if (!btn || !vkbTarget) return;
        const action = btn.dataset.action;
        const key = btn.dataset.key;

        if (action === "backspace") {
            vkbTarget.value = vkbTarget.value.slice(0, -1);
        } else if (action === "done") {
            hideVKB(); return;
        } else if (action === "shift") {
            vkbShift = !vkbShift;
            btn.classList.toggle("shift-active", vkbShift);
            document.querySelectorAll(".vkb-key[data-key]").forEach(k => {
                if (k.dataset.key.length === 1 && k.dataset.key.match(/[a-z]/i))
                    k.textContent = vkbShift ? k.dataset.key.toUpperCase() : k.dataset.key.toLowerCase();
            });
            return;
        } else if (action === "symbols") {
            document.querySelector(".vkb-symbols").style.display = "block"; return;
        } else if (action === "abc") {
            document.querySelector(".vkb-symbols").style.display = "none"; return;
        } else if (key !== undefined) {
            let char = key;
            if (vkbShift && char.length === 1 && char.match(/[a-z]/i)) {
                char = char.toUpperCase();
                vkbShift = false;
                document.querySelectorAll(".vkb-key[data-action='shift']").forEach(k => k.classList.remove("shift-active"));
                document.querySelectorAll(".vkb-key[data-key]").forEach(k => {
                    if (k.dataset.key.length === 1 && k.dataset.key.match(/[a-z]/i)) k.textContent = k.dataset.key.toLowerCase();
                });
            }
            vkbTarget.value += char;
        }
        syncToField();
    });

    // Emoji keys
    document.querySelectorAll(".vkb-emoji").forEach(btn => {
        btn.addEventListener("click", e => {
            e.stopPropagation();
            if (!vkbTarget) return;
            vkbTarget.value += btn.dataset.key;
            syncToField();
        });
    });

    overlay.addEventListener("click", e => { if (e.target === overlay) hideVKB(); });
}

// ==================== AUTOCOMPLETE ====================
let acDebounce = null;
let acDropdown = null;
let acJustSelected = false;

function triggerAutocomplete(input) {
    if (acJustSelected) { acJustSelected = false; return; }
    clearTimeout(acDebounce);
    acDebounce = setTimeout(async () => {
        const type = input.dataset.autocomplete;
        const q = input.value.trim();
        if (q.length < 2) { hideAutocomplete(); return; }

        const url = type === "city" ? `/api/autocomplete/city?q=${encodeURIComponent(q)}` : `/api/autocomplete/address?q=${encodeURIComponent(q)}`;
        const data = await fetchJSON(url);
        if (!data || !data.results || !data.results.length) { hideAutocomplete(); return; }

        showAutocompleteDropdown(data.results, input);
    }, 300);
}

function showAutocompleteDropdown(results, input) {
    hideAutocomplete();
    acDropdown = document.createElement("div");
    acDropdown.id = "ac-dropdown";
    acDropdown.style.cssText = `position:fixed;z-index:550;background:rgba(30,30,36,0.98);border:1px solid rgba(255,255,255,0.1);border-radius:10px;overflow:hidden;max-height:200px;overflow-y:auto;min-width:250px;`;

    // Position: if VKB is open, show above VKB. Otherwise show below the input field.
    const vkbOverlay = document.getElementById("vkb-overlay");
    if (vkbOverlay && vkbOverlay.style.display !== "none") {
        const vkb = document.getElementById("vkb");
        const vkbRect = vkb.getBoundingClientRect();
        acDropdown.style.bottom = `${window.innerHeight - vkbRect.top + 8}px`;
        acDropdown.style.left = `${vkbRect.left}px`;
        acDropdown.style.width = `${Math.min(vkbRect.width, 400)}px`;
    } else {
        const rect = input.getBoundingClientRect();
        acDropdown.style.top = `${rect.bottom + 4}px`;
        acDropdown.style.left = `${rect.left}px`;
        acDropdown.style.width = `${Math.max(rect.width, 250)}px`;
    }

    results.forEach(r => {
        const item = document.createElement("div");
        item.textContent = r;
        item.style.cssText = "padding:10px 14px;font-size:13px;cursor:pointer;transition:background 0.15s;border-bottom:1px solid rgba(255,255,255,0.04);";
        item.addEventListener("mouseover", () => item.style.background = "rgba(255,255,255,0.08)");
        item.addEventListener("mouseout", () => item.style.background = "");
        item.addEventListener("click", e => {
            e.stopPropagation();
            acJustSelected = true;
            input.value = r;
            document.getElementById("vkb-preview").textContent = r;
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.dispatchEvent(new Event("change", { bubbles: true }));
            hideAutocomplete();
        });
        acDropdown.appendChild(item);
    });

    document.body.appendChild(acDropdown);
}

function hideAutocomplete() {
    if (acDropdown) { acDropdown.remove(); acDropdown = null; }
}

// Hide autocomplete when clicking outside or blurring the field
document.addEventListener("click", e => {
    if (acDropdown && !e.target.closest("#ac-dropdown") && !e.target.closest("[data-autocomplete]")) {
        hideAutocomplete();
    }
});
document.addEventListener("focusout", e => {
    if (e.target.dataset && e.target.dataset.autocomplete) {
        // Small delay to allow clicking a dropdown item
        setTimeout(hideAutocomplete, 200);
    }
});

// Also trigger autocomplete from regular keyboard typing on marked fields
document.addEventListener("input", e => {
    if (e.target.dataset && e.target.dataset.autocomplete && e.target.value.length >= 2) {
        triggerAutocomplete(e.target);
    }
});

// ==================== YOUTUBE MUSIC ====================
function openYTMusic() {
    // Always use the same window name — browser will reuse it
    window.open("https://music.youtube.com", "FamilyDashboardMusic");
}

function setupMusicWidget() {
    document.getElementById("music-open-player").addEventListener("click", e => {
        e.stopPropagation();
        openYTMusic();
    });
    document.getElementById("music-launcher").addEventListener("click", e => {
        e.stopPropagation();
        openYTMusic();
    });
}

async function searchYouTube(query) {
    if (!query || query.length < 2) return [];
    try {
        const data = await fetchJSON(`/api/youtube/search?q=${encodeURIComponent(query)}`);
        return data && data.results ? data.results : [];
    } catch { return []; }
}

document.addEventListener("DOMContentLoaded", setupMusicWidget);

// ==================== IP ADDRESS ====================
async function getLocalIP() {
    try {
        const r = await fetch("/api/status");
        document.getElementById("about-ip").textContent = window.location.hostname;
    } catch {}
}

// ==================== START ====================
document.addEventListener("DOMContentLoaded", () => { init(); getLocalIP(); });
