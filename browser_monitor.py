import os
import re
import time
import json
import random
from pathlib import Path
import database
import urllib.request

TRAP_KEYWORDS = ["trap", "honeypot", "do not type", "will be banned", "bot-trap", "verification-trap"]
URL_REGEX     = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
DOMAIN_REGEX  = r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}(?:\.[a-z]{2,})?'

_EXTRACT_JS = """() => {
    const texts = [];
    const sels = ['[class*="messageContent"]','code','pre','[class*="markup-"]',
                  '[class*="embedTitle"]','[class*="embedDescription"]',
                  '[class*="embedContent"]','span'];
    sels.forEach(s => document.querySelectorAll(s).forEach(el => texts.push(el.innerText)));
    return texts;
}"""

_SIDEBAR_JS = """() => {
    const sidebar = (
        document.querySelector('[class*="sidebar_"]') ||
        document.querySelector('[class*="scroller_"][class*="channel"]')
    );
    if (!sidebar) return [];
    return Array.from(sidebar.querySelectorAll('a[href*="/channels/"]'))
        .filter(a => a.getAttribute('href') && !a.getAttribute('href').includes('@me'))
        .map(a => ({
            name: ((a.querySelector('[class*="name__"]') ||
                    a.querySelector('[class*="channelName"]') || a).innerText || '').trim(),
            href: a.getAttribute('href')
        }));
}"""

_DEFAULT_KEYWORDS = [
    "url", "urls", "link", "links", "proxy", "site", "web",
    "mirror", "hub", "resource", "directory", "bot", "status",
    "update", "method", "byod", "community", "filter", "filtered",
    "custom", "bypass", "eagler", "craft", "game", "arcade",
    "leaker", "report", "partner", "flag", "cheat", "share",
    "shared", "unblocker", "unblock",
]


def load_whitelist():
    path = Path("whitelist.json")
    if not path.exists():
        return ["google.com", "discord.com", "youtube.com", "microsoft.com",
                "github.com", "spotify.com", "apple.com"]
    with open(path) as f:
        try:    return json.load(f).get("whitelisted_domains", [])
        except: return []


def log_debug(msg):
    try:
        log_path = os.path.join(os.path.expanduser("~"), "Desktop", "Guardian_Debug.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.ctime()}] {msg}\n")
    except Exception:
        pass


