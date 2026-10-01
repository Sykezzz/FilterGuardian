"""
analyzer.py — FilterGuardian Autonomous Brain v2.1
===================================================
Visits URLs in a locked-down sandboxed Playwright browser.
Detects hosting platform, proxy technology, classifies category,
generates a structural fingerprint, and logs everything to the DB.

v2.1 changes:
 - Rotating user agents + viewport variation to avoid fingerprint recognition
 - Random inter-request delay (4–12 s) to appear human-paced
 - Exponential backoff retry (up to 3 attempts) on connection errors
 - Deep proxy tech detection: script src paths, intercepted network requests,
   inline JS patterns (service worker registrations, proxy globals)
 - Richer site name extraction: OG tags, h1, brand/logo selectors
 - Known-fingerprint database (known_sites.json) for recognized gaming arcades
 - Failed URLs auto-reset to pending at startup so they get retried
"""

import base64
import hashlib
import json
import random
import re
import sys
import threading
import time
import database
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait
from pathlib import Path
from urllib.parse import urlparse as _urlparse

# ─── User-agent / viewport pools ─────────────────────────────────────────────

USER_AGENTS = [
    # Chrome Windows
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"),
    # Firefox Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    # Chrome Mac
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    # Edge Windows
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"),
    # Safari Mac
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) Version/17.2 Safari/605.1.15"),
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
    {"width": 1536, "height": 864},
]

TIMEZONES = [
    "America/New_York", "America/Chicago", "America/Denver",
    "America/Los_Angeles", "America/Phoenix",
]

# ─── Platform detection ───────────────────────────────────────────────────────

PLATFORM_MAP = {
    "github.io":         "GitHub Pages",
    "pages.dev":         "Cloudflare Pages",
    "workers.dev":       "Cloudflare Workers",
    "vercel.app":        "Vercel",
    "netlify.app":       "Netlify",
    "netlify.com":       "Netlify",
    "replit.app":        "Replit",
    "repl.co":           "Replit",
    "glitch.me":         "Glitch",
    "render.com":        "Render",
    "onrender.com":      "Render",
    "railway.app":       "Railway",
    "fly.dev":           "Fly.io",
    "web.app":           "Firebase",
    "firebaseapp.com":   "Firebase",
    "pythonanywhere.com":"PythonAnywhere",
    "heroku.com":        "Heroku",
    "herokuapp.com":     "Heroku",
    "surge.sh":          "Surge",
    "tiiny.host":        "Tiiny Host",
    "000webhost.com":    "000WebHost",
    "neocities.org":     "Neocities",
    "sites.google.com":  "Google Sites",
    "codepen.io":        "CodePen",
    "stackblitz.com":    "StackBlitz",
    "codesandbox.io":    "CodeSandbox",
    "b-cdn.net":         "BunnyCDN",
    "b-cdn.com":         "BunnyCDN",
    "amazonaws.com":     "AWS",
    "cloudfront.net":    "AWS CloudFront",
    "s3.amazonaws.com":  "AWS S3",
    "azurewebsites.net": "Azure",
    "azurestaticapps.net":"Azure Static",
    "blob.core.windows.net":"Azure Blob",
    "run.app":           "Google Cloud Run",
    "appspot.com":       "Google App Engine",
    "digitaloceanspaces.com":"DigitalOcean Spaces",
    "backblazeb2.com":   "Backblaze B2",
    "nowgg.fun":         "Now.gg",
    "now.gg":            "Now.gg",
}

# ─── Proxy tech detection — ordered most-specific first ──────────────────────
#
# These are checked against a combined haystack of:
#   • full HTML source (lowercased)
#   • all <script src="…"> attribute values
#   • all network request URLs intercepted during page load
#
# Proxy frameworks leak identity through script bundle paths, service worker
# registration calls, and JS global variable names.

