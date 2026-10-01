"""
relay_agent.py — FilterGuardian Network Test Relay
====================================================
Deploy on any machine already connected to the target network
(designated computer, spare laptop on the target LAN, etc.).

Requirements:
  Best results — pip install playwright && playwright install chromium
  Fallback     — Python 3.8+ standard library only (less accurate)

Why Playwright?
  urllib doesn't replicate browser behaviour on filtered networks:
  it ignores PAC files, Group Policy proxy settings, and presents a
  non-browser TLS fingerprint.  Network Filter may handle it differently
  from real browser traffic.  Playwright IS a real browser — it reads
  the same system proxy settings Chrome does, follows PAC files, handles
  MITM SSL certs with ignore_https_errors, and renders JS block pages.

Usage:
    python relay_agent.py
    python relay_agent.py --port 9224 --token mysecret

Security:
  - --token <secret>  require the same token in FilterGuardian settings.
  - Only accepts GET /test?url=... — cannot be used as a general proxy.
"""

import json, re, socket, ssl, sys
import urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn


# ── Threading server ──────────────────────────────────────────────────────────
class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


# ── Playwright availability ───────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright as _sync_playwright
    _PW_AVAILABLE = True
except ImportError:
    _PW_AVAILABLE = False


# ── urllib SSL fallback context ───────────────────────────────────────────────
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode    = ssl.CERT_NONE


# ── Block-page detection ──────────────────────────────────────────────────────
_BLOCK_PHRASES = [
    "access denied", "access blocked", "access has been blocked",
    "access to this site", "access to this page", "access to this website",
    "this site has been blocked", "this site is blocked",
    "this website is blocked", "this website has been blocked",
    "this page has been blocked", "this page is blocked",
    "this web page is blocked", "this web page has been filtered",
    "blocked by", "has been blocked", "has been restricted",
    "content filtered", "content has been blocked",
    "category blocked", "this category is blocked",
    "internet access has been restricted", "internet access is restricted",
    "web access blocked", "web filtering", "web filter",
    "your request has been blocked", "your request was blocked",
    "request was rejected", "request blocked",
    "restricted by", "restricted access",
    "filtered by", "filtered content",
    "policy violation", "acceptable use policy", "acceptable use",
    "network policy", "usage policy",
    "not permitted", "not allowed",
    "contentkeeper", "content keeper", "app defender",
    "ck filtering", "ck filter",
    "fortiguard", "fortigate", "websense", "forcepoint", "barracuda",
    "lightspeed filter", "lightspeed systems", "securly",
    "cisco umbrella", "opendns", "iboss", "zscaler", "goguardian",
    "smoothwall", "netsweeper", "linewize", "mobicip", "impero",
]

_BLOCK_TITLE_WORDS = (
    "blocked", "restricted", "filtered", "denied",
    "not allowed", "access denied", "app defender",
)