class BrowserMonitor:
    def __init__(self, cdp_url="http://127.0.0.1:9223", command_queue=None):
        self.cdp_url        = cdp_url
        self.command_queue  = command_queue
        self.running        = True
        self.whitelist      = load_whitelist()
        self.auto_switch    = False
        self.targets        = []
        self.min_wait       = 5
        self.max_wait       = 15
        self.last_switch_time  = 0
        self.next_switch_delay = 0
        self.cycle_index    = 0
        self.guild_map: dict[str, str] = {}
        self.current_server = "None"
        self.current_channel= "None"
        log_debug("Monitor Initialized")

    # ── Auto-cycle ────────────────────────────────────────────────────────────

    def set_auto_switch(self, enabled, targets, min_m, max_m):
        self.auto_switch    = enabled
        self.targets        = targets
        self.min_wait       = min_m * 60
        self.max_wait       = max_m * 60
        self.next_switch_delay = random.randint(self.min_wait, self.max_wait)
        self.last_switch_time  = time.time()

    # ── Navigation helpers ────────────────────────────────────────────────────

    def simulate_click(self, page, selector):
        try:
            page.bring_to_front()
            el = (page.query_selector(selector)
                  if selector.startswith(("#", "."))
                  else (page.query_selector(f'[aria-label*="{selector}" i]')
                        or page.get_by_text(selector).first))
            if el:
                el.scroll_into_view_if_needed()
                el.click(force=True)
                log_debug(f"Simulated click: {selector}")
                return True
        except Exception as e:
            log_debug(f"Click failed: {e}")
        return False

    def discover_guilds(self, page):
        # Expand any collapsed server folders so nested servers are visible
        try:
            page.evaluate("""() => {
                const nav = document.querySelector('[aria-label="Servers"]')
                         || document.querySelector('[class*="guilds"]');
                if (!nav) return;
                nav.querySelectorAll('[aria-expanded="false"]').forEach(el => {
                    try { el.click(); } catch(e) {}
                });
            }""")
            time.sleep(0.6)
        except Exception:
            pass
        try:
            guild_data = page.evaluate("""() => {
                const servers = [];
                document.querySelectorAll('[data-list-item-id^="guildsnav"]').forEach(item => {
                    const rawId = item.getAttribute('data-list-item-id');
                    if (!rawId || !rawId.includes('___')) return;
                    const guildId = rawId.split('___')[1];
                    if (guildId === 'home') return;
                    const parent = item.closest('[data-dnd-name]');
                    const name = (parent ? parent.getAttribute('data-dnd-name') : '')
                                 || item.getAttribute('aria-label')
                                 || 'Server ' + guildId;
                    servers.push({
                        name: name.replace('Unread messages, ', '').toLowerCase().trim(),
                        href: '/channels/' + guildId
                    });
                });
                return servers;
            }""")
            for g in guild_data:
                self.guild_map[g['name']] = g['href']
        except Exception as e:
            log_debug(f"Guild discovery error: {e}")

    def _match_server(self, target: str) -> str | None:
        """Fuzzy-match a configured server name against the guild map."""
        t = target.lower()
        if t in self.guild_map:
            return self.guild_map[t]
        for guild_name, href in self.guild_map.items():
            if t in guild_name or guild_name in t:
                log_debug(f"Fuzzy-matched '{target}' -> '{guild_name}'")
                return href
        return None

    def switch_server(self, page, server_name: str) -> bool:
        try:
            page.bring_to_front()
            self.current_server = server_name
            self.discover_guilds(page)
            href = self._match_server(server_name)
            if href:
                target_url = "https://discord.com" + href
                if page.url != target_url:
                    page.goto(target_url, wait_until="domcontentloaded")
                return True
            # Fallback: quick-switcher
            page.keyboard.press("Control+k")
            time.sleep(0.5)
            page.keyboard.type(server_name, delay=50)
            time.sleep(1)
            page.keyboard.press("Enter")
            time.sleep(2)
            return True
        except Exception as e:
            log_debug(f"Navigation failed: {e}")
            return self.simulate_click(page, server_name)

    # ── Sidebar sweeper ───────────────────────────────────────────────────────

    def _sweep_sidebar(self, page) -> list[tuple[str, str]]:
        """Scroll the full channel sidebar; return all (name, url) pairs."""
        seen:    set[str]                = set()
        results: list[tuple[str, str]]   = []
        page.mouse.move(200, 400)
        page.mouse.wheel(0, -9999)
        time.sleep(0.8)
        for _ in range(15):
            page.mouse.move(200, 400)
            page.mouse.wheel(0, 600)
            time.sleep(0.7)
            for c in page.evaluate(_SIDEBAR_JS):
                url = "https://discord.com" + c['href']
                if url not in seen:
                    seen.add(url)
                    raw = c['name'].split('\n')[-1].strip()
                    if raw:
                        results.append((raw, url))
        return results

    def _find_channel_url(self, page, channel_name: str) -> str | None:
        """Search the sidebar for a channel by name; return URL or None."""
        target = re.sub(r'[^a-zA-Z0-9-]', '', channel_name.lstrip('#')).lower()
        for raw, url in self._sweep_sidebar(page):
            clean = re.sub(r'[^a-zA-Z0-9-]', '', raw).lower()
            if clean == target or target in clean:
                return url
        return None

    # ── Per-channel scraper ───────────────────────────────────────────────────

    def _clean_url(self, raw: str) -> str | None:
        # Cut at the first whitespace/bracket/quote/angle delimiter so markdown
        # links ('text](url' / '<url>') don't leak brackets into the stored URL.
        url = re.split(r'[\s\'"<>\[\]()]+', raw.strip())[0].rstrip('.,;!?)]}')
        if not url.startswith('http'):
            url = "https://" + url
        if "*" in url or "." not in url or len(url) < 10:
            return None
        if any(d.lower() in url.lower() for d in self.whitelist):
            return None
        return url

    def _harvest_page(self, page, seen: set, source_label: str, progress_callback) -> bool:
        """Extract all URLs from the current page state. Returns True if any new URLs found."""
        found = False
        for text in page.evaluate(_EXTRACT_JS):
            # Do not invent a second root URL from the hostname of a full URL.
            bare_text = re.sub(URL_REGEX, " ", text)
            for raw in re.findall(URL_REGEX, text) + re.findall(DOMAIN_REGEX, bare_text.lower()):
                url = self._clean_url(raw)
                if url and url not in seen:
                    seen.add(url)
                    if database.add_url(url, "GuardianBot", source_label):
                        progress_callback(url)
                        found = True
        return found

    def _get_thread_links(self, page) -> list[str]:
        """Return thread/post URLs visible on the current page (forum channels + inline threads)."""
        try:
            return page.evaluate("""() => {
                const urls = new Set();
                document.querySelectorAll('a[href*="/channels/"]').forEach(a => {
                    const href = a.getAttribute('href') || '';
                    // Thread URLs have the form /channels/GUILD/CHANNEL/THREAD (3 numeric IDs)
                    if (/\\/channels\\/\\d+\\/\\d+\\/\\d+/.test(href)) {
                        urls.add(href);
                    }
                });
                return [...urls].slice(0, 20);
            }""")
        except Exception:
            return []

    def _scrape_channel(self, page, server_name: str, chan_name: str,
                        chan_url: str, progress_callback) -> bool:
        """Navigate to one channel and scrape all links including forum/thread posts."""
        self.current_channel = chan_name
        progress_callback(f"STATUS:{server_name} > {chan_name}")
        try:
            page.goto(chan_url, wait_until="domcontentloaded")
            time.sleep(3)
            page.mouse.move(600, 400)

            found = False
            seen: set[str] = set()
            scraped_threads: set[str] = set()
            source = f"{server_name} > {chan_name}"

            # ── Scrape main channel (scroll up through history) ───────────────
            for _ in range(20):
                if not self.running:
                    break
                if self._harvest_page(page, seen, source, progress_callback):
                    found = True
                page.mouse.move(600, 400)
                page.mouse.wheel(0, -700)
                time.sleep(0.8)

            # ── Collect visible thread / forum-post links ─────────────────────
            thread_hrefs = self._get_thread_links(page)
            if thread_hrefs:
                progress_callback(f"STATUS:{server_name} > {chan_name} — found {len(thread_hrefs)} thread(s)")

            for href in thread_hrefs:
                if not self.running:
                    break
                t_url = "https://discord.com" + href
                if t_url in scraped_threads:
                    continue
                scraped_threads.add(t_url)
                try:
                    thread_label = f"{server_name} > {chan_name} (thread)"
                    progress_callback(f"STATUS:{thread_label}")
                    page.goto(t_url, wait_until="domcontentloaded")
                    time.sleep(2)
                    page.mouse.move(600, 400)
                    for _ in range(8):
                        if not self.running:
                            break
                        if self._harvest_page(page, seen, thread_label, progress_callback):
                            found = True
                        page.mouse.wheel(0, -700)
                        time.sleep(0.6)
                except Exception as e:
                    log_debug(f"Thread scrape [{chan_name}]: {e}")

            try:
                ss = page.screenshot(type="jpeg", quality=40, timeout=2000)
                progress_callback(b"IMG:" + ss)
            except Exception:
                pass
            return found
        except Exception as e:
            log_debug(f"Scrape error [{chan_name}]: {e}")
            return False

    # ── Channel crawl (discovery + scraping) ──────────────────────────────────

    def crawl_channels(self, page, server_name: str, progress_callback,
                       keywords=None, explicit_only=None) -> list[str]:
        """
        Discover and scrape channels in the current server.

        explicit_only  : list of channel names  → targeted mode (skip keyword filter)
        keywords       : list of keyword strings → keyword mode (default)
                         Pass ['*'] or ['all'] to match every channel.
        """
        channels_with_links: list[str] = []
        try:
            progress_callback("STATUS:Sweeping Sidebar...")

            if explicit_only is not None:
                norm = {re.sub(r'[^a-zA-Z0-9-]', '', ch.lstrip('#')).lower()
                        for ch in explicit_only}
                def _match(raw: str) -> bool:
                    return re.sub(r'[^a-zA-Z0-9-]', '', raw).lower() in norm
            else:
                kw = keywords or _DEFAULT_KEYWORDS
                scan_all = any(k.strip() in ("*", "all", "everything") for k in kw)
                def _match(raw: str) -> bool:
                    clean = re.sub(r'[^a-zA-Z0-9-]', '', raw).lower()
                    return scan_all or any(k in clean for k in kw)

            channel_targets = [
                (name, url)
                for name, url in self._sweep_sidebar(page)
                if _match(name) and not database.is_channel_blacklisted(name, server_name)
            ]

            progress_callback(f"STATUS:Found {len(channel_targets)} channels")
            for name, url in channel_targets:
                if not self.running:
                    break
                if self.command_queue and not self.command_queue.empty():
                    break
                if self._scrape_channel(page, server_name, name, url, progress_callback):
                    channels_with_links.append(name)
        except Exception as e:
            log_debug(f"Crawl error: {e}")
        return channels_with_links

    # ── Unified scan engine ───────────────────────────────────────────────────

    def _run_scan(self, page, data, progress_callback):
        """
        Flexible scan engine used by FULL_SCAN and SCAN commands.

        data dict keys:
          mode    : "keyword" | "targeted" | "channel"  (default: "keyword")
          server  : restrict to this server name  (None = all targets)
          channel : channel name  (only for mode == "channel")
        """
        d        = data or {}
        mode     = d.get("mode", "keyword")
        only_srv = d.get("server")
        only_ch  = d.get("channel")

        targets_data = []
        p = Path("targets.json")
        if p.exists():
            with open(p) as f:
                targets_data = json.load(f).get("servers", [])

        if only_srv:
            targets_data = [
                t for t in targets_data
                if only_srv.lower() in t["name"].lower()
                   or t["name"].lower() in only_srv.lower()
            ]

        all_discovered: dict[str, list[str]] = {}

        for t in targets_data:
            if not self.running:
                break
            label = t["name"]
            progress_callback(f"STATUS:Scanning: {label}")
            if not self.switch_server(page, label):
                continue
            time.sleep(4)

            if mode == "channel" and only_ch:
                chan_url = self._find_channel_url(page, only_ch)
                if chan_url:
                    if self._scrape_channel(page, label, only_ch, chan_url, progress_callback):
                        all_discovered[label] = [only_ch]
                else:
                    progress_callback(f"STATUS:Channel '{only_ch}' not found in sidebar")

            elif mode == "targeted":
                explicit = t.get("explicit_channels", [])
                found = self.crawl_channels(page, label, progress_callback,
                                            explicit_only=explicit)
                if found:
                    all_discovered[label] = found

            else:  # keyword
                kw = [k.strip().lower() for k in t.get("keywords", "").split(",")
                      if k.strip()] or None
                found = self.crawl_channels(page, label, progress_callback, keywords=kw)
                if found:
                    all_discovered[label] = found

        if all_discovered:
            progress_callback(f"CHANNELS_FOUND:{json.dumps(all_discovered)}")
        progress_callback("STATUS:Scan Complete")

    # ── Auto-join ─────────────────────────────────────────────────────────────

    _JOIN_DELAY_MIN = 8   # seconds between join attempts (anti-detection)
    _JOIN_DELAY_MAX = 20
    _last_join_time = 0

    def auto_join_server(self, page, invite_url: str, progress_callback) -> str:
        """
        Attempt to join a Discord server via invite link using the linked browser.

        Returns one of:
          "joined"                — successfully joined
          "already_member"        — already in the server
          "captcha"               — hCaptcha detected, needs human input
          "member_screening"      — membership screening form shown
          "verification_required" — phone / age gate detected
          "rate_limited"          — joined too recently, try later
          "error"                 — unexpected failure
        """
        # Rate-limit: don't auto-join more than once every ~8–20 s
        now = time.time()
        since_last = now - BrowserMonitor._last_join_time
        if since_last < self._JOIN_DELAY_MIN:
            wait = self._JOIN_DELAY_MIN - since_last
            progress_callback(f"STATUS:Join rate-limited — waiting {wait:.0f}s…")
            time.sleep(wait)

        BrowserMonitor._last_join_time = time.time()

        try:
            progress_callback(f"STATUS:Navigating to invite: {invite_url}")
            page.goto(invite_url, wait_until="domcontentloaded")
            time.sleep(random.uniform(2.5, 4.0))

            # Already a member?
            if re.search(r"/channels/\d+", page.url):
                return "already_member"

            # hCaptcha present (Discord uses this before join for suspicious accounts)
            if page.query_selector("iframe[src*='hcaptcha'], [data-sitekey]"):
                return "captcha"

            # Look for the "Accept Invite" / "Join Server" button
            accept = None
            for selector in [
                "button[type='submit']",
                "[class*='joinButton']",
                "[class*='inviteButton']",
            ]:
                accept = page.query_selector(selector)
                if accept:
                    break
            if accept is None:
                # Try text-based lookup as last resort
                for label in ("Join Server", "Accept Invite", "Continue"):
                    try:
                        accept = page.get_by_role("button", name=re.compile(label, re.I)).first
                        accept.wait_for(timeout=2000)
                        break
                    except Exception:
                        accept = None

            if accept:
                # Human-like delay before clicking
                time.sleep(random.uniform(0.8, 2.2))
                accept.scroll_into_view_if_needed()
                accept.click()
                time.sleep(random.uniform(2.5, 4.0))

            # Re-check for captcha after click
            if page.query_selector("iframe[src*='hcaptcha'], [data-sitekey]"):
                return "captcha"

            # Membership screening (server rules / "Complete")
            body_text = ""
            try:
                body_text = (page.inner_text("body") or "").lower()
            except Exception:
                pass
            if any(kw in body_text for kw in ["membership screening", "server rules", "finish"]):
                # Try to click through the screening form automatically
                try:
                    for sel in ["[class*='continueButton']", "button[type='submit']"]:
                        btn = page.query_selector(sel)
                        if btn:
                            time.sleep(random.uniform(1.0, 2.0))
                            btn.click()
                            time.sleep(2.0)
                            break
                    else:
                        return "member_screening"
                except Exception:
                    return "member_screening"

            # Phone / age gate
            if any(kw in body_text for kw in
                   ["verify your age", "phone verification", "verify your phone",
                    "confirm your age", "date of birth"]):
                return "verification_required"

            # Success — Discord should have navigated into the server
            if re.search(r"/channels/\d+", page.url):
                return "joined"

            # Fallback — we navigated somewhere, assume ok
            return "joined"

        except Exception as e:
            log_debug(f"Auto-join error: {e}")
            return "error"

    # ── Main event loop ───────────────────────────────────────────────────────

    def run(self, progress_callback=None):
        if not progress_callback:
            progress_callback = lambda x: None

        connected = False
        for _ in range(5):
            try:
                with urllib.request.urlopen(f"{self.cdp_url}/json/version", timeout=2) as r:
                    if r.status == 200:
                        connected = True; break
            except Exception:
                time.sleep(1)

        if not connected:
            progress_callback("STATUS:CDP_TIMEOUT")
            return

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(self.cdp_url)
                progress_callback("STATUS:Guardian Link Active")

                while self.running:
                    # ── Command queue ─────────────────────────────────────
                    if self.command_queue and not self.command_queue.empty():
                        try:
                            cmd_type, cmd_data = self.command_queue.get_nowait()
                            pages = [pg for ctx in browser.contexts for pg in ctx.pages]
                            if not pages:
                                pass
                            elif cmd_type == "SWITCH":
                                self.switch_server(pages[0], cmd_data)
                            elif cmd_type == "CLICK":
                                self.simulate_click(pages[0], cmd_data)
                            elif cmd_type in ("FULL_SCAN", "SCAN"):
                                # FULL_SCAN (legacy / dashboard button) = keyword scan all
                                data = None if cmd_type == "FULL_SCAN" else cmd_data
                                self._run_scan(pages[0], data, progress_callback)
                            elif cmd_type == "JOIN":
                                result = self.auto_join_server(pages[0], cmd_data, progress_callback)
                                _RESULT_MSGS = {
                                    "joined":                "STATUS:✅ Joined server successfully",
                                    "already_member":        "STATUS:Already a member of that server",
                                    "captcha":               "NOTIFY:CAPTCHA detected while joining — please complete it in the browser",
                                    "member_screening":      "NOTIFY:Server requires membership screening — please complete it in the browser",
                                    "verification_required": "NOTIFY:Phone or age verification required — please complete it in the browser",
                                    "rate_limited":          "STATUS:Join rate-limited — try again shortly",
                                    "error":                 "STATUS:Join attempt failed — check the browser",
                                }
                                progress_callback(_RESULT_MSGS.get(result, f"STATUS:Join result: {result}"))
                        except Exception as e:
                            log_debug(f"Command error: {e}")

                    # ── Auto-cycle ────────────────────────────────────────
                    if self.auto_switch and self.targets:
                        now = time.time()
                        if now - self.last_switch_time > self.next_switch_delay:
                            target_server = self.targets[self.cycle_index % len(self.targets)]
                            progress_callback(f"STATUS:Auto-Cycle: {target_server}")
                            pages = [pg for ctx in browser.contexts for pg in ctx.pages]
                            if pages and self.switch_server(pages[0], target_server):
                                time.sleep(4)
                                self.crawl_channels(pages[0], target_server, progress_callback)
                            self.cycle_index += 1
                            self.last_switch_time = now
                            self.next_switch_delay = random.randint(self.min_wait, self.max_wait)

                    # ── Idle screenshot ───────────────────────────────────
                    pages = [pg for ctx in browser.contexts for pg in ctx.pages]
                    if pages:
                        try:
                            ss = pages[0].screenshot(type="jpeg", quality=30, timeout=1000)
                            progress_callback(b"IMG:" + ss)
                        except Exception:
                            pass
                    time.sleep(2)

        except Exception as e:
            log_debug(f"Monitor Crash: {e}")
            raise

    def stop(self):
        self.running = False