PROXY_TECH_PATTERNS = [
    # Ultraviolet — most common, check multiple signatures
    (r'/uv/uv\.|uv\.bundle|uv\.config|__uv\$|uv\.sw\.js|@titaniumnetwork/uv', "Ultraviolet"),
    # Rammerhead
    (r'/rammerhead/|rammerhead\.js|__rh\$|rh\.sw\.js|rhead\.', "Rammerhead"),
    # Scramjet
    (r'/scramjet/|scramjet\.js|scramjet\.wasm|__scramjet\$|sj\.sw\.js', "Scramjet"),
    # Bare Server (transport layer used by UV/Scramjet — detect if no framework matched)
    (r'bare-client|/bare/v\d|bare\.bundle|bare\.cjs', "Bare Server"),
    # Corrosion
    (r'/corrosion/|corrosion\.js|__cor\$', "Corrosion"),
    # Interstellar
    (r'interstellar[/_-]proxy|/interstellar/bundle|__interstellar\$', "Interstellar"),
    # Holy Unblocker
    (r'holy[_-]unblocker|holyublocker', "Holy Unblocker"),
    # Epoxy (WASM-based)
    (r'/epoxy/|epoxy\.wasm|libepoxy\.js', "Epoxy"),
    # Aero Proxy
    (r'aero[_-]proxy|/aero/|__aero\$', "Aero"),
    # Alloy
    (r'alloyproxy|__alloy\$', "Alloy"),
    # Terbium
    (r'terbium[._/-]|__terbium\$', "Terbium"),
    # Womginx
    (r'womginx|__womginx\$', "Womginx"),
    # NodeUnblocker
    (r'nodeunblocker', "NodeUnblocker"),
    # Meteor Proxy
    (r'meteor[_-]proxy', "Meteor"),
    # Dynamic Intercept
    (r'dynamic[_-]intercept', "Dynamic Intercept"),
    # Palladium
    (r'palladium[_-]proxy', "Palladium"),
    # Titanium Network (umbrella, if nothing more specific matched)
    (r'titaniumnetwork|titanium[_-]network', "Titanium Network"),
]
_PROXY_RE = [(re.compile(p, re.I), name) for p, name in PROXY_TECH_PATTERNS]

# ─── Network filter / block-page detection ───────────────────────────────────
#
# When FilterGuardian is running on the target network the brain visits URLs
# through Network Filter. If CK blocks a URL it returns a block page instead of
# the real site. We detect that and record it as a separate status so it doesn't
# get confused with genuinely unreachable sites.

_FILTER_PHRASES = [
    "access denied", "access blocked", "this site has been blocked",
    "blocked by", "content filtered", "category blocked",
    "fortiguard", "websense", "barracuda", "lightspeed filter",
    "securly", "cisco umbrella", "iboss", "zscaler", "goguardian",
    "contentkeeper", "request was rejected", "internet access has been restricted",
    "this website is blocked", "this page has been blocked",
    "acceptable use policy", "policy violation",
]

_FILTER_PRODUCTS = [
    ("contentkeeper",   "Network Filter"),
    ("fortiguard",      "Fortinet FortiGuard"),
    ("fortinet",        "Fortinet FortiGuard"),
    ("websense",        "Websense"),
    ("barracuda",       "Barracuda"),
    ("securly",         "Securly"),
    ("iboss",           "iBoss"),
    ("zscaler",         "Zscaler"),
    ("goguardian",      "GoGuardian"),
    ("cisco umbrella",  "Cisco Umbrella"),
    ("lightspeed",      "Lightspeed Filter"),
]

def _detect_filter_block(content_lower: str) -> str:
    """
    If content looks like a block page, return the filter product name.
    Returns '' if no block page detected.
    """
    if not any(p in content_lower for p in _FILTER_PHRASES):
        return ""
    for keyword, name in _FILTER_PRODUCTS:
        if keyword in content_lower:
            return name
    return "Network Filter"

def _is_on_premises() -> bool:
    """Read the on-premises flag from app_config.json."""
    try:
        with open("app_config.json", encoding="utf-8") as _f:
            return json.load(_f).get("on_premises", False)
    except Exception:
        return False


# ─── Category rules ──────────────────────────────────────────────────────────