def _page_title(html: str) -> str:
    m = re.search(r'<title[^>]*>([^<]{1,120})</title>', html, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _is_block_content(html: str) -> bool:
    t = html.lower()
    if any(p in t for p in _BLOCK_PHRASES):
        return True
    title = _page_title(html).lower()
    return any(w in title for w in _BLOCK_TITLE_WORDS)


def _is_block_redirect(original_url: str, final_url: str) -> bool:
    if not final_url or final_url.rstrip("/") == original_url.rstrip("/"):
        return False
    try:
        orig_host  = urllib.parse.urlparse(original_url).netloc.lower().lstrip("www.")
        final      = urllib.parse.urlparse(final_url)
        final_host = final.netloc.lower().lstrip("www.")
        if orig_host == final_host:
            return False
        if re.match(r'^\d+\.\d+\.\d+\.\d+(:\d+)?$', final_host):
            return True  # redirected to bare IP = filter appliance
        combined = (final_host + final.path).lower()
        if any(w in combined for w in ("blocked", "filtered", "denied",
                                        "restricted", "filter", "block",
                                        "violation", "policy")):
            return True
    except Exception:
        pass
    return False


# ── DNS pre-check ───────────────────────────────────────────────────────────
def _host_resolves(url: str) -> bool:
    """
    Return False only for a genuine NXDOMAIN (the domain does not exist).

    The relay runs ON the target network, so a real filter block resolves the
    host to the appliance's IP (or returns a block page) rather than failing
    DNS. A clean resolution failure here therefore means the proxy domain is
    genuinely gone — a dead site, not a block. Any non-DNS error falls through
    so the fetcher can make the call.
    """
    try:
        host = urllib.parse.urlparse(url).hostname
        if not host:
            return True  # malformed URL — let the fetcher surface the real error
        socket.getaddrinfo(host, None)
        return True
    except socket.gaierror:
        return False
    except Exception:
        return True


def _read_settled(page):
    """
    Read (final_url, title, content) after letting any client-side redirect
    settle.

    Proxy cover pages JS-redirect from the landing page to the real arcade, so
    page.content() called immediately after `domcontentloaded` frequently fires
    mid-navigation and raises "page is navigating and changing the content."
    Wait the navigation out and retry instead of giving up (that single race was
    ~72% of all ERROR results in testing).
    """
    last_exc = None
    for _ in range(4):
        try:
            return page.url, page.title(), page.content()
        except Exception as e:
            msg = str(e).lower()
            if "navigat" in msg or "changing the content" in msg:
                last_exc = e
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    pass
                page.wait_for_timeout(600)
                continue
            raise
    if last_exc:
        page.wait_for_timeout(400)
    return page.url, page.title(), page.content()  # final try; caller handles failure


# ── Playwright fetch (preferred) ──────────────────────────────────────────────
def _fetch_playwright(url: str, proxy: str) -> dict:
    """
    Fetch url using a headless Chromium browser.
    - ignore_https_errors=True  → proceeds past expired Network Filter MITM certs
    - No proxy arg needed       → Playwright reads system/Group Policy proxy automatically
    - proxy arg overrides       → when --proxy is explicitly given
    """
    with _sync_playwright() as pw:
        launch_opts = {"headless": True}
        ctx_opts    = {"ignore_https_errors": True}
        if proxy:
            ctx_opts["proxy"] = {"server": proxy}

        browser = pw.chromium.launch(**launch_opts)
        try:
            ctx  = browser.new_context(**ctx_opts)
            page = ctx.new_page()
            try:
                resp = page.goto(url, timeout=20000, wait_until="domcontentloaded")
                final_url, title, content = _read_settled(page)

                if _is_block_redirect(url, final_url):
                    return {"result": "blocked",
                            "detail": f"Redirected to filter: {final_url[:80]}"}
                if _is_block_content(content):
                    return {"result": "blocked",
                            "detail": f"Block page — \"{title}\"" if title
                                      else "Block page content detected"}
                status = resp.status if resp else "?"
                return {"result": "allowed",
                        "detail": f"HTTP {status}" + (f' — "{title}"' if title else "")}

            except Exception as e:
                err = str(e).lower()
                if any(k in err for k in ("net::err_connection_refused",
                                           "connection refused")):
                    return {"result": "blocked",
                            "detail": "Hard block (TCP reset — no block page)"}
                if any(k in err for k in ("net::err_name_not_resolved",
                                           "getaddrinfo")):
                    return {"result": "dead", "detail": "Domain does not resolve (NXDOMAIN)"}
                if "timeout" in err:
                    return {"result": "error", "detail": "Timed out"}
                return {"result": "error", "detail": str(e)[:100]}
            finally:
                page.close(); ctx.close()
        finally:
            browser.close()


# ── urllib fetch (fallback) ───────────────────────────────────────────────────
def _fetch_urllib(url: str, proxy: str) -> dict:
    """
    Fallback when Playwright is not installed.
    Less accurate — does not follow PAC files or Group Policy proxy
    settings the same way a browser would.
    """
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        handlers = [urllib.request.HTTPSHandler(context=_SSL_CTX)]
        if proxy:
            handlers.append(urllib.request.ProxyHandler(
                {"http": proxy, "https": proxy}))
        opener = urllib.request.build_opener(*handlers)
        with opener.open(req, timeout=15) as resp:
            final_url = resp.geturl()
            content   = resp.read(16000).decode("utf-8", errors="replace")
            title     = _page_title(content)
            if _is_block_redirect(url, final_url):
                return {"result": "blocked",
                        "detail": f"Redirected to filter: {final_url[:80]}"}
            if _is_block_content(content):
                return {"result": "blocked",
                        "detail": f"Block page — \"{title}\"" if title
                                  else "Block page content detected"}
            detail = f"HTTP {resp.status}" + (f' — "{title}"' if title else "")
            return {"result": "allowed", "detail": detail}

    except urllib.error.HTTPError as e:
        if e.code in (403, 407):
            return {"result": "blocked", "detail": f"HTTP {e.code}"}
        return {"result": "error", "detail": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        reason = str(e.reason).lower()
        if "no connection could be made" in reason or "connection refused" in reason:
            return {"result": "blocked",
                    "detail": "Hard block (TCP reset — no block page)"}
        if "timed out" in reason or "no route" in reason:
            return {"result": "error", "detail": "Unreachable (timeout)"}
        if any(k in reason for k in ("getaddrinfo", "name or service not known",
                                      "name not known", "no such host",
                                      "nodename nor servname")):
            return {"result": "dead", "detail": "Domain does not resolve (NXDOMAIN)"}
        return {"result": "error", "detail": str(e.reason)[:100]}
    except Exception as e:
        return {"result": "error", "detail": str(e)[:100]}


# ── HTTP handler ──────────────────────────────────────────────────────────────
_TOKEN = ""
_PROXY = ""


class _RelayHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[relay]  {self.address_string()}  {fmt % args}")

    def _json(self, data: dict, code: int = 200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if _TOKEN and params.get("token", [""])[0] != _TOKEN:
            self._json({"result": "error", "detail": "Unauthorized"}, 403)
            return
        if parsed.path == "/ping":
            self._json({"result": "ok",
                        "detail": f"relay alive ({'playwright' if _PW_AVAILABLE else 'urllib'})"})
            return
        if parsed.path != "/test":
            self._json({"result": "error", "detail": "Unknown endpoint"}, 404)
            return

        url = params.get("url", [""])[0]
        if not url:
            self._json({"result": "error", "detail": "No URL provided"})
            return
        if not url.startswith(("http://", "https://")):
            self._json({"result": "error", "detail": "Invalid URL scheme"})
            return

        # Cheap NXDOMAIN check first — skip the full browser fetch for dead
        # domains and report them as 'dead' rather than polluting 'error'.
        if not _host_resolves(url):
            self._json({"result": "dead", "detail": "Domain does not resolve (NXDOMAIN)"})
            return

        if _PW_AVAILABLE:
            result = _fetch_playwright(url, _PROXY)
        else:
            result = _fetch_urllib(url, _PROXY)

        self._json(result)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    global _TOKEN, _PROXY
    port = 9224
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--port"  and i + 1 < len(args): port   = int(args[i + 1])
        if a == "--token" and i + 1 < len(args): _TOKEN = args[i + 1]
        if a == "--proxy" and i + 1 < len(args): _PROXY = args[i + 1]

    if _PROXY and not _PROXY.startswith(("http://", "https://")):
        _PROXY = "http://" + _PROXY

    mode = "Playwright (browser mode)" if _PW_AVAILABLE else \
           "urllib (fallback — less accurate)"

    print("=" * 60)
    print("  FilterGuardian Relay Agent")
    print(f"  Mode     : {mode}")
    print(f"  Port     : {port}")
    print(f"  Token    : {'set (' + _TOKEN[:4] + '…)' if _TOKEN else 'none'}")
    if _PROXY:
        print(f"  Proxy    : {_PROXY}")
    if not _PW_AVAILABLE:
        print()
        print("  ⚠  Playwright not found — results may be inaccurate.")
        print("     For reliable testing run:")
        print("       pip install playwright")
        print("       playwright install chromium")
    print("=" * 60)
    print(f"  FilterGuardian → Settings → Network Filter Test")
    print(f"    Method : Relay Agent")
    print(f"    Address: http://<THIS_MACHINE_IP>:{port}")
    print()

    try:
        _ThreadingHTTPServer(("0.0.0.0", port), _RelayHandler).serve_forever()
    except KeyboardInterrupt:
        print("\n[relay] Stopped.")


if __name__ == "__main__":
    main()
