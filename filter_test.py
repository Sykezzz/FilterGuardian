"""
filter_test.py — FilterGuardian Network Filter Testing
=======================================================
Provides URL reachability tests via:
  • HTTP proxy  (network's web proxy, if you know its address)
  • Relay agent (relay_agent.py running on a target-network machine)
"""

import ssl
import urllib.error
import urllib.parse
import urllib.request

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

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
    "fortiguard", "fortigate", "websense", "forcepoint", "barracuda",
    "lightspeed filter", "lightspeed systems", "securly",
    "cisco umbrella", "opendns", "iboss", "zscaler", "goguardian",
    "smoothwall", "netsweeper", "linewize", "mobicip", "impero",
]

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _page_title(html: str) -> str:
    import re
    m = re.search(r'<title[^>]*>([^<]{1,120})</title>', html, re.IGNORECASE)
    return m.group(1).strip() if m else ""

def _is_block_page(content: bytes) -> bool:
    try:
        t = content.decode("utf-8", errors="replace")
    except Exception:
        return False
    tl = t.lower()
    if any(p in tl for p in _BLOCK_PHRASES):
        return True
    title = _page_title(t).lower()
    _BLOCK_TITLE_WORDS = ("blocked", "restricted", "filtered", "denied",
                          "not allowed", "access denied", "app defender")
    return any(w in title for w in _BLOCK_TITLE_WORDS)


def _result(status: str, detail: str) -> dict:
    return {"result": status, "detail": detail}


# ── Proxy-based test ──────────────────────────────────────────────────────────

def test_via_proxy(url: str, proxy_addr: str, timeout: int = 10) -> dict:
    """
    Test URL through an HTTP/HTTPS proxy.
    proxy_addr format: 'http://host:port'  (include http:// prefix)

    Returns {"result": "allowed"|"blocked"|"dead"|"error", "detail": str}
    """
    if not proxy_addr.startswith(("http://", "https://")):
        proxy_addr = "http://" + proxy_addr
    try:
        proxy_handler = urllib.request.ProxyHandler(
            {"http": proxy_addr, "https": proxy_addr})
        opener = urllib.request.build_opener(proxy_handler, urllib.request.HTTPSHandler(context=_SSL_CTX))
        opener.addheaders = list(_HEADERS.items())
        resp = opener.open(url, timeout=timeout)
        content = resp.read(4000)
        if _is_block_page(content):
            return _result("blocked", "Block page content detected")
        return _result("allowed", f"HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        if e.code in (403, 407):
            return _result("blocked", f"HTTP {e.code}")
        return _result("error", f"HTTP {e.code}")
    except urllib.error.URLError as e:
        reason = str(e.reason).lower()
        if "connection refused" in reason or "timed out" in reason:
            return _result("error", "Proxy unreachable")
        if any(k in reason for k in ("getaddrinfo", "name or service not known",
                                      "name not known", "no such host",
                                      "nodename nor servname")):
            return _result("dead", "Domain does not resolve (NXDOMAIN)")
        return _result("error", str(e.reason)[:80])
    except Exception as e:
        return _result("error", str(e)[:80])


# ── Relay-agent test ──────────────────────────────────────────────────────────

def test_via_relay(url: str, relay_url: str, token: str = "",
                   timeout: int = 12) -> dict:
    """
    Test URL through relay_agent.py running on the target network.
    relay_url: base URL of the agent, e.g. 'http://relay.example:9224'

    Returns {"result": "allowed"|"blocked"|"dead"|"error", "detail": str}
    """
    import json
    if not relay_url.startswith(("http://", "https://")):
        relay_url = "http://" + relay_url
    try:
        params = {"url": url}
        if token:
            params["token"] = token
        qs = urllib.parse.urlencode(params)
        req_url = f"{relay_url.rstrip('/')}/test?{qs}"
        with urllib.request.urlopen(req_url, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        return _result("error", f"Relay unreachable: {str(e.reason)[:60]}")
    except Exception as e:
        return _result("error", str(e)[:80])


def ping_relay(relay_url: str, token: str = "", timeout: int = 5) -> bool:
    """Return True if the relay agent responds to a /ping request."""
    import json
    if not relay_url.startswith(("http://", "https://")):
        relay_url = "http://" + relay_url
    try:
        params = {"token": token} if token else {}
        qs = ("?" + urllib.parse.urlencode(params)) if params else ""
        with urllib.request.urlopen(
                f"{relay_url.rstrip('/')}/ping{qs}", timeout=timeout) as r:
            data = json.loads(r.read())
            return data.get("result") == "ok"
    except Exception:
        return False