CATEGORY_RULES = [
    # Gaming checked FIRST — a gaming proxy is primarily a gaming site
    ("Gaming / Arcade", [
        "arcade", "games", "play online", "gaming", "emulator", "flash games",
        "unblocked games", "coolmath", "game vault", "retro", "browser games",
        "html5 games", "io games", "io game", "minecraft", "roblox",
        "cookie clicker", "frogie", "velara", "1v1", "slope", "shell shockers",
        "yohoho", "pirate battle", "krunker", "blooket", "gimkit", "kahoot",
        "eaglercraft", "selenite", "now.gg", "nowgg", "geometry dash",
        "among us", "agar.io", "paper.io", "snake.io", "skribbl",
        "play for free", "free to play", "online multiplayer game",
    ]),
    # Proxy requires stronger evidence — "unblocked" alone is not enough
    ("Proxy / Filter Bypass", [
        "web proxy", "web proxy", "proxy site", "filter bypass",
        "bypass filter", "cloak", "unblocker", "hide ip",
        "no restrictions", "anonymous browsing",
        "ultraviolet", "rammerhead", "scramjet", "bare server",
        "nodeunblocker", "interstellar", "holy unblocker",
    ]),
    ("Streaming / Media", [
        "movie", "stream", "watch online", "tv show", "anime", "series",
        "episode", "manga", "webtoon", "crunchyroll", "putlocker", "soap",
    ]),
    ("AI / Tools", [
        "ai", "chatgpt", "gpt", "claude", "copilot", "llm", "chatbot",
        "text generator", "image generator", "ai tool",
    ]),
    ("Social / Communication", [
        "chat", "social", "forum", "community", "messaging", "discussion",
    ]),
]

# ─── Request / resource blocking ─────────────────────────────────────────────

BLOCKED_TYPES   = {"image", "media", "font", "websocket", "eventsource", "other"}
BLOCKED_DOMAINS = [
    "google-analytics.com", "googletagmanager.com", "doubleclick.net",
    "googlesyndication.com", "hotjar.com", "mixpanel.com", "segment.io",
]

# ─── Known-site fingerprint database ─────────────────────────────────────────

KNOWN_SITES_FILE = Path("known_sites.json")

def _load_known_sites() -> dict:
    if KNOWN_SITES_FILE.exists():
        try:
            with open(KNOWN_SITES_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_known_site(fp: str, name: str):
    """Persist a fingerprint → site-name mapping for future lookups."""
    db = _load_known_sites()
    if fp and fp != "error":
        db[fp] = name
        with open(KNOWN_SITES_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2)

def lookup_fingerprint(fp: str) -> str:
    """Return the known site name for this fingerprint, or ''."""
    if not fp or fp == "error":
        return ""
    return _load_known_sites().get(fp, "")


# ─── Non-blocking fingerprint queue ──────────────────────────────────────────
#
# Instead of pausing the brain to ask the operator, unknown fingerprints are
# written to pending_fingerprints.json.  The operator reviews them later via
# the app's "Review Queue" button or at brain shutdown.

PENDING_FP_FILE = Path("pending_fingerprints.json")
_fp_file_lock   = threading.Lock()
_print_lock     = threading.Lock()


def _safe_print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)


def _load_pending_fps() -> dict:
    if PENDING_FP_FILE.exists():
        try:
            with open(PENDING_FP_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def queue_fingerprint(fp: str, site_name: str, url: str, category: str,
                      screenshot_b64: str = None):
    """Queue an unrecognized fingerprint for later operator review (non-blocking)."""
    queued = False
    with _fp_file_lock:
        data = _load_pending_fps()
        if fp not in data:
            entry = {"site_name": site_name, "url": url, "category": category}
            if screenshot_b64:
                entry["screenshot"] = screenshot_b64
            data[fp] = entry
            try:
                with open(PENDING_FP_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                queued = True
            except Exception:
                pass
    if queued:
        _safe_print(f"  [FP] Queued for review: {site_name!r}  ({fp[:8]}...)")


def _process_pending_queue():
    """Interactive review of queued fingerprints at brain shutdown."""
    data  = _load_pending_fps()
    items = [(fp, info) for fp, info in data.items()]
    if not items:
        return
    print(f"\n{'='*54}")
    print(f"  FINGERPRINT REVIEW  ({len(items)} queued)")
    print(f"{'='*54}")
    for fp, info in items:
        print(f"\n  URL     : {info.get('url', '')}")
        print(f"  Current : {info.get('site_name', '')}")
        print(f"  Category: {info.get('category', '')}")
        print(f"  FP hash : {fp}")
        try:
            name = input("  Name (Enter=keep, s=skip): ").strip()
        except (EOFError, OSError):
            break
        if name.lower() == "s":
            continue
        final = name or info.get("site_name", "")
        if final:
            save_known_site(fp, final)
            database.update_site_name_by_fingerprint(fp, final)
            data.pop(fp, None)
    try:
        with open(PENDING_FP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
    print("\n[BRAIN] Queue review complete.")


# ─── Fingerprint classification gating ───────────────────────────────────────

_session_asked:      set = set()
_session_asked_lock: threading.Lock = threading.Lock()
_CLASSIFY_CATEGORIES = {"proxy / filter bypass", "gaming / arcade"}


def maybe_classify(fp: str, site_name: str, url: str,
                   proxy_tech: str, category: str,
                   screenshot_b64: str = None) -> str:
    """
    Queue unrecognized proxy/gaming fingerprints for later review.
    Non-blocking — analysis continues immediately without operator input.
    """
    if not fp or fp == "error":
        return site_name
    with _session_asked_lock:
        if fp in _session_asked:
            return site_name
        if lookup_fingerprint(fp):
            return site_name
        cat_lower = category.lower()
        if not (proxy_tech or any(c in cat_lower for c in _CLASSIFY_CATEGORIES)):
            return site_name
        _session_asked.add(fp)
    queue_fingerprint(fp, site_name, url, category, screenshot_b64=screenshot_b64)
    return site_name


# ─── Detection helpers ───────────────────────────────────────────────────────

# Pre-compiled HTML / network-URL patterns for platform detection.
# Checked against lowercased (html + all script/network URLs) when URL and
# header checks both fail to identify the host.
_PLATFORM_HTML_RE = [
    (re.compile(r"cf-ray|/__cf_chl|cloudflare-static|cf-browser-verification|cdn\.cloudflare\.com", re.I), "Cloudflare"),
    (re.compile(r"cdn\.vercel-insights|_vercel/static|vercel\.live|\.vercel\.app", re.I), "Vercel"),
    (re.compile(r"netlify\.com/|_netlify|netlify-cdn|\.netlify\.app", re.I), "Netlify"),
    (re.compile(r"fly\.io|fly-request|\.fly\.dev", re.I), "Fly.io"),
    (re.compile(r"render\.com|onrender\.com", re.I), "Render"),
    (re.compile(r"railway\.app", re.I), "Railway"),
    (re.compile(r"cdn\.glitch\.com|glitch\.me|\.glitch\.me", re.I), "Glitch"),
    (re.compile(r"replit\.com|repl\.co|replit\.dev", re.I), "Replit"),
    (re.compile(r"firebase|firebaseapp\.com|firebase-messaging|__firebase_defaults__", re.I), "Firebase"),
    (re.compile(r"github\.io|raw\.githubusercontent\.com", re.I), "GitHub Pages"),
    (re.compile(r"herokuapp\.com|herokucdn\.com", re.I), "Heroku"),
    (re.compile(r"pythonanywhere\.com", re.I), "PythonAnywhere"),
    (re.compile(r"surge\.sh", re.I), "Surge"),
    (re.compile(r"tiiny\.host", re.I), "Tiiny Host"),
    (re.compile(r"000webhost", re.I), "000WebHost"),
    (re.compile(r"neocities\.org", re.I), "Neocities"),
    (re.compile(r"cloudfront\.net|amazonaws\.com|aws-amplify", re.I), "AWS"),
    (re.compile(r"azurewebsites\.net|azurestaticapps\.net|blob\.core\.windows\.net", re.I), "Azure"),
    (re.compile(r"run\.app|appspot\.com|googleusercontent\.com|storage\.googleapis", re.I), "Google Cloud"),
    (re.compile(r"digitaloceanspaces\.com|digitalocean\.app", re.I), "DigitalOcean"),
    (re.compile(r"b-cdn\.net|bunnycdn\.com", re.I), "BunnyCDN"),
    (re.compile(r"now\.gg|nowgg\.fun", re.I), "Now.gg"),
    (re.compile(r"codepen\.io", re.I), "CodePen"),
    (re.compile(r"stackblitz\.com", re.I), "StackBlitz"),
    (re.compile(r"codesandbox\.io", re.I), "CodeSandbox"),
    (re.compile(r"backblazeb2\.com", re.I), "Backblaze B2"),
    (re.compile(r"pages\.dev|workers\.dev", re.I), "Cloudflare Pages"),
]


def _detect_platform_headers(headers: dict) -> str:
    """
    Identify hosting platform from HTTP response headers.
    Accepts a raw {header-name: value} dict (any case).
    Returns platform name or '' if undetected.
    """
    h = {k.lower(): v.lower() for k, v in headers.items()}

    # Single-header definitive signals
    if "cf-ray" in h:                                       return "Cloudflare"
    if any(k.startswith("x-vercel") for k in h):           return "Vercel"
    if "fly-request-id" in h:                              return "Fly.io"
    if "x-render-origin-server" in h:                      return "Render"
    if any(k.startswith("x-railway") for k in h):          return "Railway"
    if "x-github-request-id" in h:                         return "GitHub Pages"
    if "x-nf-request-id" in h or "x-netlify-cache-tag" in h: return "Netlify"
    if "x-amz-cf-id" in h:                                 return "AWS CloudFront"
    if any(k.startswith("x-amz") for k in h):              return "AWS"
    if any(k.startswith("x-azure") for k in h):            return "Azure"
    if any(k.startswith("x-goog") or k.startswith("x-firebase") for k in h):
        return "Google Cloud"

    # x-powered-by
    xpb = h.get("x-powered-by", "")
    if "replit" in xpb:  return "Replit"
    if "heroku" in xpb:  return "Heroku"

    # Server header
    server = h.get("server", "")
    for token, platform in [
        ("cloudflare", "Cloudflare"), ("netlify", "Netlify"),
        ("vercel", "Vercel"),         ("github", "GitHub Pages"),
        ("cowboy", "Heroku"),         ("heroku", "Heroku"),
        ("ditto", "Surge"),           ("render", "Render"),
        ("fly", "Fly.io"),
    ]:
        if token in server:
            return platform

    # Via header (Heroku's vegur proxy)
    if "vegur" in h.get("via", ""):
        return "Heroku"

    return ""


def detect_platform(url: str, headers: dict = None,
                    html_lower: str = "", extra_urls: list = None) -> str:
    """
    Exhaustive platform detection — three passes before giving up:
      1. URL domain suffixes  (fastest, most reliable)
      2. HTTP response headers (Server, CF-Ray, X-Vercel-*, etc.)
      3. HTML source + script/network URL patterns
    Falls back to 'Self-Hosted / Unknown' only if all three fail.
    """
    # Pass 1 — URL
    low = url.lower()
    for suffix, name in PLATFORM_MAP.items():
        if suffix in low:
            return name

    # Pass 2 — Response headers
    if headers:
        found = _detect_platform_headers(headers)
        if found:
            return found

    # Pass 3 — HTML + network URL haystack
    if html_lower or extra_urls:
        haystack = html_lower
        if extra_urls:
            haystack += " " + " ".join(u.lower() for u in extra_urls)
        for pattern, name in _PLATFORM_HTML_RE:
            if pattern.search(haystack):
                return name

    return "Self-Hosted / Unknown"


def detect_proxy_tech(html_lower: str, extra_urls: list) -> str:
    """
    Search for proxy framework signatures across:
      • full HTML source (already lowercased)
      • script src values extracted from the DOM
      • network request URLs captured during page load
    """
    haystack = html_lower
    if extra_urls:
        haystack += " " + " ".join(u.lower() for u in extra_urls)
    for pattern, name in _PROXY_RE:
        if pattern.search(haystack):
            return name
    return ""


def _extract_meta(html: str, prop: str) -> str:
    """Extract <meta property/name="…" content="…"> values."""
    for attr in ("property", "name"):
        # content before attr
        m = re.search(
            rf'<meta[^>]+{attr}=["\'](?:og:)?{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.I)
        if m:
            return m.group(1).strip()
        # content after attr
        m = re.search(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+{attr}=["\'](?:og:)?{re.escape(prop)}["\']',
            html, re.I)
        if m:
            return m.group(1).strip()
    return ""


# Selectors tried in order when hunting for the real site brand
_BRAND_SELECTORS = [
    "h1",
    ".site-name", ".site-title", "#site-title",
    ".brand", "#brand", ".brand-name",
    ".logo-text", ".logo-name",
    ".navbar-brand", ".nav-brand",
    "header .title", "nav .title",
    "[class*='brand']", "[class*='logo']",
    "[id*='brand']",   "[id*='logo']",
    ".title-bar", ".page-title",
]

_NOISE = {
    "", "home", "menu", "navigation", "search", "login", "sign in",
    "sign up", "register", "loading", "welcome",
}

def _extract_brand(page) -> str:
    """
    Return first non-trivial text found across brand-like selectors.
    Checks the main frame first, then all child iframes — gaming sites
    often embed their UI inside an iframe within a proxy shell.
    """
    try:
        frames = page.frames  # includes main frame as frames[0]
    except Exception:
        frames = [page]

    for frame in frames:
        for sel in _BRAND_SELECTORS:
            try:
                el = frame.query_selector(sel)
                if not el:
                    continue
                text = (el.inner_text() or "").strip()
                if text and len(text) < 120 and text.lower() not in _NOISE:
                    return text
            except Exception:
                continue
    return ""


def classify(title: str, content: str) -> str:
    combined = (title + " " + content).lower()
    for category, keywords in CATEGORY_RULES:
        if any(kw in combined for kw in keywords):
            return category
    return "Unclassified"


def fingerprint(page) -> str:
    try:
        skeleton = page.evaluate(r"""() => {
            const w = el => {
                if (!el || el.nodeType !== 1) return '';
                const tag = el.tagName.toLowerCase();
                const cls = [...el.classList].sort().join('.');
                const k = tag + (cls ? '.' + cls : '');
                return '<' + k + '>' + [...el.children].map(w).join('') + '</' + k + '>';
            };
            return w(document.body);
        }""")
        return hashlib.md5(skeleton.encode()).hexdigest()
    except Exception:
        return "error"


# ─── Core visit logic ─────────────────────────────────────────────────────────

def _visit(url_id: int, url: str):
    """
    Single browser visit. Raises on connection/navigation failure so the
    caller can decide whether to retry.
    """
    from playwright.sync_api import sync_playwright

    seen_requests: list[str] = []

    def _route(route, request):
        try:
            if request.resource_type in BLOCKED_TYPES:
                route.abort(); return
            if any(d in request.url for d in BLOCKED_DOMAINS):
                route.abort(); return
            if request.url.startswith(("file://", "data:")):
                route.abort(); return
            seen_requests.append(request.url)
            route.continue_()
        except Exception:
            try:
                route.abort()
            except Exception:
                pass

    ua       = random.choice(USER_AGENTS)
    viewport = random.choice(VIEWPORTS)
    tz       = random.choice(TIMEZONES)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
            "--disable-extensions", "--disable-background-networking",
            "--disable-sync", "--no-first-run",
            "--disable-blink-features=AutomationControlled",
        ])
        ctx = browser.new_context(
            user_agent=ua,
            viewport=viewport,
            accept_downloads=False,
            ignore_https_errors=True,
            locale="en-US",
            timezone_id=tz,
            extra_http_headers={"DNT": "1", "Sec-GPC": "1"},
        )
        ctx.set_default_timeout(15000)
        page = ctx.new_page()
        page.route("**/*", _route)

        _resp = None
        try:
            _resp = page.goto(url, wait_until="networkidle", timeout=15000)
        except Exception:
            # Fallback: accept page once DOM is ready even if network never idles
            try:
                _resp = page.goto(url, wait_until="domcontentloaded", timeout=8000)
            except Exception as e:
                browser.close()
                raise
        _resp_headers: dict = {}
        try:
            if _resp:
                _resp_headers = dict(_resp.headers)
        except Exception:
            pass

        # Brief pause for late-registering service workers
        try:
            page.wait_for_timeout(500)
        except Exception:
            pass

        final_url = page.url
        title     = page.title() or ""
        try:
            content = page.content()[:700_000]
        except Exception:
            content = ""
        content_lower = content.lower()

        # Gather script src attributes to aid proxy tech detection
        script_srcs: list[str] = []
        try:
            script_srcs = page.eval_on_selector_all(
                "script[src]", "els => els.map(e => e.src)")
        except Exception:
            pass

        all_network_hints = script_srcs + seen_requests

        platform   = detect_platform(final_url, headers=_resp_headers,
                                     html_lower=content_lower,
                                     extra_urls=all_network_hints)
        proxy_tech = detect_proxy_tech(content_lower, all_network_hints)

        # Rich metadata extraction
        og_title     = _extract_meta(content, "title")
        og_site_name = _extract_meta(content, "site_name")
        og_desc      = _extract_meta(content, "description")
        brand_text   = _extract_brand(page)  # now searches all frames incl. iframes

        category = classify(title, content_lower + " " + og_desc)

        # If proxy tech was found but content is clearly gaming, keep Gaming/Arcade.
        # If proxy tech was found and nothing else matched, force Proxy category.
        if proxy_tech and category == "Unclassified":
            category = "Proxy / Filter Bypass"

        fp = fingerprint(page)

        # Domain-based lookup: if another URL from the same host is already named,
        # inherit that name. This prevents every sub-page (e.g. arcade game URLs)
        # from becoming an orphan fingerprint with a game-specific name.
        _submitted_domain = _urlparse(url).netloc.lower()
        _final_domain     = _urlparse(final_url).netloc.lower()
        _domain_name = ""
        for _dom in dict.fromkeys([d for d in [_final_domain, _submitted_domain] if d]):
            _domain_name = database.get_site_name_by_domain(_dom)
            if _domain_name:
                break

        # Path depth — deep links (game pages inside an arcade) carry game-specific
        # brand text that overrides the actual site identity. Skip brand_text for them.
        _path_depth = len([s for s in _urlparse(final_url).path.split("/") if s])

        # Title suffix: "Snake Game | frogie's arcade v4" → "frogie's arcade v4"
        _title_site = ""
        for _sep in (" | ", " — ", " :: ", " - "):
            if _sep in title:
                _candidate = title.split(_sep)[-1].strip()
                if 2 < len(_candidate) < 60:
                    _title_site = _candidate
                    break

        # Site-name priority:
        #   1. Known fingerprint  — operator-confirmed identity
        #   2. Domain DB match    — inherit name from same-domain records
        #   3. OG site_name       — explicit <meta> identity tag
        #   4. Brand/h1 text      — only for shallow paths (depth < 2)
        #   5. Title suffix       — "Game | Site Name" → "Site Name"
        #   6. OG title
        #   7. Page title
        #   8. Proxy tech label   — last resort when we have no other identity
        #   9. Hostname fallback
        known_name = lookup_fingerprint(fp)
        if known_name:
            site_name = known_name
        elif _domain_name:
            site_name = _domain_name
            # Persist so future sessions skip DB lookup for this fingerprint
            save_known_site(fp, site_name)
        elif og_site_name and len(og_site_name) > 2:
            site_name = og_site_name[:80]
        elif brand_text and _path_depth < 2 and brand_text.lower() not in (title.lower(), ""):
            site_name = brand_text[:80]
        elif _title_site:
            site_name = _title_site
        elif og_title and og_title.lower() != title.lower() and len(og_title) > 2:
            site_name = og_title[:80]
        elif title:
            site_name = title[:80]
        elif proxy_tech:
            site_name = f"{proxy_tech} Proxy"
        else:
            m = re.search(r'https?://([^/]+)', final_url)
            site_name = m.group(1) if m else "Unknown"

        # Capture a preview snapshot for the review queue, but only if this
        # fingerprint is unknown — avoids wasting time on already-named sites.
        _snap_b64 = None
        with _session_asked_lock:
            _already_known = (fp in _session_asked) or bool(lookup_fingerprint(fp))
        if not _already_known:
            try:
                # Give JS-rendered content extra time to paint before snapping
                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                page.wait_for_timeout(2000)
                _snap_bytes = page.screenshot(
                    type="jpeg", quality=52, full_page=False, timeout=6000)
                _snap_b64 = base64.b64encode(_snap_bytes).decode("ascii")
            except Exception:
                pass

        # ── On-premises block-page detection ──────────────────────────────────
        # When the brain is running on the target network, Network Filter intercepts
        # requests to blocked sites and returns a block page instead. Detect and
        # record this as status="filtered" so it's clearly distinct from both
        # "analyzed" (real site, reached) and "failed" (unreachable).
        if _is_on_premises():
            _filter_product = _detect_filter_block(content_lower)
            if _filter_product:
                _safe_print(f"  > BLOCKED BY FILTER: {_filter_product}")
                database.update_analysis(
                    url_id=url_id, status="filtered",
                    category="Blocked by Network Filter",
                    site_name=_filter_product,
                    fingerprint=fp, platform=platform,
                    proxy_tech="", final_url=final_url,
                )
                browser.close()
                return

        # Ask operator to classify unrecognized proxy/gaming fingerprints
        site_name = maybe_classify(fp, site_name, url, proxy_tech, category,
                                   screenshot_b64=_snap_b64)

        _safe_print(f"  > {platform} | {proxy_tech or 'no tech'} | {category} | {site_name!r}")

        database.update_analysis(
            url_id=url_id, status="analyzed",
            category=category, site_name=site_name,
            fingerprint=fp, platform=platform,
            proxy_tech=proxy_tech, final_url=final_url,
        )
        browser.close()


# ─── Retry wrapper ────────────────────────────────────────────────────────────

_RETRIABLE = (
    "connection refused", "connection reset", "connection timed out",
    "eof", "net::err", "timeout", "econnrefused", "econnreset",
    "failed to connect", "socket hang up",
)

MAX_RETRIES = 3


def analyze_site(url_id: int, url: str):
    _safe_print(f"\n[BRAIN] → {url}")
    if not url.startswith(("http://", "https://")):
        database.update_analysis(url_id=url_id, status="failed",
                                 site_name="Invalid URL", category="Error")
        return

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            _visit(url_id, url)
            return
        except Exception as e:
            err = str(e).lower()
            is_retriable = any(sig in err for sig in _RETRIABLE)
            if is_retriable and attempt < MAX_RETRIES:
                wait = (2 ** attempt) * random.uniform(2, 5)
                _safe_print(f"  > [RETRY {attempt}/{MAX_RETRIES}] waiting {wait:.0f}s")
                time.sleep(wait)
                continue
            _safe_print(f"  > [FAILED] {e}")
            err_lower = str(e).lower()
            _is_conn_error = any(s in err_lower for s in
                ("connection refused", "econnrefused", "connection reset", "econnreset",
                 "net::err_connection", "no route to host"))
            if _is_conn_error and _is_on_premises():
                # Hard network block (CK drops the connection instead of serving a block page)
                _fail_name = "Hard Network Block"
            elif _is_on_premises():
                _fail_name = "Analysis Error"
            else:
                _fail_name = "Unreachable"
            database.update_analysis(url_id=url_id, status="failed",
                                     site_name=_fail_name, category="Error")
            return


# ─── Main analysis loop ───────────────────────────────────────────────────────

# 3 concurrent browser sessions.  Each worker uses a unique UA/viewport/TZ,
# so simultaneous visits to DIFFERENT sites look like separate users.
# Visits to the same origin are unlikely given diverse Discord sources.
WORKERS         = 3
INTER_BATCH_MIN = 2   # seconds between batch completions
INTER_BATCH_MAX = 5
POLL_INTERVAL   = 20  # seconds to wait when the queue is empty


def run_analyzer_loop():
    _safe_print("=" * 54)
    _safe_print(f"  FILTERGUARDIAN BRAIN  -  ACTIVE  v2.2  ({WORKERS} workers)")
    _safe_print("=" * 54)

    retried = database.reset_failed_urls()
    if retried:
        _safe_print(f"[BRAIN] Re-queued {retried} previously failed URL(s)")

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        while True:
            pending = database.get_pending_urls()
            if pending:
                _safe_print(f"\n[BRAIN] {len(pending)} URL(s) — dispatching to {WORKERS} workers")
                fs = [pool.submit(analyze_site, uid, url) for uid, url in pending]
                futures_wait(fs)
                delay = random.uniform(INTER_BATCH_MIN, INTER_BATCH_MAX)
                _safe_print(f"  [~] Batch done. Cooling {delay:.1f}s...")
                time.sleep(delay)
            else:
                time.sleep(POLL_INTERVAL)


def main():
    database.init_db()
    try:
        run_analyzer_loop()
    except KeyboardInterrupt:
        pass
    finally:
        _process_pending_queue()


if __name__ == "__main__":
    main()
