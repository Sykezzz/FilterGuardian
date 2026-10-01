"""
main.py — FilterGuardian v2.0
==============================
Ground-up UI rewrite. Screen recorder removed.
New: 5 themes, system tray, Analytics page, dedicated Live Monitor,
     searchable Database with detail popup, improved Targets management.
"""

import sys, os, re, time, json, subprocess, base64
from pathlib import Path
from queue import Queue

def get_asset_path(p):
    return os.path.join(os.path.abspath("."), p)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QFrame, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox, QLineEdit, QSpinBox,
    QComboBox, QScrollArea, QDialog, QTextEdit, QButtonGroup,
    QPushButton, QSystemTrayIcon, QMenu, QAbstractItemView, QRadioButton,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QIcon, QColor, QPixmap, QImage, QPainter, QFont, QAction

import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

import theme
from theme import (
    get_stylesheet, apply_theme, get_chart_colors, THEMES,
    SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL, SPACE_2XL, SPACE_XS,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_DISABLED,
    ACCENT_BLUE, ACCENT_RED, ACCENT_GREEN, ACCENT_YELLOW,
    FONT_SIZE_SMALL, FONT_SIZE_BODY, FONT_SIZE_HEADING,
)
from widgets import (
    Label, Card, MetricCard, PrimaryButton, SecondaryButton,
    GhostButton, NavButton, Divider, show_toast,
)
import database
from browser_monitor import BrowserMonitor


# ══════════════════════════════════════════════════════════════════════════════
#  APP CONFIG  (persisted across restarts)
# ══════════════════════════════════════════════════════════════════════════════

CONFIG_FILE   = Path("app_config.json")
_CFG_DEFAULTS = {"theme": "dark", "user_name": "Guardian", "show_welcome": True}

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                return {**_CFG_DEFAULTS, **json.load(f)}
        except Exception:
            pass
    return dict(_CFG_DEFAULTS)

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
#  BROWSER THREAD
# ══════════════════════════════════════════════════════════════════════════════

class BrowserMonitorThread(QThread):
    signal = Signal(object)
    error  = Signal(str)

    def __init__(self, cdp_url="http://127.0.0.1:9223", cmd_queue=None):
        super().__init__()
        self.cmd_queue = cmd_queue
        self.monitor   = BrowserMonitor(cdp_url, command_queue=cmd_queue)

    def run(self):
        try:    self.monitor.run(progress_callback=self.signal.emit)
        except Exception as e: self.error.emit(str(e))

    def stop(self): self.monitor.stop(); self.wait()


# ══════════════════════════════════════════════════════════════════════════════
#  FILTER TEST WORKER
# ══════════════════════════════════════════════════════════════════════════════

class _TestWorker(QThread):
    """Runs URL reachability tests in the background via proxy or relay agent."""
    row_done = Signal(int, str, str, str, str)   # idx, url, site, result, detail
    finished = Signal()

    def __init__(self, urls, method: str, addr: str, token: str = ""):
        super().__init__()
        self.urls   = urls    # list of (url, site_name)
        self.method = method  # "proxy" | "relay"
        self.addr   = addr
        self.token  = token
        self._stop  = False

    def stop(self): self._stop = True

    def run(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import filter_test as ft

        def _test(args):
            idx, url, site = args
            if self._stop:
                return idx, url, site, "cancelled", ""
            try:
                if self.method == "proxy":
                    r = ft.test_via_proxy(url, self.addr)
                else:
                    r = ft.test_via_relay(url, self.addr, self.token)
            except Exception as e:
                r = {"result": "error", "detail": str(e)[:60]}
            return idx, url, site, r.get("result", "error"), r.get("detail", "")

        tasks = [(i, url, site) for i, (url, site) in enumerate(self.urls)]
        with ThreadPoolExecutor(max_workers=10) as pool:
            futs = {pool.submit(_test, t): t for t in tasks}
            for fut in as_completed(futs):
                if self._stop:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    self.row_done.emit(*fut.result())
                except Exception:
                    pass
        self.finished.emit()


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED APP STATE
# ══════════════════════════════════════════════════════════════════════════════

class _State:
    browser_thread: BrowserMonitorThread = None
    cmd_queue: Queue = None
    brain_process = None
    session_count: int = 0
    last_pixmap: QPixmap = None

S = _State()

def is_live(): return S.browser_thread is not None and S.browser_thread.isRunning()
def send_cmd(t, d=None):
    if is_live() and S.cmd_queue: S.cmd_queue.put((t, d)); return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def load_targets():
    p = Path("targets.json")
    if not p.exists(): return []
    with open(p) as f:
        try:
            d = json.load(f)
            if "targets" in d and "servers" not in d:
                m = [{"name": n, "keywords": "", "explicit_channels": []}
                     for n in d["targets"] if isinstance(n, str)]
                save_targets(m); return m
            return d.get("servers", [])
        except: return []

def save_targets(servers):
    with open("targets.json", "w") as f:
        json.dump({"servers": servers}, f, indent=4)


# ══════════════════════════════════════════════════════════════════════════════
#  URL DETAIL DIALOG
# ══════════════════════════════════════════════════════════════════════════════

_EDIT_CATEGORIES = [
    "Proxy / Filter Bypass", "Gaming / Arcade", "Streaming / Media",
    "AI / Tools", "Social / Communication", "Unclassified", "Error",
]
_EDIT_PROXY_TECHS = [
    "", "Ultraviolet", "Rammerhead", "Scramjet", "Bare Server", "Corrosion",
    "Interstellar", "Holy Unblocker", "Epoxy", "Aero", "Alloy",
    "Terbium", "Womginx", "NodeUnblocker", "Meteor", "Dynamic Intercept",
    "Palladium", "Titanium Network",
]
_EDIT_STATUSES = ["analyzed", "pending", "failed", "reviewed", "filtered"]


def _ro_label(text: str) -> QLabel:
    """Read-only, selectable value label."""
    lbl = QLabel(str(text) if text else "—")
    lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lbl.setStyleSheet(f"color:{TEXT_PRIMARY}; font-size:{FONT_SIZE_BODY}px;")
    return lbl

def _field_label(text: str) -> QLabel:
    lbl = QLabel(text + ":")
    lbl.setFixedWidth(90)
    lbl.setStyleSheet(
        f"color:{TEXT_SECONDARY}; font-size:{FONT_SIZE_SMALL}px; font-weight:600;")
    return lbl


class URLEditDialog(QDialog):
    """Full edit + detail dialog for a single URL record."""

    def __init__(self, url_id: int, parent=None):
        super().__init__(parent)
        self.url_id = url_id
        self.setWindowTitle("Edit Record")
        self.setMinimumWidth(680)
        self.setMinimumHeight(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_XL, SPACE_XL, SPACE_XL, SPACE_XL)
        layout.setSpacing(SPACE_MD)

        layout.addWidget(Label("Edit Record", variant="heading"))
        layout.addWidget(Divider())

        d = database.get_url_detail(url_id)
        if not d:
            layout.addWidget(Label("Record not found.", variant="body"))
            layout.addStretch()
            layout.addWidget(PrimaryButton("Close"))
            return

        # ── Read-only info ────────────────────────────────────────────────
        for lbl_text, key in [("URL", "url"), ("Source", "channel_id"), ("Discovered", "timestamp")]:
            row = QHBoxLayout()
            row.addWidget(_field_label(lbl_text))
            row.addWidget(_ro_label(d.get(key, "")), 1)
            layout.addLayout(row)

        layout.addWidget(Divider())
        layout.addWidget(Label("Editable fields", variant="caption"))

        # ── Editable fields ───────────────────────────────────────────────
        def _row(label_text, widget):
            r = QHBoxLayout()
            r.addWidget(_field_label(label_text))
            r.addWidget(widget, 1)
            layout.addLayout(r)

        self.f_status = QComboBox()
        self.f_status.addItems(_EDIT_STATUSES)
        self.f_status.setCurrentText(d.get("status", "pending"))
        _row("Status", self.f_status)

        self.f_site_name = QLineEdit(d.get("site_name", "") or "")
        self.f_site_name.setPlaceholderText("e.g. frogie's arcade")
        _row("Site Name", self.f_site_name)

        self.f_category = QComboBox()
        self.f_category.setEditable(True)
        self.f_category.addItems(_EDIT_CATEGORIES)
        self.f_category.setCurrentText(d.get("category", "") or "")
        _row("Category", self.f_category)

        self.f_platform = QLineEdit(d.get("platform", "") or "")
        self.f_platform.setPlaceholderText("e.g. Cloudflare Pages")
        _row("Platform", self.f_platform)

        self.f_proxy_tech = QComboBox()
        self.f_proxy_tech.setEditable(True)
        self.f_proxy_tech.addItems(_EDIT_PROXY_TECHS)
        self.f_proxy_tech.setCurrentText(d.get("proxy_tech", "") or "")
        _row("Proxy Tech", self.f_proxy_tech)

        layout.addWidget(Divider())

        # ── Fingerprint row with "save as known site" ─────────────────────
        fp = d.get("fingerprint", "") or ""
        fp_row = QHBoxLayout()
        fp_row.addWidget(_field_label("Fingerprint"))
        fp_row.addWidget(_ro_label(fp), 1)
        if fp and fp != "error":
            save_fp_btn = GhostButton("  📌 Save as Known Site  ")
            save_fp_btn.clicked.connect(lambda: self._save_fingerprint(fp))
            fp_row.addWidget(save_fp_btn)
        layout.addLayout(fp_row)

        final_row = QHBoxLayout()
        final_row.addWidget(_field_label("Final URL"))
        final_row.addWidget(_ro_label(d.get("final_url", "")), 1)
        layout.addLayout(final_row)

        layout.addStretch()

        # ── Buttons ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        cancel_btn = SecondaryButton("  Cancel  ")
        cancel_btn.clicked.connect(self.reject)
        reanalyze_btn = GhostButton("  🔄 Re-analyze  ")
        reanalyze_btn.clicked.connect(self._reanalyze)
        save_btn = PrimaryButton("  Save Changes  ")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(reanalyze_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _save(self):
        database.update_url_manual(
            url_id    = self.url_id,
            site_name = self.f_site_name.text().strip(),
            category  = self.f_category.currentText().strip(),
            platform  = self.f_platform.text().strip(),
            proxy_tech= self.f_proxy_tech.currentText().strip(),
            status    = self.f_status.currentText(),
        )
        self.accept()

    def _reanalyze(self):
        database.requeue_url(self.url_id)
        self.accept()

    def _save_fingerprint(self, fp: str):
        name = self.f_site_name.text().strip()
        if not name:
            show_toast(self.parent(), "Enter a Site Name first", variant="warning")
            return
        try:
            import json
            from pathlib import Path
            ks_file = Path("known_sites.json")
            db = {}
            if ks_file.exists():
                with open(ks_file, encoding="utf-8") as f:
                    db = json.load(f)
            db[fp] = name
            with open(ks_file, "w", encoding="utf-8") as f:
                json.dump(db, f, indent=2)
            count = database.update_site_name_by_fingerprint(fp, name)
            msg = f"Fingerprint saved: {name}"
            if count: msg += f"  ({count} records updated)"
            show_toast(self.parent(), msg, variant="success")
        except Exception as e:
            show_toast(self.parent(), f"Save failed: {e}", variant="error")


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE 1 — DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

class DashboardPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        outer = QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.addWidget(scroll)
        inner = QWidget(); scroll.setWidget(inner)
        L = QVBoxLayout(inner)
        L.setContentsMargins(SPACE_2XL, SPACE_2XL, SPACE_2XL, SPACE_2XL)
        L.setSpacing(SPACE_LG)

        # Header
        hdr = QHBoxLayout()
        hb = QVBoxLayout()
        hb.addWidget(Label("Dashboard", variant="display"))
        _name = load_config().get("user_name", "Guardian")
        self.sub = Label(
            f"Welcome back, {_name}. System idle — link a browser to start monitoring.",
            variant="subtitle")
        hb.addWidget(self.sub)
        hdr.addLayout(hb); hdr.addStretch()
        self.location_badge = QLabel()
        self.location_badge.setStyleSheet(
            f"font-size:{FONT_SIZE_SMALL}px; font-weight:600; padding:3px 10px;"
            f" border-radius:10px;")
        hdr.addWidget(self.location_badge)
        self.brain_badge = QLabel("● BRAIN OFFLINE"); self.brain_badge.setObjectName("status_idle")
        hdr.addWidget(self.brain_badge)
        L.addLayout(hdr)
        self.refresh_location()

        # Metrics
        mr = QHBoxLayout(); mr.setSpacing(SPACE_MD)
        self.m_total    = MetricCard("Total URLs",   "0", icon="🔗")
        self.m_analyzed = MetricCard("Analyzed",     "0", color=ACCENT_GREEN, icon="🧠")
        self.m_pending  = MetricCard("Pending",      "0", color=ACCENT_YELLOW, icon="⏳")
        self.m_session  = MetricCard("This Session", "0", color=ACCENT_BLUE, icon="📡")
        for m in [self.m_total, self.m_analyzed, self.m_pending, self.m_session]:
            mr.addWidget(m)
        L.addLayout(mr)

        # Middle row: Quick actions + Live feed
        mid = QHBoxLayout(); mid.setSpacing(SPACE_LG)

        # Quick actions
        qa = Card(); qa.add_title("Quick Actions", "Browser & brain controls")
        qa.setMinimumWidth(240); qa.setMaximumWidth(280)
        self.browser_status = QLabel("● DISCONNECTED"); self.browser_status.setObjectName("status_idle")
        self.link_btn = PrimaryButton("  🔗  Link to Browser  ")
        self.link_btn.clicked.connect(self._toggle_browser)
        qa.layout.addWidget(self.browser_status)
        qa.layout.addWidget(self.link_btn)
        qa.layout.addWidget(Divider())
        self.scan_btn = SecondaryButton("  🚀  Full Scan  ")
        self.scan_btn.clicked.connect(self._full_scan); self.scan_btn.setEnabled(False)
        self.brain_btn = SecondaryButton("  🧠  Start Brain  ")
        self.brain_btn.clicked.connect(self._toggle_brain)
        qa.layout.addWidget(self.scan_btn); qa.layout.addWidget(self.brain_btn)
        qa.layout.addStretch(); mid.addWidget(qa)

        # Recent discoveries feed
        fc = Card(); fc.add_title("Recent Discoveries", "Live URL feed")
        self.feed_scroll = QScrollArea(); self.feed_scroll.setWidgetResizable(True)
        self.feed_scroll.setFrameShape(QFrame.NoFrame); self.feed_scroll.setMinimumHeight(280)
        self.feed_w = QWidget(); self.feed_L = QVBoxLayout(self.feed_w)
        self.feed_L.setSpacing(4); self.feed_L.setContentsMargins(0,0,0,0)
        self.feed_L.addStretch(); self.feed_scroll.setWidget(self.feed_w)
        fc.layout.addWidget(self.feed_scroll); mid.addWidget(fc, 1)
        L.addLayout(mid); L.addStretch()

        self._timer = QTimer(self); self._timer.timeout.connect(self.refresh_stats); self._timer.start(8000)
        self.refresh_stats()

    def refresh_welcome(self):
        cfg = load_config()
        name = cfg.get("user_name", "Guardian")
        if is_live():
            self.sub.setText(f"Hey {name}, monitoring is active.")
        else:
            self.sub.setText(
                f"Welcome back, {name}. System idle — link a browser to start monitoring.")

    def refresh_location(self):
        on_prem = load_config().get("on_premises", False)
        if on_prem:
            self.location_badge.setText("🏫  On Filtered Network")
            self.location_badge.setStyleSheet(
                f"font-size:{FONT_SIZE_SMALL}px; font-weight:600; padding:3px 10px;"
                f" border-radius:10px; background:#f97316; color:white;")
        else:
            self.location_badge.setText("🏠  Remote / Home")
            self.location_badge.setStyleSheet(
                f"font-size:{FONT_SIZE_SMALL}px; font-weight:600; padding:3px 10px;"
                f" border-radius:10px; background:{ACCENT_BLUE}; color:white;")

    # ── Browser ──────────────────────────────────────────────────────────────

    def _toggle_browser(self):
        if is_live():
            S.browser_thread.stop(); S.browser_thread = None
            self.link_btn.setText("  🔗  Link to Browser  ")
            self._set_status(self.browser_status, "● DISCONNECTED", "status_idle")
            self.scan_btn.setEnabled(False); self.sub.setText("Disconnected.")
        else:
            if not load_config().get("browser_monitor_enabled", False):
                QMessageBox.information(self, "Browser monitoring is disabled",
                    "Open Settings > Setup menu to enable monitoring for your own targets.")
                return
            if QMessageBox.question(self, "Connect browser monitoring",
                    "Connect to the local Chrome debugging session and read messages from your configured targets? "
                    "If needed, Chrome will open with a separate local profile for you to sign in. "
                    "Only monitor servers you are authorized to access.",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            if not self._ensure_cdp(): return
            S.cmd_queue = Queue()
            S.browser_thread = BrowserMonitorThread("http://127.0.0.1:9223", S.cmd_queue)
            S.browser_thread.signal.connect(self._on_signal)
            S.browser_thread.error.connect(self._on_error)
            S.browser_thread.start()
            self.link_btn.setText("  ■  Unlink Browser  ")
            self._set_status(self.browser_status, "● CONNECTED", "status_live")
            self.scan_btn.setEnabled(True)

    def _ensure_cdp(self):
        import socket
        s = socket.socket(); s.settimeout(1)
        ok = s.connect_ex(('127.0.0.1', 9223)) == 0; s.close()
        if ok: return True
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser("~") + r"\AppData\Local\Google\Chrome\Application\chrome.exe",
        ]
        chrome = next((p for p in paths if os.path.exists(p)), None)
        if not chrome:
            QMessageBox.warning(self, "Chrome Not Found",
                "Launch Chrome manually:\nchrome.exe --remote-debugging-port=9223"); return False
        try:
            ud = os.path.join(os.getcwd(), "chrome_debug_profile"); os.makedirs(ud, exist_ok=True)
            subprocess.Popen([chrome, "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9223",
                              f"--user-data-dir={ud}", "--disable-gpu", "https://discord.com/app"])
            import socket
            for _ in range(12):
                time.sleep(0.5); s = socket.socket(); s.settimeout(1)
                ok = s.connect_ex(('127.0.0.1',9223)) == 0; s.close()
                if ok: return True
        except Exception as e: QMessageBox.warning(self, "Error", str(e))
        return False

    def _full_scan(self):
        if send_cmd("FULL_SCAN"): show_toast(self.window(), "🚀 Full scan started", variant="success")
        else: show_toast(self.window(), "Link a browser first!", variant="warning")

    def _toggle_brain(self):
        if S.brain_process and S.brain_process.poll() is None:
            try:
                import psutil; p = psutil.Process(S.brain_process.pid)
                for c in p.children(recursive=True): c.kill(); p.kill()
            except: S.brain_process.terminate()
            S.brain_process = None
            self.brain_btn.setText("  🧠  Start Brain  ")
            self._set_status(self.brain_badge, "● BRAIN OFFLINE", "status_idle")
        else:
            if QMessageBox.question(self, "Start URL analysis",
                    "The Brain will visit pending URLs using Playwright Chromium and store classifications "
                    "and preview images locally. It does not change your Windows proxy or certificates. Start now?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            try:
                S.brain_process = subprocess.Popen(
                    [sys.executable, "analyzer.py"],
                    creationflags=subprocess.CREATE_NEW_CONSOLE)
                self.brain_btn.setText("  ■  Stop Brain  ")
                self._set_status(self.brain_badge, "● BRAIN ACTIVE", "status_live")
                show_toast(self.window(), "Brain started", variant="success")
            except Exception as e: QMessageBox.critical(self, "Error", str(e))

    # ── Signal router ─────────────────────────────────────────────────────────

    def _on_signal(self, data):
        mw = self.window()
        if isinstance(data, bytes) and data.startswith(b"IMG:"):
            pix = QPixmap.fromImage(QImage.fromData(data[4:]))
            S.last_pixmap = pix
            if hasattr(mw, "live_page"): mw.live_page.update_feed(pix)
            return
        if isinstance(data, str):
            if data.startswith("CHANNELS_FOUND:"):
                self._handle_discovered(json.loads(data.split(":",1)[1])); return
            if data.startswith("NOTIFY:"):
                msg = data.split(":", 1)[1]
                mw = self.window()
                if hasattr(mw, "tray"):
                    mw.tray.showMessage(
                        "FilterGuardian — Action Required", msg,
                        QSystemTrayIcon.Warning, 8000)
                show_toast(mw, f"⚠️ {msg}", variant="warning")
                return
            if data.startswith("STATUS:"):
                msg = data.split(":",1)[1]; self.sub.setText(f"📡 {msg}")
                if hasattr(mw, "live_page"): mw.live_page.update_status(msg)
                return
            # URL found
            S.session_count += 1
            self.m_session.set_value(str(S.session_count))
            self._add_feed_item(data); self.refresh_stats()

    def _on_error(self, err):
        if S.browser_thread: S.browser_thread.stop()
        S.browser_thread = None
        self.link_btn.setText("  🔗  Link to Browser  ")
        self._set_status(self.browser_status, "● ERROR", "status_error")
        self.scan_btn.setEnabled(False)
        show_toast(self.window(), f"Browser error: {err[:60]}", variant="error")

    def _add_feed_item(self, url: str):
        item = QFrame(); item.setObjectName("feed_item")
        row = QHBoxLayout(item); row.setContentsMargins(SPACE_SM, SPACE_XS, SPACE_SM, SPACE_XS)
        dot = QLabel("🔗"); dot.setStyleSheet("font-size:11px;")
        lbl = QLabel(url); lbl.setStyleSheet(f"color:{TEXT_PRIMARY}; font-size:{FONT_SIZE_SMALL}px;")
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse); lbl.setWordWrap(False)
        ts = QLabel(time.strftime("%H:%M"))
        ts.setStyleSheet(f"color:{TEXT_DISABLED}; font-size:{FONT_SIZE_SMALL}px;"); ts.setFixedWidth(40)
        row.addWidget(dot); row.addWidget(lbl, 1); row.addWidget(ts)
        self.feed_L.insertWidget(self.feed_L.count()-1, item)
        while self.feed_L.count() > 52:
            w = self.feed_L.itemAt(0).widget()
            if w: w.deleteLater()
            self.feed_L.removeItem(self.feed_L.itemAt(0))
        QTimer.singleShot(50, lambda: self.feed_scroll.verticalScrollBar().setValue(
            self.feed_scroll.verticalScrollBar().maximum()))

    def _handle_discovered(self, discovered: dict):
        summary = "".join(f"\n  {s}: {', '.join(ch)}" for s, ch in discovered.items())
        if QMessageBox.question(self, "New Channels Found",
                f"Links discovered in:{summary}\n\nAdd to targets?",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            targets = load_targets()
            for s_name, chans in discovered.items():
                for t in targets:
                    if t["name"].lower() == s_name.lower():
                        ec = t.setdefault("explicit_channels", [])
                        for c in chans:
                            if c not in ec: ec.append(c)
            save_targets(targets); show_toast(self.window(), "✅ Targets updated!", variant="success")
            mw = self.window()
            if hasattr(mw, "targets_page"): mw.targets_page.refresh()
            if hasattr(mw, "live_page"): mw.live_page.refresh_toolbox()

    def refresh_stats(self):
        try:
            st = database.get_stats()
            self.m_total.set_value(str(st["total"]))
            self.m_analyzed.set_value(str(st["analyzed"]))
            self.m_pending.set_value(str(st["pending"]))
        except: pass
        if S.brain_process and S.brain_process.poll() is not None:
            S.brain_process = None; self.brain_btn.setText("  🧠  Start Brain  ")
            self._set_status(self.brain_badge, "● BRAIN OFFLINE", "status_idle")

    @staticmethod
    def _set_status(lbl, text, obj_name):
        lbl.setText(text); lbl.setObjectName(obj_name); lbl.setStyle(lbl.style())


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE 2 — LIVE MONITOR
# ══════════════════════════════════════════════════════════════════════════════

class LiveMonitorPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        L = QHBoxLayout(self); L.setContentsMargins(0,0,0,0); L.setSpacing(0)

        # Feed area (left)
        feed_frame = QFrame(); feed_frame.setStyleSheet("background:#000;")
        ff_L = QVBoxLayout(feed_frame); ff_L.setContentsMargins(0,0,0,0)

        # Status bar
        sb = QFrame()
        sb.setStyleSheet(f"background:{theme._t()['bg_surface']}; border-bottom:1px solid {theme._t()['border']};")
        sb_L = QHBoxLayout(sb); sb_L.setContentsMargins(SPACE_LG, SPACE_SM, SPACE_LG, SPACE_SM)
        self.status_pill = QLabel("● DISCONNECTED"); self.status_pill.setObjectName("status_idle")
        self.srv_lbl = QLabel("Server: —")
        self.srv_lbl.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:{FONT_SIZE_SMALL}px;")
        self.ch_lbl = QLabel("Channel: —")
        self.ch_lbl.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:{FONT_SIZE_SMALL}px;")
        sb_L.addWidget(self.status_pill); sb_L.addSpacing(16)
        sb_L.addWidget(self.srv_lbl); sb_L.addSpacing(12); sb_L.addWidget(self.ch_lbl); sb_L.addStretch()
        ff_L.addWidget(sb)

        # Image
        self.feed_scroll = QScrollArea(); self.feed_scroll.setWidgetResizable(True)
        self.feed_scroll.setFrameShape(QFrame.NoFrame)
        self.live_img = QLabel("No feed — link a browser on the Dashboard.")
        self.live_img.setAlignment(Qt.AlignCenter)
        self.live_img.setStyleSheet(f"color:{TEXT_DISABLED}; font-size:14px;")
        self.live_img.setMinimumHeight(400)
        self.feed_scroll.setWidget(self.live_img)
        ff_L.addWidget(self.feed_scroll, 1)
        L.addWidget(feed_frame, 1)

        # Control panel (right)
        ctrl = QFrame(); ctrl.setFixedWidth(320)
        ctrl.setStyleSheet(f"background:{theme._t()['bg_surface']}; border-left:1px solid {theme._t()['border']};")
        cL = QVBoxLayout(ctrl); cL.setContentsMargins(SPACE_LG, SPACE_XL, SPACE_LG, SPACE_XL); cL.setSpacing(SPACE_LG)

        cL.addWidget(Label("Monitor Controls", variant="heading"))
        cL.addWidget(Divider())
        cL.addWidget(Label("Navigate To", variant="caption"))
        self.nav_combo = QComboBox(); self.nav_combo.setEditable(True)
        self.nav_combo.setPlaceholderText("Select server or channel…")
        self.refresh_dropdown()
        nav_btn = PrimaryButton("  ▶  Go  "); nav_btn.clicked.connect(self._navigate)
        cL.addWidget(self.nav_combo); cL.addWidget(nav_btn); cL.addWidget(Divider())

        # ── Scan Toolbox ─────────────────────────────────────────────────
        cL.addWidget(Label("Scan Mode", variant="caption"))
        self.rb_keyword  = QRadioButton("Keyword Scan")
        self.rb_targeted = QRadioButton("Targeted Scan")
        self.rb_keyword.setChecked(True)
        _mode_grp = QButtonGroup(self)
        _mode_grp.addButton(self.rb_keyword); _mode_grp.addButton(self.rb_targeted)
        cL.addWidget(self.rb_keyword); cL.addWidget(self.rb_targeted)

        cL.addWidget(Label("Scope", variant="caption"))
        self.rb_all    = QRadioButton("All Servers")
        self.rb_single = QRadioButton("Single Server")
        self.rb_ch     = QRadioButton("Single Channel")
        self.rb_all.setChecked(True)
        _scope_grp = QButtonGroup(self)
        _scope_grp.addButton(self.rb_all)
        _scope_grp.addButton(self.rb_single)
        _scope_grp.addButton(self.rb_ch)
        cL.addWidget(self.rb_all); cL.addWidget(self.rb_single); cL.addWidget(self.rb_ch)

        self.scan_srv_combo = QComboBox()
        for _t in load_targets(): self.scan_srv_combo.addItem(_t["name"])
        self.scan_srv_combo.setVisible(False)
        self.scan_ch_combo = QComboBox(); self.scan_ch_combo.setEditable(True)
        self.scan_ch_combo.setPlaceholderText("Channel name…")
        self.scan_ch_combo.setVisible(False)
        cL.addWidget(self.scan_srv_combo); cL.addWidget(self.scan_ch_combo)

        self.rb_all.toggled.connect(self._update_scope_vis)
        self.rb_single.toggled.connect(self._update_scope_vis)
        self.rb_ch.toggled.connect(self._update_scope_vis)
        self.scan_srv_combo.currentTextChanged.connect(self._populate_ch_combo)

        start_scan_btn = PrimaryButton("  🚀  Start Scan  ")
        start_scan_btn.clicked.connect(self._start_scan)
        cL.addWidget(start_scan_btn); cL.addWidget(Divider())

        cL.addWidget(Label("Auto-Cycle", variant="caption"))
        r1 = QHBoxLayout(); r1.addWidget(QLabel("Min (min):")); self.min_sp = QSpinBox()
        self.min_sp.setRange(1,60); self.min_sp.setValue(5); r1.addWidget(self.min_sp); cL.addLayout(r1)
        r2 = QHBoxLayout(); r2.addWidget(QLabel("Max (min):")); self.max_sp = QSpinBox()
        self.max_sp.setRange(1,120); self.max_sp.setValue(15); r2.addWidget(self.max_sp); cL.addLayout(r2)
        self.cycle_btn = SecondaryButton("  ⏱️  Enable Auto-Cycle  ")
        self.cycle_btn.clicked.connect(self._toggle_cycle); self._cycling = False
        cL.addWidget(self.cycle_btn); cL.addStretch()

        save_btn = GhostButton("  💾  Save Screenshot  "); save_btn.clicked.connect(self._save_ss)
        cL.addWidget(save_btn)
        L.addWidget(ctrl)

    def update_feed(self, pix: QPixmap):
        painter = QPainter(pix)
        painter.setPen(QColor(ACCENT_RED))
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        painter.drawText(14, 28, f"● LIVE  {time.strftime('%H:%M:%S')}"); painter.end()
        self.live_img.setPixmap(pix.scaledToWidth(max(100, self.feed_scroll.width()-10), Qt.SmoothTransformation))
        self.live_img.setText("")

    def update_status(self, msg: str):
        self.status_pill.setText(f"● {msg.upper()}")
        self.status_pill.setObjectName("status_live"); self.status_pill.setStyle(self.status_pill.style())
        if ">" in msg:
            parts = msg.split(">")
            self.srv_lbl.setText(f"Server: {parts[0].strip()}")
            self.ch_lbl.setText(f"Channel: #{parts[-1].strip()}")

    def refresh_dropdown(self):
        self.nav_combo.clear()
        for t in load_targets():
            self.nav_combo.addItem(f"Server: {t['name']}")
            for c in t.get("explicit_channels", []): self.nav_combo.addItem(f"#{c}")

    def _navigate(self):
        t = self.nav_combo.currentText().strip()
        if not t: return
        if not is_live(): show_toast(self.window(), "Link a browser first!", variant="warning"); return
        if t.startswith("Server: "): send_cmd("SWITCH", t.replace("Server: ","").strip()); show_toast(self.window(), f"Switching…")
        elif t.startswith("#"): send_cmd("CLICK", t.lstrip("#").strip()); show_toast(self.window(), f"Navigating to: {t}")
        else: send_cmd("CLICK", t)

    def _full_scan(self):
        if send_cmd("FULL_SCAN"): show_toast(self.window(), "🚀 Full scan started", variant="success")
        else: show_toast(self.window(), "Link a browser first!", variant="warning")

    def _update_scope_vis(self):
        srv_vis = self.rb_single.isChecked() or self.rb_ch.isChecked()
        self.scan_srv_combo.setVisible(srv_vis)
        self.scan_ch_combo.setVisible(self.rb_ch.isChecked())

    def _populate_ch_combo(self, srv: str):
        self.scan_ch_combo.clear()
        for t in load_targets():
            if t["name"] == srv:
                for c in t.get("explicit_channels", []):
                    self.scan_ch_combo.addItem(c)
                break

    def _start_scan(self):
        if not is_live():
            show_toast(self.window(), "Link a browser first!", variant="warning")
            return
        mode   = "keyword" if self.rb_keyword.isChecked() else "targeted"
        server = None; channel = None
        if self.rb_single.isChecked():
            server = self.scan_srv_combo.currentText()
        elif self.rb_ch.isChecked():
            server  = self.scan_srv_combo.currentText()
            channel = self.scan_ch_combo.currentText().lstrip("#").strip()
        send_cmd("SCAN", {"mode": mode, "server": server, "channel": channel})
        show_toast(self.window(), "Scan started", variant="success")

    def refresh_toolbox(self):
        cur = self.scan_srv_combo.currentText()
        self.scan_srv_combo.blockSignals(True)
        self.scan_srv_combo.clear()
        for t in load_targets(): self.scan_srv_combo.addItem(t["name"])
        idx = self.scan_srv_combo.findText(cur)
        self.scan_srv_combo.setCurrentIndex(max(0, idx) if idx >= 0 else 0)
        self.scan_srv_combo.blockSignals(False)
        self._populate_ch_combo(self.scan_srv_combo.currentText())
        self.refresh_dropdown()

    def _toggle_cycle(self):
        if not is_live(): show_toast(self.window(), "Link a browser first!", variant="warning"); return
        self._cycling = not self._cycling
        targets = [t["name"] for t in load_targets()]
        if S.browser_thread and hasattr(S.browser_thread.monitor, "set_auto_switch"):
            S.browser_thread.monitor.set_auto_switch(self._cycling, targets, self.min_sp.value(), self.max_sp.value())
        self.cycle_btn.setText("  ⏹️  Disable  " if self._cycling else "  ⏱️  Enable Auto-Cycle  ")
        show_toast(self.window(), f"Auto-cycle {'on' if self._cycling else 'off'}", variant="success" if self._cycling else "info")

    def _save_ss(self):
        if S.last_pixmap:
            path, _ = QFileDialog.getSaveFileName(self, "Save Screenshot", "", "Images (*.png *.jpg)")
            if path: S.last_pixmap.save(path); show_toast(self.window(), "Screenshot saved", variant="success")
        else: show_toast(self.window(), "No screenshot yet", variant="warning")


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE 3 — ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

class ChartCanvas(FigureCanvas):
    def __init__(self, figsize=(5, 3.5)):
        bg, fg, grid, pal = get_chart_colors()
        self.fig = Figure(figsize=figsize, facecolor=bg, tight_layout=True)
        super().__init__(self.fig)
        self._bg = bg; self._fg = fg; self._grid = grid; self._pal = pal
        self.setMinimumHeight(240)

    def reset(self):
        self.fig.clf()
        bg, fg, grid, pal = get_chart_colors()
        self._bg = bg; self._fg = fg; self._grid = grid; self._pal = pal
        self.fig.set_facecolor(bg)

    def ax(self):
        a = self.fig.add_subplot(111); a.set_facecolor(self._bg)
        a.tick_params(colors=self._fg, labelsize=8)
        for sp in a.spines.values(): sp.set_edgecolor(self._grid)
        return a

    def _no_data(self):
        self.reset(); ax = self.ax()
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center",
                color=self._fg, fontsize=11, alpha=0.5)
        self.draw()


class AnalyticsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        outer = QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.addWidget(scroll)
        inner = QWidget(); scroll.setWidget(inner)
        L = QVBoxLayout(inner)
        L.setContentsMargins(SPACE_2XL, SPACE_2XL, SPACE_2XL, SPACE_2XL); L.setSpacing(SPACE_LG)

        hdr = QHBoxLayout(); hdr.addWidget(Label("Analytics", variant="display")); hdr.addStretch()
        rep_btn = SecondaryButton("  📊  Reports  ")
        rep_btn.clicked.connect(self._open_reports)
        hdr.addWidget(rep_btn)
        ref = SecondaryButton("  🔄  Refresh  "); ref.clicked.connect(self.refresh); hdr.addWidget(ref)
        L.addLayout(hdr)
        L.addWidget(Label("Auto-refreshes every 30 seconds.", variant="subtitle"))
        L.addWidget(Divider())

        # Row 1: category + platform
        r1 = QHBoxLayout(); r1.setSpacing(SPACE_LG)
        c1 = Card(); c1.add_title("Category Breakdown", "What types of sites are proxied")
        self.cat_c = ChartCanvas(); c1.layout.addWidget(self.cat_c); r1.addWidget(c1, 1)
        c2 = Card(); c2.add_title("Hosting Platform", "Where proxy sites are deployed")
        self.plat_c = ChartCanvas(); c2.layout.addWidget(self.plat_c); r1.addWidget(c2, 1)
        L.addLayout(r1)

        # Row 2: proxy tech + timeline
        r2 = QHBoxLayout(); r2.setSpacing(SPACE_LG)
        c3 = Card(); c3.add_title("Proxy Technology", "Frameworks detected")
        self.tech_c = ChartCanvas(); c3.layout.addWidget(self.tech_c); r2.addWidget(c3, 1)
        c4 = Card(); c4.add_title("Discovery Timeline", "URLs found per day (last 30 days)")
        self.time_c = ChartCanvas(figsize=(7,3.5)); c4.layout.addWidget(self.time_c); r2.addWidget(c4, 2)
        L.addLayout(r2)

        # Top site names chart
        sn = Card(); sn.add_title("Top Site Names", "Most-seen identified sites")
        self.sites_c = ChartCanvas(figsize=(10, 3.2))
        sn.layout.addWidget(self.sites_c)
        L.addWidget(sn)

        # Sources table
        sc = Card(); sc.add_title("Top Source Channels", "Channels yielding the most URLs")
        self.src_tbl = QTableWidget(); self.src_tbl.setColumnCount(2)
        self.src_tbl.setHorizontalHeaderLabels(["Channel / Source","URLs Found"])
        self.src_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.src_tbl.setMaximumHeight(200); self.src_tbl.setSelectionMode(QAbstractItemView.NoSelection)
        sc.layout.addWidget(self.src_tbl); L.addWidget(sc)

        self._auto = QTimer(self); self._auto.timeout.connect(self.refresh); self._auto.start(30000)
        self.refresh()

    def refresh(self):
        self._cat(); self._plat(); self._tech(); self._timeline(); self._sites(); self._sources()

    def _cat(self):
        rows = database.get_category_breakdown()
        self.cat_c.reset()
        if not rows: self.cat_c._no_data(); return
        ax = self.cat_c.ax()
        labels = [r[0] for r in rows]; sizes = [r[1] for r in rows]
        wedges, _, auts = ax.pie(sizes, labels=None, autopct="%1.0f%%",
            colors=self.cat_c._pal[:len(labels)], startangle=140, pctdistance=0.8,
            wedgeprops={"linewidth":2,"edgecolor":self.cat_c._bg})
        for t in auts: t.set_color(self.cat_c._bg); t.set_fontsize(8); t.set_fontweight("bold")
        ax.legend(wedges, labels, loc="lower center", bbox_to_anchor=(0.5,-0.12),
                  ncol=2, fontsize=7, frameon=False, labelcolor=self.cat_c._fg)
        self.cat_c.draw()

    def _plat(self):
        rows = database.get_platform_breakdown()
        self.plat_c.reset()
        if not rows: self.plat_c._no_data(); return
        ax = self.plat_c.ax()
        labels = [r[0] for r in rows][:8]; vals = [r[1] for r in rows][:8]
        bars = ax.barh(labels, vals, color=self.plat_c._pal[1], height=0.6)
        ax.set_xlabel("URLs", color=self.plat_c._fg, fontsize=8)
        ax.xaxis.grid(True, color=self.plat_c._grid, linewidth=0.5, alpha=0.5); ax.set_axisbelow(True); ax.invert_yaxis()
        for bar, val in zip(bars, vals):
            ax.text(bar.get_width()+0.1, bar.get_y()+bar.get_height()/2, str(val), va="center", color=self.plat_c._fg, fontsize=8)
        self.plat_c.draw()

    def _tech(self):
        rows = database.get_proxy_tech_breakdown()
        self.tech_c.reset()
        if not rows: self.tech_c._no_data(); return
        ax = self.tech_c.ax()
        labels = [r[0] for r in rows]; vals = [r[1] for r in rows]
        ax.bar(range(len(labels)), vals, color=self.tech_c._pal[4], width=0.6)
        ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)
        ax.yaxis.grid(True, color=self.tech_c._grid, linewidth=0.5, alpha=0.5); ax.set_axisbelow(True)
        self.tech_c.draw()

    def _timeline(self):
        rows = database.get_timeline()
        self.time_c.reset()
        if not rows: self.time_c._no_data(); return
        ax = self.time_c.ax()
        dates = [r[0] for r in rows]; counts = [r[1] for r in rows]
        ax.fill_between(range(len(dates)), counts, alpha=0.2, color=self.time_c._pal[0])
        ax.plot(range(len(dates)), counts, color=self.time_c._pal[0], linewidth=2, marker="o", markersize=4)
        step = max(1, len(dates)//6)
        ax.set_xticks(range(0, len(dates), step))
        ax.set_xticklabels([dates[i] for i in range(0, len(dates), step)], rotation=20, ha="right", fontsize=7)
        ax.yaxis.grid(True, color=self.time_c._grid, linewidth=0.5, alpha=0.5); ax.set_axisbelow(True)
        ax.set_ylabel("URLs", color=self.time_c._fg, fontsize=8)
        self.time_c.draw()

    def _sites(self):
        rows = database.get_top_site_names()
        self.sites_c.reset()
        if not rows: self.sites_c._no_data(); return
        ax = self.sites_c.ax()
        labels = [r[0] for r in rows]
        vals   = [r[1] for r in rows]
        colors = self.sites_c._pal
        bar_colors = [colors[i % len(colors)] for i in range(len(labels))]
        bars = ax.barh(labels, vals, color=bar_colors, height=0.65)
        ax.set_xlabel("URLs", color=self.sites_c._fg, fontsize=8)
        ax.xaxis.grid(True, color=self.sites_c._grid, linewidth=0.5, alpha=0.5)
        ax.set_axisbelow(True)
        ax.invert_yaxis()
        for bar, val in zip(bars, vals):
            ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2,
                    str(val), va="center", color=self.sites_c._fg, fontsize=8)
        self.sites_c.draw()

    def _sources(self):
        rows = database.get_top_sources()
        self.src_tbl.setRowCount(len(rows))
        for i, (ch, cnt) in enumerate(rows):
            self.src_tbl.setItem(i, 0, QTableWidgetItem(ch or "—"))
            self.src_tbl.setItem(i, 1, QTableWidgetItem(str(cnt)))

    def _open_reports(self):
        dlg = ReportDialog(self)
        dlg.exec()


# ══════════════════════════════════════════════════════════════════════════════
#  FINGERPRINT REVIEW DIALOG
# ══════════════════════════════════════════════════════════════════════════════

class FingerprintReviewDialog(QDialog):
    """Review and name queued unknown fingerprints without blocking the brain."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fingerprint Review Queue")
        self.setMinimumWidth(740); self.setMinimumHeight(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_XL, SPACE_XL, SPACE_XL, SPACE_XL)
        layout.setSpacing(SPACE_MD)

        layout.addWidget(Label("Fingerprint Review Queue", variant="heading"))
        layout.addWidget(Label(
            "Each entry is a unique structural fingerprint — one name covers every URL "
            "that shares it. Saving updates all matching database records automatically.",
            variant="body"))
        layout.addWidget(Divider())

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget(); scroll.setWidget(inner)
        self._form_L = QVBoxLayout(inner); self._form_L.setSpacing(SPACE_MD)
        layout.addWidget(scroll, 1)

        self._rows: list = []
        self._load_rows()

        layout.addWidget(Divider())
        btn_row = QHBoxLayout()
        cancel_btn  = SecondaryButton("  Close  "); cancel_btn.clicked.connect(self.reject)
        save_btn    = PrimaryButton("  💾  Save All  "); save_btn.clicked.connect(self._save_all)
        btn_row.addWidget(cancel_btn); btn_row.addStretch(); btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _load_rows(self):
        while self._form_L.count():
            it = self._form_L.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        self._rows = []

        try:
            fp_file = Path("pending_fingerprints.json")
            if not fp_file.exists():
                self._form_L.addWidget(Label("No pending fingerprints.", variant="body"))
                return
            with open(fp_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self._form_L.addWidget(Label("Error loading queue.", variant="body"))
            return

        # Deduplicate by fingerprint key (JSON dict already guarantees uniqueness,
        # but guard against any legacy duplicates just in case)
        seen_fps: set = set()
        items = []
        for fp, info in data.items():
            if fp not in seen_fps:
                seen_fps.add(fp)
                items.append((fp, info))

        if not items:
            self._form_L.addWidget(Label("No pending fingerprints.", variant="body"))
            return

        for fp, info in items:
            match_count = database.count_by_fingerprint(fp)
            card = Card()

            # ── Site snapshot ─────────────────────────────────────────────
            snap_b64 = info.get("screenshot")
            if snap_b64:
                try:
                    pix = QPixmap.fromImage(
                        QImage.fromData(base64.b64decode(snap_b64)))
                    thumb_lbl = QLabel()
                    thumb_lbl.setPixmap(
                        pix.scaledToWidth(660, Qt.SmoothTransformation))
                    thumb_lbl.setAlignment(Qt.AlignCenter)
                    thumb_lbl.setStyleSheet(
                        "border:1px solid rgba(255,255,255,0.08); border-radius:6px;")
                    card.layout.addWidget(thumb_lbl)
                except Exception:
                    pass

            # ── Fingerprint identity row ──────────────────────────────────
            fp_row = QHBoxLayout()
            fp_row.addWidget(_field_label("Fingerprint"))
            fp_lbl = QLabel(f"{fp[:16]}…")
            fp_lbl.setStyleSheet(
                f"color:{TEXT_DISABLED}; font-size:{FONT_SIZE_SMALL}px; font-family:monospace;")
            fp_lbl.setToolTip(fp)
            fp_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            fp_row.addWidget(fp_lbl)
            fp_row.addStretch()
            match_lbl = QLabel(f"  {match_count} URL{'s' if match_count != 1 else ''} in database")
            match_lbl.setStyleSheet(
                f"color:{ACCENT_BLUE}; font-size:{FONT_SIZE_SMALL}px; font-weight:600;")
            fp_row.addWidget(match_lbl)
            card.layout.addLayout(fp_row)

            # ── Example URL + category ────────────────────────────────────
            for lbl_text, key in [("Example URL", "url"), ("Category", "category")]:
                row = QHBoxLayout()
                row.addWidget(_field_label(lbl_text))
                val_lbl = QLabel(str(info.get(key, "") or "—"))
                val_lbl.setStyleSheet(f"color:{TEXT_PRIMARY}; font-size:{FONT_SIZE_SMALL}px;")
                val_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                val_lbl.setWordWrap(True)
                row.addWidget(val_lbl, 1)
                card.layout.addLayout(row)

            # ── Name input ────────────────────────────────────────────────
            name_row = QHBoxLayout()
            name_row.addWidget(_field_label("Site Name"))
            name_in = QLineEdit(info.get("site_name", ""))
            name_in.setPlaceholderText("Enter site name — will apply to all matching URLs…")
            name_row.addWidget(name_in, 1)
            card.layout.addLayout(name_row)

            self._form_L.addWidget(card)
            self._rows.append((fp, info, name_in))

        self._form_L.addStretch()

    def _save_all(self):
        try:
            fp_file = Path("pending_fingerprints.json")
            data = json.load(open(fp_file, encoding="utf-8")) if fp_file.exists() else {}
        except Exception:
            data = {}

        ks_file = Path("known_sites.json")
        ks = {}
        try:
            if ks_file.exists():
                with open(ks_file, encoding="utf-8") as f: ks = json.load(f)
        except Exception:
            pass

        saved = 0
        for fp, info, name_in in self._rows:
            name = name_in.text().strip()
            if not name: continue
            ks[fp] = name
            database.update_site_name_by_fingerprint(fp, name)
            data.pop(fp, None)
            saved += 1

        try:
            with open(ks_file, "w", encoding="utf-8") as f: json.dump(ks, f, indent=2)
            with open(fp_file, "w", encoding="utf-8") as f: json.dump(data, f, indent=2)
        except Exception as e:
            show_toast(self.parent(), f"Save error: {e}", variant="error"); return

        show_toast(self.parent(), f"Saved {saved} site name(s)", variant="success")
        self._load_rows()


# ══════════════════════════════════════════════════════════════════════════════
#  FILTER TEST DIALOG
# ══════════════════════════════════════════════════════════════════════════════

_RESULT_COLORS = {
    "allowed":   ACCENT_GREEN,
    "blocked":   ACCENT_RED,
    "error":     ACCENT_YELLOW,
    "dead":      TEXT_DISABLED,
    "cancelled": TEXT_DISABLED,
}

class FilterTestDialog(QDialog):
    """Test which URLs pass through the org's network filter via proxy or relay agent."""

    def __init__(self, urls: list, parent=None):
        """urls: list of (url, site_name) tuples to test."""
        super().__init__(parent)
        self.setWindowTitle("Network Filter Test")
        self.setMinimumWidth(860); self.setMinimumHeight(620)
        self._worker: _TestWorker = None
        self._urls = urls

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_XL, SPACE_XL, SPACE_XL, SPACE_XL)
        layout.setSpacing(SPACE_MD)

        layout.addWidget(Label("Network Filter Test", variant="heading"))
        layout.addWidget(Label(
            "Tests URLs from the database through your environment's filter — "
            "without changing your IP. Requires either a proxy address or the "
            "relay agent (relay_agent.py) running on a machine inside the target network.",
            variant="body"))
        layout.addWidget(Divider())

        # ── Config row ────────────────────────────────────────────────────
        cfg = QHBoxLayout(); cfg.setSpacing(SPACE_MD)
        self.rb_proxy = QRadioButton("HTTP Proxy")
        self.rb_relay = QRadioButton("Relay Agent")
        _mg = QButtonGroup(self); _mg.addButton(self.rb_proxy); _mg.addButton(self.rb_relay)
        saved_cfg = load_config()
        method = saved_cfg.get("filter_test_method", "relay")
        (self.rb_proxy if method == "proxy" else self.rb_relay).setChecked(True)

        self.addr_in = QLineEdit(saved_cfg.get("filter_test_addr", ""))
        self.addr_in.setPlaceholderText("http://proxy:port  or  http://relay-ip:9224")
        self.token_in = QLineEdit(saved_cfg.get("filter_test_token", ""))
        self.token_in.setPlaceholderText("Token (optional, relay only)")
        self.token_in.setEchoMode(QLineEdit.Password)
        self.token_in.setMaximumWidth(180)

        cfg.addWidget(self.rb_proxy); cfg.addWidget(self.rb_relay)
        cfg.addWidget(self.addr_in, 1)
        cfg.addWidget(self.token_in)
        layout.addLayout(cfg)

        # ── Progress / count ──────────────────────────────────────────────
        self.prog_lbl = QLabel(f"Ready — {len(urls)} URL(s) queued")
        self.prog_lbl.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:{FONT_SIZE_SMALL}px;")
        layout.addWidget(self.prog_lbl)

        # ── Results table ─────────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Result","Site Name","URL","Detail"])
        self.table.setRowCount(len(urls))
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        for col, w in [(0, 80), (1, 180), (2, 340), (3, 200)]:
            self.table.setColumnWidth(col, w)

        # Pre-populate rows with pending state
        for i, (url, site) in enumerate(urls):
            self.table.setItem(i, 0, QTableWidgetItem("—"))
            self.table.setItem(i, 1, QTableWidgetItem(site or "—"))
            self.table.setItem(i, 2, QTableWidgetItem(url))
            self.table.setItem(i, 3, QTableWidgetItem(""))
        layout.addWidget(self.table, 1)

        layout.addWidget(Divider())

        # ── Buttons ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        close_btn   = SecondaryButton("  Close  "); close_btn.clicked.connect(self._on_close)
        export_btn  = GhostButton("  📤  Export Results  "); export_btn.clicked.connect(self._export)
        self.run_btn = PrimaryButton("  ▶  Run Test  "); self.run_btn.clicked.connect(self._run)
        btn_row.addWidget(close_btn); btn_row.addWidget(export_btn)
        btn_row.addStretch(); btn_row.addWidget(self.run_btn)
        layout.addLayout(btn_row)

    def _run(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self.run_btn.setText("  ▶  Run Test  ")
            return

        addr  = self.addr_in.text().strip()
        token = self.token_in.text().strip()
        if not addr:
            show_toast(self, "Enter a proxy address or relay URL", variant="warning"); return

        method = "proxy" if self.rb_proxy.isChecked() else "relay"

        # Ping relay before starting
        if method == "relay":
            import filter_test as ft
            if not ft.ping_relay(addr, token):
                show_toast(self, "Cannot reach relay agent — check address/token", variant="error")
                return

        # Save config
        cfg = load_config()
        cfg["filter_test_method"] = method
        cfg["filter_test_addr"]   = addr
        cfg["filter_test_token"]  = token
        save_config(cfg)

        # Reset table state
        for i in range(self.table.rowCount()):
            self.table.item(i, 0).setText("—")
            self.table.item(i, 0).setForeground(QColor(TEXT_DISABLED))
            self.table.item(i, 3).setText("")
        self._done = 0

        self._method = method
        self._worker = _TestWorker(self._urls, method, addr, token)
        self._worker.row_done.connect(self._on_row)
        self._worker.finished.connect(self._on_done)
        self._worker.start()
        self.run_btn.setText("  ■  Stop  ")

    def _on_row(self, idx: int, url: str, site: str, result: str, detail: str):
        self._done = getattr(self, "_done", 0) + 1
        self.prog_lbl.setText(
            f"Testing… {self._done}/{len(self._urls)}  "
            f"({sum(1 for r in self._get_results() if r=='allowed')} allowed  "
            f"{sum(1 for r in self._get_results() if r=='blocked')} blocked)")
        item_r = self.table.item(idx, 0)
        item_d = self.table.item(idx, 3)
        if item_r:
            item_r.setText(result.upper())
            item_r.setForeground(QColor(_RESULT_COLORS.get(result, TEXT_PRIMARY)))
        if item_d:
            item_d.setText(detail)

    def _get_results(self) -> list:
        return [self.table.item(i, 0).text().lower()
                for i in range(self.table.rowCount())
                if self.table.item(i, 0)]

    def _on_done(self):
        results = self._get_results()
        allowed = results.count("allowed")
        blocked = results.count("blocked")
        dead    = results.count("dead")
        errors  = len(results) - allowed - blocked - dead - results.count("cancelled")
        self.prog_lbl.setText(
            f"Complete — {allowed} allowed  |  {blocked} blocked  |  "
            f"{dead} dead  |  {errors} errors")
        self.run_btn.setText("  ▶  Run Test  ")
        # Persist results so they appear in reports
        try:
            import time as _time
            session_id = str(int(_time.time()))
            method = getattr(self, "_method", "relay")
            rows = []
            for i in range(self.table.rowCount()):
                res    = (self.table.item(i, 0) or QTableWidgetItem("")).text().lower()
                site   = (self.table.item(i, 1) or QTableWidgetItem("")).text()
                url    = (self.table.item(i, 2) or QTableWidgetItem("")).text()
                detail = (self.table.item(i, 3) or QTableWidgetItem("")).text()
                if url and url != "—" and res not in ("—", ""):
                    rows.append((url, site, res, detail))
            if rows:
                database.save_filter_results(session_id, rows, method)
        except Exception:
            pass
        mw = self.parent().window() if self.parent() else None
        if mw and hasattr(mw, "tray"):
            mw.tray.showMessage("FilterGuardian — Filter Test Done",
                f"{blocked} URLs blocked, {allowed} allowed through the filter.",
                QSystemTrayIcon.Information, 6000)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Results", "filter_test_results.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            import csv
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Result", "Site Name", "URL", "Detail"])
                for i in range(self.table.rowCount()):
                    w.writerow([
                        (self.table.item(i, c) or QTableWidgetItem("")).text()
                        for c in range(4)])
            show_toast(self, f"Exported {self.table.rowCount()} rows", variant="success")
        except Exception as e:
            show_toast(self, f"Export failed: {e}", variant="error")

    def _on_close(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait()
        self.reject()

    def closeEvent(self, event):
        self._on_close(); event.accept()


# ══════════════════════════════════════════════════════════════════════════════
#  REPORT DIALOG
# ══════════════════════════════════════════════════════════════════════════════

class ReportDialog(QDialog):
    """Choose and generate Executive or Network Filter reports."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Reports")
        self.setMinimumWidth(520)

        L = QVBoxLayout(self)
        L.setContentsMargins(SPACE_XL, SPACE_XL, SPACE_XL, SPACE_XL)
        L.setSpacing(SPACE_MD)

        L.addWidget(Label("Generate Reports", variant="heading"))
        L.addWidget(Label(
            "Choose a report type. Reports open in your browser and can be saved "
            "to PDF using Print → Save as PDF.",
            variant="body"))
        L.addWidget(Divider())

        t = theme._t()
        card_style = (f"QFrame {{ background:{t['bg_card']}; border:1px solid {t['border']};"
                      f" border-radius:8px; padding:16px; }}")

        # ── Executive Report card ─────────────────────────────────────────
        exec_card = QFrame(); exec_card.setStyleSheet(card_style)
        ec_L = QVBoxLayout(exec_card); ec_L.setSpacing(SPACE_SM)
        ec_title = QLabel("📊  Executive Report")
        ec_title.setStyleSheet(f"font-size:15px;font-weight:700;color:{t['text_primary']}")
        ec_desc  = QLabel(
            "High-level summary for the Executive Director of Technology. Includes key "
            "metrics, filter test bypass count, proxy technology breakdown, hosting "
            "platform analysis, 30-day timeline, and recommendations.")
        ec_desc.setWordWrap(True)
        ec_desc.setStyleSheet(f"font-size:13px;color:{t['text_secondary']}")
        ec_btn   = PrimaryButton("  Generate Executive Report  ")
        ec_btn.clicked.connect(self._gen_executive)
        ec_L.addWidget(ec_title); ec_L.addWidget(ec_desc); ec_L.addWidget(ec_btn)
        L.addWidget(exec_card)

        # ── Network Filter card ────────────────────────────────────────────
        ck_card = QFrame(); ck_card.setStyleSheet(card_style)
        ck_L = QVBoxLayout(ck_card); ck_L.setSpacing(SPACE_SM)
        ck_title = QLabel("🔒  Network Filter Submission Report")
        ck_title.setStyleSheet(f"font-size:15px;font-weight:700;color:{t['text_primary']}")
        ck_desc  = QLabel(
            "Technical report for Network Filter support. Lists confirmed bypass domains, "
            "proxy framework signatures, filter test results, and a CSV export of all "
            "bypass URLs for direct import into Network Filter.")
        ck_desc.setWordWrap(True)
        ck_desc.setStyleSheet(f"font-size:13px;color:{t['text_secondary']}")
        ck_btn   = PrimaryButton("  Generate Network Filter Report  ")
        ck_btn.clicked.connect(self._gen_filter_report)
        ck_L.addWidget(ck_title); ck_L.addWidget(ck_desc); ck_L.addWidget(ck_btn)
        L.addWidget(ck_card)

        L.addWidget(Divider())
        close_btn = SecondaryButton("  Close  ")
        close_btn.clicked.connect(self.accept)
        close_row = QHBoxLayout(); close_row.addStretch(); close_row.addWidget(close_btn)
        L.addLayout(close_row)

    def _gen_executive(self):
        import report_gen, webbrowser as _wb
        from datetime import datetime as _dt
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Executive Report",
            f"FilterGuardian_Executive_{_dt.now().strftime('%Y%m%d')}.html",
            "HTML Report (*.html)")
        if not path:
            return
        try:
            html = report_gen.generate_executive_report()
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            show_toast(self.window(), "Executive report saved — opening in browser", variant="success")
            _wb.open("file:///" + path.replace("\\", "/"))
        except Exception as e:
            show_toast(self.window(), f"Report error: {e}", variant="error")

    def _gen_filter_report(self):
        import report_gen, webbrowser as _wb, os as _os
        from datetime import datetime as _dt
        folder = QFileDialog.getExistingDirectory(self, "Save Network Filter Report To")
        if not folder:
            return
        try:
            html, csv_str = report_gen.generate_filter_report()
            date_str  = _dt.now().strftime("%Y%m%d")
            html_path = _os.path.join(folder, f"FilterGuardian_Filter_{date_str}.html")
            csv_path  = _os.path.join(folder, f"FilterGuardian_Filter_{date_str}.csv")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                f.write(csv_str)
            show_toast(self.window(),
                       f"Network Filter report saved (HTML + CSV) — opening in browser",
                       variant="success")
            _wb.open("file:///" + html_path.replace("\\", "/"))
        except Exception as e:
            show_toast(self.window(), f"Report error: {e}", variant="error")


# ══════════════════════════════════════════════════════════════════════════════
#  CONSOLIDATE DIALOG
# ══════════════════════════════════════════════════════════════════════════════

class ConsolidateDialog(QDialog):
    """
    Shows domains with conflicting or missing site names.
    Lets the operator pick one canonical name per domain and applies it
    to all same-domain records.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Consolidate Site Names")
        self.setMinimumWidth(720)
        self.setMinimumHeight(540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_XL, SPACE_XL, SPACE_XL, SPACE_XL)
        layout.setSpacing(SPACE_MD)

        layout.addWidget(Label("Consolidate Site Names", variant="heading"))
        layout.addWidget(Label(
            "Domains that have conflicting or missing site names. "
            "Pick a canonical name per domain to unify all records.",
            variant="body"))
        layout.addWidget(Divider())

        self._groups = database.get_domain_groups()
        self._widgets: list[tuple[str, QComboBox, QLineEdit]] = []

        if not self._groups:
            layout.addWidget(Label("No conflicts found — all domains are consistently named.", variant="body"))
            layout.addStretch()
            close = PrimaryButton("Close")
            close.clicked.connect(self.accept)
            layout.addWidget(close)
            return

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        grid = QVBoxLayout(inner)
        grid.setSpacing(SPACE_MD)

        for domain, records in self._groups[:50]:   # cap at 50 to keep UI snappy
            distinct_names = sorted({r[2] for r in records if r[2]})
            unnamed_count  = sum(1 for r in records if not r[2])

            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background: transparent; border: 1px solid {theme._t()['border']};"
                f" border-radius: 6px; padding: 8px; }}")
            cl = QVBoxLayout(card)
            cl.setSpacing(SPACE_SM)

            title_lbl = QLabel(f"<b>{domain}</b>  "
                               f"<span style='color:{TEXT_SECONDARY}'>({len(records)} records"
                               + (f", {unnamed_count} unnamed" if unnamed_count else "")
                               + ")</span>")
            title_lbl.setTextFormat(Qt.RichText)
            cl.addWidget(title_lbl)

            row = QHBoxLayout()
            combo = QComboBox()
            combo.setEditable(False)
            combo.addItems(distinct_names)
            combo.setMinimumWidth(220)
            row.addWidget(QLabel("Known names:"))
            row.addWidget(combo, 1)

            custom = QLineEdit()
            custom.setPlaceholderText("…or type a new name")
            custom.setMinimumWidth(180)
            row.addWidget(custom, 1)

            cl.addLayout(row)
            grid.addWidget(card)
            self._widgets.append((domain, combo, custom))

        grid.addStretch()
        layout.addWidget(scroll, 1)
        layout.addWidget(Divider())

        btns = QHBoxLayout()
        apply_btn = PrimaryButton("Apply All")
        apply_btn.clicked.connect(self._apply)
        cancel_btn = SecondaryButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(apply_btn)
        layout.addLayout(btns)

    def _apply(self):
        import json as _json
        from pathlib import Path as _Path
        from analyzer import save_known_site

        updated_total = 0
        for domain, combo, custom in self._widgets:
            name = custom.text().strip() or combo.currentText().strip()
            if not name:
                continue
            updated_total += database.update_site_name_by_domain(domain, name)

        if updated_total:
            show_toast(self.window(), f"Updated {updated_total} record(s)", variant="success")
        else:
            show_toast(self.window(), "No records updated", variant="info")
        self.accept()


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE 4 — DATABASE
# ══════════════════════════════════════════════════════════════════════════════

COLS = ["ID","Status","Site Name","Category","Platform","Proxy Tech","URL","Source","Timestamp"]
STATUS_CLR = {
    "analyzed": ACCENT_GREEN,
    "pending":  ACCENT_YELLOW,
    "failed":   ACCENT_RED,
    "reviewed": ACCENT_BLUE,
    "filtered": "#f97316",   # orange — Network Filter blocked it
}

class DatabasePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        L = QVBoxLayout(self)
        L.setContentsMargins(SPACE_2XL, SPACE_2XL, SPACE_2XL, SPACE_2XL)
        L.setSpacing(SPACE_LG)

        # ── Header ────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.addWidget(Label("URL Database", variant="display"))
        hdr.addStretch()
        self.review_btn = GhostButton("  🔍  Review Queue  ")
        self.review_btn.clicked.connect(self._open_review_queue)
        self.review_btn.setVisible(False)
        hdr.addWidget(self.review_btn)
        propagate_btn = GhostButton("  🔗  Propagate Names  ")
        propagate_btn.clicked.connect(self._propagate)
        hdr.addWidget(propagate_btn)
        consolidate_btn = GhostButton("  🔀  Consolidate  ")
        consolidate_btn.clicked.connect(self._consolidate)
        hdr.addWidget(consolidate_btn)
        test_btn = GhostButton("  🌐  Filter Test  ")
        test_btn.clicked.connect(self._open_filter_test)
        hdr.addWidget(test_btn)
        for label, fn in [("  📤  Export  ", self._export), ("  🔄  Refresh  ", self.refresh)]:
            b = SecondaryButton(label); b.clicked.connect(fn); hdr.addWidget(b)
        L.addLayout(hdr)

        # Timer to update the review queue badge
        self._review_timer = QTimer(self)
        self._review_timer.timeout.connect(self._update_review_badge)
        self._review_timer.start(5000)

        # ── Manual URL entry ──────────────────────────────────────────────────
        mu = QHBoxLayout(); mu.setSpacing(SPACE_SM)
        self.manual_url_in = QLineEdit()
        self.manual_url_in.setPlaceholderText("➕  Paste a URL to submit for analysis…")
        self.manual_url_in.returnPressed.connect(self._submit_manual_url)
        manual_submit_btn = SecondaryButton("  Submit URL  ")
        manual_submit_btn.clicked.connect(self._submit_manual_url)
        mu.addWidget(self.manual_url_in, 1); mu.addWidget(manual_submit_btn)
        L.addLayout(mu)

        # ── Filter bar ────────────────────────────────────────────────────
        sr = QHBoxLayout(); sr.setSpacing(SPACE_SM)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Search URL, site, category, platform…")
        self.search.textChanged.connect(self._search)

        self.filt_status = QComboBox()
        self.filt_status.addItems(["All Statuses", "analyzed", "pending", "failed", "reviewed", "filtered"])
        self.filt_status.currentTextChanged.connect(self._search)

        self.filt_cat = QComboBox()
        self.filt_cat.setMinimumWidth(150)
        self.filt_cat.currentTextChanged.connect(self._search)

        self.filt_plat = QComboBox()
        self.filt_plat.setMinimumWidth(160)
        self.filt_plat.currentTextChanged.connect(self._search)

        sr.addWidget(self.search, 1)
        sr.addWidget(self.filt_status)
        sr.addWidget(self.filt_cat)
        sr.addWidget(self.filt_plat)
        L.addLayout(sr)

        self.count_lbl = QLabel("0 results")
        self.count_lbl.setStyleSheet(
            f"color:{TEXT_SECONDARY}; font-size:{FONT_SIZE_SMALL}px;")
        L.addWidget(self.count_lbl)

        # ── Table ─────────────────────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)   # all columns user-resizable
        hh.setMinimumSectionSize(55)
        hh.setStretchLastSection(False)
        hh.setSortIndicatorShown(True)
        # Default column widths (all interactive — drag to resize freely)
        for col, w in [(1,80),(2,160),(3,145),(4,145),(5,120),(6,320),(7,185),(8,145)]:
            self.table.setColumnWidth(col, w)
        self.table.setColumnHidden(0, True)                # ID hidden
        self.table.doubleClicked.connect(self._open_edit)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._ctx)
        L.addWidget(self.table)

        self._rows = []
        self.refresh()

    # ── Data helpers ──────────────────────────────────────────────────────

    def _current_uid(self, row: int) -> int:
        return int(self.table.item(row, 0).text())

    def _open_edit(self, idx=None, uid: int = None):
        if uid is None:
            uid = self._current_uid(idx.row() if idx else self.table.currentRow())
        dlg = URLEditDialog(uid, self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()

    # ── Refresh / filter ──────────────────────────────────────────────────

    def refresh(self):
        self._rows = database.get_all_urls()
        self._refresh_filter_dropdowns()
        self._populate(self._filter(self._rows))

    def _refresh_filter_dropdowns(self):
        # Preserve current selections before repopulating
        cur_cat  = self.filt_cat.currentText()
        cur_plat = self.filt_plat.currentText()

        self.filt_cat.blockSignals(True)
        self.filt_cat.clear()
        self.filt_cat.addItem("All Categories")
        for c in database.get_distinct_categories():
            self.filt_cat.addItem(c)
        idx = self.filt_cat.findText(cur_cat)
        self.filt_cat.setCurrentIndex(max(0, idx))
        self.filt_cat.blockSignals(False)

        self.filt_plat.blockSignals(True)
        self.filt_plat.clear()
        self.filt_plat.addItem("All Platforms")
        for p in database.get_distinct_platforms():
            self.filt_plat.addItem(p)
        idx = self.filt_plat.findText(cur_plat)
        self.filt_plat.setCurrentIndex(max(0, idx))
        self.filt_plat.blockSignals(False)

    def _filter(self, rows):
        q      = self.search.text().strip()
        status = self.filt_status.currentText()
        cat    = self.filt_cat.currentText()
        plat   = self.filt_plat.currentText()

        if q:
            rows = database.search_urls(q)
        if status != "All Statuses":
            rows = [r for r in rows if r[1] == status]
        if cat != "All Categories":
            rows = [r for r in rows if (r[3] or "") == cat]
        if plat != "All Platforms":
            rows = [r for r in rows if (r[4] or "") == plat]
        return rows

    def _search(self):
        self._populate(self._filter(self._rows))

    def _populate(self, rows):
        self.table.setSortingEnabled(False)
        self.table.clearContents()          # fully clear before repopulating
        self.table.setRowCount(len(rows))
        self.count_lbl.setText(
            f"{len(rows):,} result{'s' if len(rows) != 1 else ''}")
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                item = QTableWidgetItem(str(val) if val else "—")
                item.setToolTip(str(val) if val else "")
                if j == 1:
                    item.setForeground(
                        QColor(STATUS_CLR.get(str(val), TEXT_DISABLED)))
                self.table.setItem(i, j, item)
        self.table.setSortingEnabled(True)

    # ── Context menu ──────────────────────────────────────────────────────

    def _ctx(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        uid     = self._current_uid(row)
        url_val = (self.table.item(row, 6) or QTableWidgetItem("")).text()
        t = theme._t()
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background:{t['bg_card']}; border:1px solid {t['border']};
                     border-radius:8px; padding:4px; }}
            QMenu::item {{ padding:6px 16px; border-radius:4px;
                           color:{t['text_primary']}; font-size:13px; }}
            QMenu::item:selected {{ background:{t['accent_dim']}; color:{t['accent']}; }}
            QMenu::separator {{ height:1px; background:{t['border']}; margin:4px 0; }}
        """)
        a_edit      = QAction("✏️  Edit Record",            self)
        a_reanalyze = QAction("🔄  Re-analyze",              self)
        a_copy      = QAction("📋  Copy URL",                self)
        a_reviewed  = QAction("✅  Mark as Reviewed",        self)
        a_wl_domain = QAction("🔒  Whitelist Domain",        self)
        a_wl_site   = QAction("🔒  Whitelist Site Name",     self)
        a_delete    = QAction("🗑️  Delete",                   self)

        a_edit.triggered.connect(lambda: self._open_edit(uid=uid))
        a_reanalyze.triggered.connect(lambda: self._reanalyze(uid))
        a_copy.triggered.connect(lambda: QApplication.clipboard().setText(url_val))
        a_reviewed.triggered.connect(lambda: self._mark_reviewed(uid))
        a_wl_domain.triggered.connect(lambda: self._whitelist_domain(uid))
        a_wl_site.triggered.connect(lambda: self._whitelist_site(uid))
        a_delete.triggered.connect(lambda: self._delete(uid))

        menu.addAction(a_edit)
        menu.addAction(a_reanalyze)
        menu.addAction(a_copy)
        menu.addAction(a_reviewed)
        menu.addSeparator()
        menu.addAction(a_wl_domain)
        menu.addAction(a_wl_site)
        menu.addSeparator()
        menu.addAction(a_delete)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ── Actions ───────────────────────────────────────────────────────────

    def _open_filter_test(self):
        # Build URL list from current visible rows
        urls = []
        for i in range(self.table.rowCount()):
            url_item  = self.table.item(i, 6)
            site_item = self.table.item(i, 2)
            if url_item:
                urls.append((url_item.text(), site_item.text() if site_item else ""))
        if not urls:
            show_toast(self.window(), "No URLs visible to test", variant="warning")
            return
        dlg = FilterTestDialog(urls, self)
        dlg.exec()

    def _whitelist_domain(self, uid: int):
        import urllib.parse
        row = database.get_url_detail(uid)
        if not row:
            return
        url    = row.get("url", "")
        domain = urllib.parse.urlparse(url).netloc or url
        if not domain:
            show_toast(self.window(), "Could not extract domain", variant="warning")
            return
        try:
            wl_path = Path("whitelist.json")
            data = json.loads(wl_path.read_text(encoding="utf-8")) if wl_path.exists() else {}
            domains = data.setdefault("whitelisted_domains", [])
            if domain not in domains:
                domains.append(domain)
                wl_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
                show_toast(self.window(), f"Whitelisted domain: {domain}", variant="success")
            else:
                show_toast(self.window(), f"Already whitelisted: {domain}", variant="info")
        except Exception as e:
            show_toast(self.window(), f"Whitelist error: {e}", variant="error")

    def _whitelist_site(self, uid: int):
        row = database.get_url_detail(uid)
        if not row:
            return
        site = row.get("site_name", "")
        if not site:
            show_toast(self.window(), "No site name on this record", variant="warning")
            return
        try:
            wl_path = Path("whitelist.json")
            data = json.loads(wl_path.read_text(encoding="utf-8")) if wl_path.exists() else {}
            sites = data.setdefault("whitelisted_sites", [])
            if site not in sites:
                sites.append(site)
                wl_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
                show_toast(self.window(), f"Whitelisted site: {site}", variant="success")
            else:
                show_toast(self.window(), f"Already whitelisted: {site}", variant="info")
        except Exception as e:
            show_toast(self.window(), f"Whitelist error: {e}", variant="error")

    def _submit_manual_url(self):
        url = self.manual_url_in.text().strip()
        if not url:
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        if database.add_url(url, "Manual", "Manual Entry"):
            show_toast(self.window(), f"Queued for analysis: {url[:60]}", variant="success")
            self.manual_url_in.clear()
            self.refresh()
        else:
            show_toast(self.window(), "URL already exists in database", variant="warning")

    def _reanalyze(self, uid: int):
        database.requeue_url(uid)
        self.refresh()
        show_toast(self.window(), "URL queued for re-analysis", variant="info")

    def _delete(self, uid: int):
        if QMessageBox.question(
                self, "Delete", "Remove this URL from the database?",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            database.delete_url(uid)
            self.refresh()
            show_toast(self.window(), "URL deleted", variant="success")

    def _mark_reviewed(self, uid: int):
        database.mark_reviewed(uid)
        self.refresh()
        show_toast(self.window(), "Marked as reviewed", variant="info")

    def _propagate(self):
        count = database.propagate_names_by_domain()
        self.refresh()
        if count:
            show_toast(self.window(), f"Propagated names to {count} record(s)", variant="success")
        else:
            show_toast(self.window(), "No unnamed records to update", variant="info")

    def _consolidate(self):
        dlg = ConsolidateDialog(self)
        dlg.exec()
        self.refresh()

    def _update_review_badge(self):
        try:
            fp_file = Path("pending_fingerprints.json")
            if not fp_file.exists():
                self._fp_prev_count = 0
                self.review_btn.setVisible(False); return
            with open(fp_file, encoding="utf-8") as f:
                data = json.load(f)
            count = len(data)
            if count > 0:
                self.review_btn.setText(f"  🔍  Review Queue ({count})  ")
                self.review_btn.setVisible(True)
                prev = getattr(self, "_fp_prev_count", 0)
                if count > prev:
                    mw = self.window()
                    if hasattr(mw, "tray"):
                        mw.tray.showMessage(
                            "FilterGuardian",
                            f"{count} site(s) queued for fingerprint review — open the Database page to name them.",
                            QSystemTrayIcon.Information, 7000)
                self._fp_prev_count = count
            else:
                self._fp_prev_count = 0
                self.review_btn.setVisible(False)
        except Exception:
            self.review_btn.setVisible(False)

    def _open_review_queue(self):
        dlg = FingerprintReviewDialog(self)
        dlg.exec()
        self._update_review_badge()
        self.refresh()

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", "export.txt", "Text (*.txt)")
        if path:
            cnt = database.export_blacklist(export_file=path)
            show_toast(self.window(), f"Exported {cnt} URLs", variant="success")


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE 5 — TARGETS
# ══════════════════════════════════════════════════════════════════════════════

class TargetsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        outer = QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.addWidget(scroll)
        self._inner = QWidget(); scroll.setWidget(self._inner)
        L = QVBoxLayout(self._inner)
        L.setContentsMargins(SPACE_2XL, SPACE_2XL, SPACE_2XL, SPACE_2XL); L.setSpacing(SPACE_LG)

        L.addWidget(Label("Target Servers & Channels", variant="display"))
        L.addWidget(Label("Configure which Discord servers and channels to monitor.", variant="subtitle"))
        L.addWidget(Divider())

        # Add server card
        add_card = Card(); add_card.add_title("Add Server Target", "Register a server by display name")
        r1 = QHBoxLayout(); r1.addWidget(QLabel("Server Name:"))
        self.srv_in = QLineEdit(); self.srv_in.setPlaceholderText("e.g. Selenite"); r1.addWidget(self.srv_in, 1)
        r2 = QHBoxLayout(); r2.addWidget(QLabel("Keywords:"))
        self.key_in = QLineEdit(); self.key_in.setPlaceholderText("Comma-separated keywords (optional)"); r2.addWidget(self.key_in, 1)
        add_btn = PrimaryButton("  +  Add Server  "); add_btn.clicked.connect(self._add)
        add_card.layout.addLayout(r1); add_card.layout.addLayout(r2); add_card.layout.addWidget(add_btn)
        L.addWidget(add_card)

        # ── Auto-Join card ────────────────────────────────────────────────
        join_card = Card()
        join_card.add_title("Auto-Join Server", "Join a server via invite link using the linked browser")
        r_inv = QHBoxLayout(); r_inv.addWidget(QLabel("Invite URL:"))
        self.invite_in = QLineEdit()
        self.invite_in.setPlaceholderText("https://discord.gg/…")
        r_inv.addWidget(self.invite_in, 1)
        join_btn = SecondaryButton("  🔗  Join Server  ")
        join_btn.clicked.connect(self._auto_join)
        self.invite_in.returnPressed.connect(self._auto_join)
        join_card.layout.addLayout(r_inv)
        join_card.layout.addWidget(join_btn)
        join_card.layout.addWidget(Label(
            "Handles member-screening flows automatically. CAPTCHAs and phone/age "
            "verification will trigger a notification so you can intervene in the browser.",
            variant="body"))
        L.addWidget(join_card)

        L.addWidget(Label("Configured Servers", variant="heading"))
        self.list_L = QVBoxLayout(); self.list_L.setSpacing(SPACE_SM); L.addLayout(self.list_L)
        L.addStretch(); self.refresh()

    def _add(self):
        s = self.srv_in.text().strip(); k = self.key_in.text().strip()
        if not s: return
        targets = load_targets(); found = False
        for t in targets:
            if t["name"].lower() == s.lower(): t["keywords"] = k; found = True; break
        if not found: targets.append({"name": s, "keywords": k, "explicit_channels": []})
        save_targets(targets); self.srv_in.clear(); self.key_in.clear(); self.refresh()
        mw = self.window()
        if hasattr(mw,"live_page"): mw.live_page.refresh_toolbox()
        show_toast(self.window(), f"Added: {s}", variant="success")

    def refresh(self):
        while self.list_L.count():
            item = self.list_L.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for t in load_targets(): self.list_L.addWidget(self._srv_card(t))

    def _srv_card(self, t: dict):
        card = Card()
        hdr = QHBoxLayout()
        nl = QLabel(f"🖥  {t['name']}")
        nl.setStyleSheet(f"color:{TEXT_PRIMARY}; font-size:{FONT_SIZE_HEADING}px; font-weight:600;")
        hdr.addWidget(nl, 1)
        sw = GhostButton("  ▶  Switch  "); sw.clicked.connect(lambda _,n=t["name"]: self._switch(n))
        dl = GhostButton("  🗑️  "); dl.setStyleSheet(f"color:{ACCENT_RED};"); dl.clicked.connect(lambda _,n=t["name"]: self._delete(n))
        hdr.addWidget(sw); hdr.addWidget(dl); card.layout.addLayout(hdr)
        if t.get("keywords"):
            kl = QLabel(f"Keywords: {t['keywords']}"); kl.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:{FONT_SIZE_SMALL}px;")
            card.layout.addWidget(kl)
        chans = t.get("explicit_channels",[])
        if chans:
            card.layout.addWidget(Divider())
            card.layout.addWidget(Label("Explicit Channels", variant="caption"))
            cg = QHBoxLayout(); cg.setSpacing(4); cg.setContentsMargins(0,0,0,0)
            for c in chans:
                ch_wrap = QFrame()
                cw_L = QHBoxLayout(ch_wrap); cw_L.setContentsMargins(0,0,0,0); cw_L.setSpacing(0)
                pill = QLabel(f"  #{c}  "); pill.setObjectName("badge_info")
                rm = QPushButton("×"); rm.setFixedSize(16, 16); rm.setCursor(Qt.PointingHandCursor)
                rm.setStyleSheet(f"color:{ACCENT_RED}; background:transparent; border:none; font-size:11px; font-weight:bold; padding:0;")
                rm.clicked.connect(lambda _, s=t["name"], ch=c: self._remove_ch(s, ch))
                cw_L.addWidget(pill); cw_L.addWidget(rm)
                cg.addWidget(ch_wrap)
            cg.addStretch(); card.layout.addLayout(cg)
        card.layout.addWidget(Divider())
        ar = QHBoxLayout()
        ci = QLineEdit(); ci.setPlaceholderText("Add channel name…"); ci.setMaximumHeight(32)
        ab = GhostButton("+ Add"); ab.clicked.connect(lambda _,n=t["name"],i=ci: self._add_ch(n,i))
        ar.addWidget(ci,1); ar.addWidget(ab); card.layout.addLayout(ar)
        return card

    def _auto_join(self):
        invite = self.invite_in.text().strip()
        if not invite:
            show_toast(self.window(), "Enter an invite URL first", variant="warning"); return
        if not is_live():
            show_toast(self.window(), "Link a browser first!", variant="warning"); return
        send_cmd("JOIN", invite)
        show_toast(self.window(), "Join request sent — watch the Live Monitor for status.", variant="info")
        self.invite_in.clear()

    def _switch(self, name):
        if send_cmd("SWITCH", name): show_toast(self.window(), f"Switching to: {name}")
        else: show_toast(self.window(), "Link a browser first!", variant="warning")

    def _delete(self, name):
        targets = [t for t in load_targets() if t["name"] != name]; save_targets(targets); self.refresh()
        mw = self.window()
        if hasattr(mw,"live_page"): mw.live_page.refresh_toolbox()

    def _add_ch(self, server, inp):
        ch = inp.text().strip().lstrip("#")
        if not ch: return
        targets = load_targets()
        for t in targets:
            if t["name"] == server:
                ec = t.setdefault("explicit_channels",[])
                if ch not in ec: ec.append(ch)
        save_targets(targets); inp.clear(); self.refresh()
        mw = self.window()
        if hasattr(mw,"live_page"): mw.live_page.refresh_toolbox()
        show_toast(self.window(), f"Channel #{ch} added", variant="success")

    def _remove_ch(self, server: str, channel: str):
        targets = load_targets()
        for t in targets:
            if t["name"] == server:
                ec = t.get("explicit_channels", [])
                if channel in ec: ec.remove(channel)
                break
        save_targets(targets)
        self.refresh()
        mw = self.window()
        if hasattr(mw, "live_page"): mw.live_page.refresh_toolbox()
        show_toast(self.window(), f"Removed #{channel}", variant="success")


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE 6 — SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        outer = QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.addWidget(scroll)
        inner = QWidget(); scroll.setWidget(inner)
        L = QVBoxLayout(inner)
        L.setContentsMargins(SPACE_2XL, SPACE_2XL, SPACE_2XL, SPACE_2XL); L.setSpacing(SPACE_2XL)

        L.addWidget(Label("Settings", variant="display"))
        L.addWidget(Divider())
        setup_btn = SecondaryButton("Open setup menu")
        setup_btn.clicked.connect(lambda: self.window().open_setup())
        L.addWidget(setup_btn)

        # User profile
        pc = Card(); pc.add_title("User Profile", "Personalise your experience")
        pr = QHBoxLayout(); pr.addWidget(QLabel("Your Name:"))
        self.name_in = QLineEdit(load_config().get("user_name", "Guardian"))
        self.name_in.setPlaceholderText("Enter your name…"); pr.addWidget(self.name_in, 1)
        save_profile_btn = PrimaryButton("  💾  Save Profile  ")
        save_profile_btn.clicked.connect(self._save_profile)
        pc.layout.addLayout(pr); pc.layout.addWidget(save_profile_btn)
        L.addWidget(pc)

        # Theme picker
        tc = Card(); tc.add_title("Appearance", "Choose your color theme")
        tg = QHBoxLayout(); tg.setSpacing(SPACE_MD)
        self._t_btns = {}; bg = QButtonGroup(self); bg.setExclusive(True)
        for key, meta in THEMES.items():
            btn = QPushButton(f"{meta['emoji']}\n{meta['name']}")
            btn.setObjectName("theme_btn"); btn.setCheckable(True)
            btn.setChecked(key == theme.CURRENT_THEME)
            btn.setCursor(Qt.PointingHandCursor); btn.setFixedWidth(100)
            btn.clicked.connect(lambda _, k=key: self._set_theme(k))
            bg.addButton(btn); self._t_btns[key] = btn; tg.addWidget(btn)
        tg.addStretch(); tc.layout.addLayout(tg); L.addWidget(tc)

        # Brain config
        bc = Card(); bc.add_title("Autonomous Brain", "Site analysis engine")
        bc.layout.addWidget(Label(
            "The Brain visits each discovered URL in a locked-down sandboxed browser — no images, "
            "no media, no downloads, isolated context per URL. It detects the hosting platform "
            "(GitHub Pages, Cloudflare, Vercel…), proxy framework (Ultraviolet, Rammerhead…), "
            "classifies the site by category, and stores a structural DOM fingerprint for "
            "duplicate detection. Runs as a separate process so the UI stays responsive.",
            variant="body"))
        L.addWidget(bc)

        # Whitelist
        wc = Card(); wc.add_title("Domain Whitelist", "Ignore URLs containing these domains")
        self.wl = QTextEdit(); self.wl.setPlaceholderText("One domain per line…"); self.wl.setMaximumHeight(180)
        self._load_wl()
        save_wl = PrimaryButton("  💾  Save Whitelist  "); save_wl.clicked.connect(self._save_wl)
        wc.layout.addWidget(self.wl); wc.layout.addWidget(save_wl); L.addWidget(wc)

        # Network filter test config
        ftc = Card(); ftc.add_title("Network Filter Test", "Test URLs through configured filter")
        ftc.layout.addWidget(Label(
            "Option A — HTTP Proxy: enter your network's web proxy address (if known).\n"
            "Option B — Relay Agent: run relay_agent.py on any machine inside the filtered "
            "network; enter its IP:port here. You stay on your own connection.",
            variant="body"))
        ft_cfg = load_config()
        ft_r = QHBoxLayout()
        self.ft_method = QComboBox()
        self.ft_method.addItems(["Relay Agent", "HTTP Proxy"])
        self.ft_method.setCurrentText(
            "HTTP Proxy" if ft_cfg.get("filter_test_method","relay") == "proxy" else "Relay Agent")
        self.ft_addr = QLineEdit(ft_cfg.get("filter_test_addr", ""))
        self.ft_addr.setPlaceholderText("http://ip:port")
        self.ft_token = QLineEdit(ft_cfg.get("filter_test_token", ""))
        self.ft_token.setPlaceholderText("Token (relay only, optional)")
        self.ft_token.setEchoMode(QLineEdit.Password)
        self.ft_token.setMaximumWidth(200)
        ft_r.addWidget(QLabel("Method:")); ft_r.addWidget(self.ft_method)
        ft_r.addWidget(QLabel("Address:")); ft_r.addWidget(self.ft_addr, 1)
        ft_r.addWidget(self.ft_token)
        save_ft = PrimaryButton("  💾  Save  "); save_ft.clicked.connect(self._save_filter_test)
        relay_btn = GhostButton("  📦  Generate Relay Package  ")
        relay_btn.clicked.connect(self._gen_relay_package)
        ft_btns = QHBoxLayout()
        ft_btns.addWidget(save_ft); ft_btns.addWidget(relay_btn); ft_btns.addStretch()
        ftc.layout.addLayout(ft_r); ftc.layout.addLayout(ft_btns)
        L.addWidget(ftc)

        # Network location toggle
        loc_c = Card(); loc_c.add_title("Network Location",
            "Tell the Brain where you are running FilterGuardian from")
        loc_c.layout.addWidget(Label(
            "When On Filtered Network: if the Brain visits a URL and gets a Network Filter "
            "block page, it records the site as 'filtered' (orange) — not failed. "
            "A hard connection refusal is also tagged as a network block, not a dead site.\n\n"
            "When Remote / Home: unreachable sites are simply marked failed — the filter "
            "isn't in the path, so unreachable means the site is likely down.",
            variant="body"))
        _loc_cfg = load_config()
        self.rb_onsite  = QRadioButton("On Filtered Network  (Network Filter in path)")
        self.rb_remote  = QRadioButton("Remote / Home  (no network filter in path)")
        _lg = QButtonGroup(self); _lg.addButton(self.rb_onsite); _lg.addButton(self.rb_remote)
        if _loc_cfg.get("on_premises", False):
            self.rb_onsite.setChecked(True)
        else:
            self.rb_remote.setChecked(True)
        self.rb_onsite.toggled.connect(self._save_location)
        self.rb_remote.toggled.connect(self._save_location)
        loc_c.layout.addWidget(self.rb_onsite)
        loc_c.layout.addWidget(self.rb_remote)
        L.addWidget(loc_c)

        # Data & Backup
        bk = Card(); bk.add_title("Data & Backup",
            "Export, import, and back up all FilterGuardian data")
        bk.layout.addWidget(Label(
            "A backup captures everything: the URL database, known site names, "
            "target servers, whitelist, filter test results, and settings. "
            "Use it to move FilterGuardian to a new machine or restore after a problem.",
            variant="body"))
        _bk_cfg = load_config()
        self.backup_lbl = QLabel()
        self.backup_lbl.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:{FONT_SIZE_SMALL}px;")
        self._update_backup_label()
        bk_btns = QHBoxLayout()
        bk_create = PrimaryButton("  💾  Create Backup  ")
        bk_create.clicked.connect(self._create_backup)
        bk_restore = SecondaryButton("  📂  Restore from Backup  ")
        bk_restore.clicked.connect(self._restore_backup)
        bk_btns.addWidget(bk_create); bk_btns.addWidget(bk_restore); bk_btns.addStretch()
        bk.layout.addWidget(self.backup_lbl)
        bk.layout.addLayout(bk_btns)
        L.addWidget(bk)

        # Storage & Cache
        stc = Card(); stc.add_title("Storage & Cache",
            "Free up disk space used by browser cache and temporary files")
        self.cache_lbl = QLabel()
        self.cache_lbl.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:{FONT_SIZE_SMALL}px;")
        self._refresh_cache_label()
        clear_cache_btn = SecondaryButton("  🗑  Clear Cache  ")
        clear_cache_btn.clicked.connect(self._clear_cache)
        st_row = QHBoxLayout()
        st_row.addWidget(clear_cache_btn); st_row.addStretch()
        stc.layout.addWidget(self.cache_lbl)
        stc.layout.addLayout(st_row)
        L.addWidget(stc)

        # Desktop Shortcut
        sc_c = Card(); sc_c.add_title("Desktop Shortcut",
            "Quick-launch FilterGuardian from your Desktop")
        sc_c.layout.addWidget(Label(
            "The launcher (launcher.vbs) will prompt once to create a shortcut. "
            "Use the button below to add or re-create it at any time.",
            variant="body"))
        add_sc_btn = SecondaryButton("  🖥  Add Desktop Shortcut  ")
        add_sc_btn.clicked.connect(self._add_shortcut)
        sc_row = QHBoxLayout()
        sc_row.addWidget(add_sc_btn); sc_row.addStretch()
        sc_c.layout.addLayout(sc_row)
        L.addWidget(sc_c)

        # Tray info
        trc = Card(); trc.add_title("System Tray", "Background operation")
        trc.layout.addWidget(Label(
            "Closing the window minimizes FilterGuardian to the system tray. "
            "The browser monitor and Brain continue running in the background. "
            "Right-click the tray icon to restore or quit.", variant="body"))
        L.addWidget(trc); L.addStretch()

    def _save_profile(self):
        cfg = load_config()
        cfg["user_name"] = self.name_in.text().strip() or "Guardian"
        save_config(cfg)
        mw = self.window()
        if hasattr(mw, "dash_page"):
            mw.dash_page.refresh_welcome()
        show_toast(mw, f"Profile saved! Welcome, {cfg['user_name']}.", variant="success")

    def _set_theme(self, key):
        QApplication.instance().setStyleSheet(apply_theme(key))
        cfg = load_config(); cfg["theme"] = key; save_config(cfg)
        show_toast(self.window(), f"Theme: {THEMES[key]['name']}", variant="success")

    def _save_location(self):
        cfg = load_config()
        cfg["on_premises"] = self.rb_onsite.isChecked()
        save_config(cfg)
        mw = self.window()
        if hasattr(mw, "dash_page"):
            mw.dash_page.refresh_location()

    def _save_filter_test(self):
        cfg = load_config()
        cfg["filter_test_method"] = "proxy" if self.ft_method.currentText() == "HTTP Proxy" else "relay"
        cfg["filter_test_addr"]   = self.ft_addr.text().strip()
        cfg["filter_test_token"]  = self.ft_token.text().strip()
        save_config(cfg)
        show_toast(self.window(), "Filter test config saved", variant="success")

    def _update_backup_label(self):
        cfg = load_config()
        last = cfg.get("last_backup_date", "")
        path = cfg.get("last_backup_path", "")
        if last and path:
            self.backup_lbl.setText(
                f"Last backup: {last[:16].replace('T', ' ')}  —  {Path(path).name}")
        else:
            self.backup_lbl.setText("No backup created yet.")

    def _create_backup(self):
        import zipfile
        from datetime import datetime as _dt
        stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Backup",
            f"FilterGuardian_Backup_{stamp}.zip",
            "FilterGuardian Backup (*.zip)")
        if not path:
            return
        _DATA_FILES = [
            "proxies.db", "known_sites.json", "targets.json",
            "whitelist.json", "app_config.json", "pending_fingerprints.json",
        ]
        try:
            included = []
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for fname in _DATA_FILES:
                    fp = Path(fname)
                    if fp.exists():
                        zf.write(fp, fname)
                        included.append(fname)
                zf.writestr("backup_info.json", json.dumps({
                    "app": "FilterGuardian",
                    "version": "2.0",
                    "created": _dt.now().isoformat(),
                    "files": included,
                }, indent=2))
            cfg = load_config()
            cfg["last_backup_date"] = _dt.now().isoformat()
            cfg["last_backup_path"] = path
            save_config(cfg)
            self._update_backup_label()
            show_toast(self.window(),
                f"Backup saved — {len(included)} files ({Path(path).name})",
                variant="success")
        except Exception as e:
            show_toast(self.window(), f"Backup failed: {e}", variant="error")

    def _restore_backup(self):
        import zipfile
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Backup", "", "FilterGuardian Backup (*.zip)")
        if not path:
            return
        # Validate
        try:
            with zipfile.ZipFile(path, 'r') as zf:
                if 'backup_info.json' not in zf.namelist():
                    show_toast(self.window(),
                               "Not a valid FilterGuardian backup file", variant="error")
                    return
                info = json.loads(zf.read('backup_info.json').decode())
        except Exception as e:
            show_toast(self.window(), f"Cannot read backup: {e}", variant="error")
            return

        created = info.get("created", "unknown")[:16].replace("T", " ")
        files   = info.get("files", [])
        if QMessageBox.question(
                self, "Restore Backup",
                f"Restore backup from {created}?\n\n"
                f"Includes: {', '.join(files)}\n\n"
                f"This will overwrite your current database and settings.\n"
                f"The app should be restarted after restoring.",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        if S.brain_process and S.brain_process.poll() is None:
            show_toast(self.window(),
                       "Stop the Brain before restoring — it has the database open.",
                       variant="warning")
            return
        try:
            with zipfile.ZipFile(path, 'r') as zf:
                for fname in files:
                    if fname in zf.namelist():
                        zf.extract(fname, '.')
            show_toast(self.window(),
                       "Backup restored. Restart FilterGuardian to load restored data.",
                       variant="success")
            QMessageBox.information(self, "Restore Complete",
                "Backup restored successfully.\n\n"
                "Please close and reopen FilterGuardian to load the restored data.")
        except Exception as e:
            show_toast(self.window(), f"Restore failed: {e}", variant="error")

    @staticmethod
    def _dir_size_mb(path: str) -> float:
        total = 0
        try:
            for dp, _, files in os.walk(path):
                for fn in files:
                    try: total += os.path.getsize(os.path.join(dp, fn))
                    except OSError: pass
        except OSError:
            pass
        return total / (1024 * 1024)

    def _refresh_cache_label(self):
        cache_mb  = self._dir_size_mb("chrome_debug_profile")
        pycache_mb = self._dir_size_mb("__pycache__")
        parts = []
        if cache_mb > 0.1:
            parts.append(f"Chrome profile: {cache_mb:.0f} MB")
        if pycache_mb > 0.1:
            parts.append(f"Python cache: {pycache_mb:.1f} MB")
        self.cache_lbl.setText("  ".join(parts) if parts else "Cache is clean.")

    def _clear_cache(self):
        import shutil
        cleared = []
        for folder in ("chrome_debug_profile", "__pycache__"):
            if os.path.isdir(folder):
                try:
                    shutil.rmtree(folder)
                    cleared.append(folder)
                except Exception as e:
                    show_toast(self.window(), f"Could not clear {folder}: {e}", variant="warning")
        self._refresh_cache_label()
        if cleared:
            show_toast(self.window(),
                       f"Cleared: {', '.join(cleared)}", variant="success")
        else:
            show_toast(self.window(), "Nothing to clear.", variant="success")

    def _add_shortcut(self):
        app_dir  = os.path.abspath(".")
        launcher = os.path.join(app_dir, "launcher.vbs")
        icon     = os.path.join(app_dir, "app_icon.ico")
        desktop  = os.path.join(os.path.expanduser("~"), "Desktop")
        lnk      = os.path.join(desktop, "FilterGuardian.lnk")
        flag     = os.path.join(app_dir, "no_shortcut.flag")

        # Clear the "No" flag so the launcher won't suppress future prompts
        try:
            if os.path.exists(flag):
                os.remove(flag)
        except OSError:
            pass

        # Shortcut points at wscript.exe → launcher.vbs so it works on any machine
        icon_loc = f"{icon},0" if os.path.exists(icon) else ""
        ps = (
            f"$sh = New-Object -ComObject WScript.Shell; "
            f"$sc = $sh.CreateShortcut('{lnk}'); "
            f"$sc.TargetPath = 'wscript.exe'; "
            f"$sc.Arguments = '\"{launcher}\"'; "
            f"$sc.WorkingDirectory = '{app_dir}'; "
            f"$sc.Description = 'FilterGuardian — URL Analysis & Filter Testing'; "
        )
        if icon_loc:
            ps += f"$sc.IconLocation = '{icon_loc}'; "
        ps += "$sc.Save()"

        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                show_toast(self.window(), "Desktop shortcut created.", variant="success")
            else:
                show_toast(self.window(),
                           f"Shortcut failed: {r.stderr.strip()[:80]}", variant="error")
        except Exception as e:
            show_toast(self.window(), f"Shortcut failed: {e}", variant="error")

    def _load_wl(self):
        try:
            with open("whitelist.json") as f:
                self.wl.setPlainText("\n".join(json.load(f).get("whitelisted_domains",[])))
        except: pass

    def _save_wl(self):
        domains = [d.strip() for d in self.wl.toPlainText().splitlines() if d.strip()]
        with open("whitelist.json","w") as f: json.dump({"whitelisted_domains": domains}, f, indent=4)
        show_toast(self.window(), f"Whitelist saved ({len(domains)} domains)", variant="success")

    def _gen_relay_package(self):
        """Generate a zip containing relay_agent.py pre-configured for this port."""
        from PySide6.QtWidgets import QInputDialog
        import zipfile, textwrap

        # Ask for port
        port, ok = QInputDialog.getInt(
            self, "Relay Agent Port",
            "Port the relay agent will listen on:", 9224, 1025, 65535, 1)
        if not ok:
            return

        # Ask where to save
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Relay Package",
            f"FilterGuardian_Relay_Agent.zip",
            "ZIP Archive (*.zip)")
        if not path:
            return

        try:
            # Read the bundled relay_agent.py source
            relay_src_path = Path(get_asset_path('relay_agent.py'))
            if not relay_src_path.exists():
                relay_src_path = Path('relay_agent.py')
            relay_src = relay_src_path.read_text(encoding='utf-8')

            # Patch the default port in the source so `python relay_agent.py`
            # (no flags) uses the configured port automatically.
            relay_src = relay_src.replace('port = 9224', f'port = {port}', 1)

            # Build launcher batch file
            bat = textwrap.dedent(f"""\
                @echo off
                setlocal EnableDelayedExpansion
                title FilterGuardian Relay Agent (port {port})
                echo.
                echo  FilterGuardian Relay Agent
                echo  ==========================
                echo.

                REM ── Install Playwright if not already present ─────────────────────
                python -c "import playwright" >nul 2>&1
                if %errorlevel% neq 0 (
                    echo  Installing Playwright for accurate browser-based testing...
                    pip install playwright --quiet
                    playwright install chromium
                    echo.
                )

                REM ── Find the machine's IP ─────────────────────────────────────────
                for /f "tokens=2 delims=:" %%a in (
                  'ipconfig ^| findstr /c:"IPv4 Address"'
                ) do ( set _IP=%%a & goto :found )
                :found
                set _IP=!_IP:~1!

                REM ── Find Network Filter proxy (set by Group Policy) ────────────────
                set _PROXY=
                for /f "tokens=3" %%p in (
                  'reg query "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" /v ProxyServer 2^>nul ^| findstr ProxyServer'
                ) do set _PROXY=%%p

                echo  Your IP  : !_IP!
                echo  Port     : {port}
                if defined _PROXY (
                    echo  CK Proxy  : !_PROXY!
                ) else (
                    echo  CK Proxy  : not detected ^(Playwright will use system settings^)
                )
                echo.
                echo  FilterGuardian ^> Settings ^> Network Filter Test:
                echo    Method  : Relay Agent
                echo    Address : http://!_IP!:{port}
                echo.
                echo  Keep this window open while running filter tests.
                echo  Press Ctrl+C to stop.
                echo.
                if defined _PROXY (
                    python relay_agent.py --proxy !_PROXY!
                ) else (
                    python relay_agent.py
                )
                pause
            """)

            readme = textwrap.dedent(f"""\
                FilterGuardian Relay Agent
                ==========================

                WHAT THIS IS
                ------------
                This relay agent lets FilterGuardian test URLs through the network's
                Network Filter filter without you changing your own network connection.

                Deploy this on any machine already on the target network
                (a lab PC, a spare laptop, a Raspberry Pi on the LAN, etc.).

                HOW TO SET UP
                -------------
                1. Copy this folder to the target machine (a designated PC works).
                2. Make sure Python 3.8+ is installed.  https://python.org
                3. Double-click start_relay.bat.
                   It will auto-detect your IP and Network Filter proxy address.
                4. Note the IP address it displays.
                5. In FilterGuardian > Settings > Network Filter Test:
                     Method  : Relay Agent
                     Address : http://<displayed IP>:{port}
                6. Click Save, then run a filter test from the Database page.

                NETWORK FILTER PROXY — IMPORTANT
                --------------------------------
                Network Filter on most target networks runs as an explicit HTTP proxy.
                Browsers are configured (via Group Policy) to send all traffic through
                it. Python does NOT use that proxy automatically, so without --proxy
                the relay would bypass Network Filter entirely and every site would
                appear "allowed".

                start_relay.bat reads the machine's system proxy setting from the
                Windows registry and passes it to the relay automatically. If it
                shows "NOT DETECTED", find the proxy address manually:
                  - Open Chrome > Settings > System > Open proxy settings
                  - Look for "Proxy server" — it will be something like
                    proxy.example:8080  or  proxy.example:8080
                Then start manually:
                  python relay_agent.py --proxy http://HOST:PORT

                NETWORK FILTER CERTIFICATE WARNING
                ----------------------------------
                If Chrome shows ERR_CERT_DATE_INVALID on target machines, the
                Network Filter SSL inspection certificate has expired. The relay
                handles this automatically (it accepts expired certs). Ask your
                IT admin to renew the Network Filter inspection cert.

                CONFIGURED PORT
                ---------------
                Pre-configured for port {port}.  To change it:
                  python relay_agent.py --port 9225

                FIREWALL NOTE
                -------------
                Add an inbound Windows Firewall rule for TCP port {port} if
                FilterGuardian can't reach the relay.

                SECURITY
                --------
                The relay only accepts GET /test requests — not a general proxy.
                Add a token for extra security:
                  python relay_agent.py --token mysecret
                Then enter the same token in FilterGuardian Settings.
            """)

            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('relay_agent.py', relay_src)
                zf.writestr('start_relay.bat', bat)
                zf.writestr('README.txt', readme)

            show_toast(self.window(),
                       f"Relay package saved — port {port} pre-configured", variant="success")
        except Exception as e:
            show_toast(self.window(), f"Failed to generate package: {e}", variant="error")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════════════

NAV = [
    ("Dashboard",    "🏠", 0),
    ("Live Monitor", "📡", 1),
    ("Analytics",    "📊", 2),
    ("Database",     "📂", 3),
    ("Targets",      "🎯", 4),
    ("Settings",     "⚙️", 5),
]

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FilterGuardian v2.0")
        self.resize(1380, 880); self.setMinimumSize(1100, 700)
        database.init_db()

        central = QWidget(); self.setCentralWidget(central)
        root = QHBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # ── Sidebar ────────────────────────────────────────────────────────
        sidebar = QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(220)
        sL = QVBoxLayout(sidebar); sL.setContentsMargins(0, SPACE_XL, 0, SPACE_XL); sL.setSpacing(0)

        brand = QFrame(); bL = QVBoxLayout(brand); bL.setContentsMargins(SPACE_XL, 0, SPACE_XL, 0)
        logo = QLabel("FILTER\nGUARDIAN"); logo.setObjectName("brand_title")
        sub = QLabel("v2.0  |  PROXY RADAR"); sub.setObjectName("brand_sub")
        bL.addWidget(logo); bL.addWidget(sub); sL.addWidget(brand); sL.addSpacing(SPACE_XL)

        div = QFrame(); div.setFrameShape(QFrame.HLine)
        div.setStyleSheet(f"color:{theme._t()['border']}; max-height:1px;")
        sL.addWidget(div); sL.addSpacing(SPACE_MD)

        self._nav_btns = {}; self._btn_grp = QButtonGroup(self); self._btn_grp.setExclusive(True)
        for name, icon, idx in NAV:
            btn = NavButton(f"  {icon}  {name}", self)
            btn.clicked.connect(lambda _, i=idx: self._goto(i))
            sL.addWidget(btn); self._nav_btns[idx] = btn; self._btn_grp.addButton(btn)

        sL.addStretch()
        self._status_lbl = QLabel("  ● IDLE")
        self._status_lbl.setStyleSheet(f"color:{theme._t()['text_muted']}; font-size:{FONT_SIZE_SMALL}px; padding:0 {SPACE_XL}px;")
        sL.addWidget(self._status_lbl)
        root.addWidget(sidebar)

        # ── Pages ──────────────────────────────────────────────────────────
        self.stack = QStackedWidget()
        self.dash_page      = DashboardPage()
        self.live_page      = LiveMonitorPage()
        self.analytics_page = AnalyticsPage()
        self.db_page        = DatabasePage()
        self.targets_page   = TargetsPage()
        self.settings_page  = SettingsPage()
        for p in [self.dash_page, self.live_page, self.analytics_page,
                  self.db_page, self.targets_page, self.settings_page]:
            self.stack.addWidget(p)
        root.addWidget(self.stack)

        self._goto(0)
        self._setup_tray()

        self._st = QTimer(self); self._st.timeout.connect(self._tick); self._st.start(3000)
        if not load_config().get("setup_complete", False):
            QTimer.singleShot(0, self.open_setup)

    def open_setup(self):
        from setup_wizard import SetupWizard
        wizard = SetupWizard(load_config(), load_targets(), save_config, save_targets, self)
        if wizard.exec() == QDialog.Accepted:
            cfg = load_config()
            QApplication.instance().setStyleSheet(apply_theme(cfg["theme"]))
            self.dash_page.refresh_welcome()
            self.dash_page.refresh_location()
            self.targets_page.refresh()
            self.live_page.refresh_toolbox()
            self.settings_page.name_in.setText(cfg["user_name"])
            self.settings_page.ft_addr.setText(cfg["filter_test_addr"])
            self.settings_page.ft_token.setText(cfg["filter_test_token"])
            self.settings_page.ft_method.setCurrentText("HTTP Proxy" if cfg["filter_test_method"] == "proxy" else "Relay Agent")
            self.settings_page.rb_onsite.setChecked(cfg["on_premises"])
            self.settings_page.rb_remote.setChecked(not cfg["on_premises"])

    def _goto(self, idx):
        self.stack.setCurrentIndex(idx)
        b = self._nav_btns.get(idx)
        if b: b.setChecked(True)
        if idx == 2: self.analytics_page.refresh()
        if idx == 3: self.db_page.refresh()
        if idx == 4: self.targets_page.refresh()

    def _setup_tray(self):
        icon_path = get_asset_path("app_icon.ico")
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
        else:
            pix = QPixmap(16,16); pix.fill(QColor(ACCENT_BLUE)); icon = QIcon(pix)

        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("FilterGuardian — Running in background")

        t = theme._t()
        menu_ss = f"""
            QMenu {{ background:{t['bg_card']}; border:1px solid {t['border']}; border-radius:8px; padding:4px; }}
            QMenu::item {{ padding:7px 18px; border-radius:4px; color:{t['text_primary']}; font-size:13px; }}
            QMenu::item:selected {{ background:{t['accent_dim']}; color:{t['accent']}; }}
            QMenu::separator {{ height:1px; background:{t['border']}; margin:4px 0; }}
        """
        m = QMenu(); m.setStyleSheet(menu_ss)
        a1 = QAction("🔍  Show / Hide", self);    a1.triggered.connect(self._toggle_vis)
        a2 = QAction("🏠  Dashboard", self);      a2.triggered.connect(lambda: (self.show(), self._goto(0)))
        a3 = QAction("🚀  Full Scan", self);      a3.triggered.connect(lambda: send_cmd("FULL_SCAN"))
        a4 = QAction("⏻  Quit", self);           a4.triggered.connect(self._quit)
        m.addAction(a1); m.addSeparator(); m.addAction(a2); m.addAction(a3); m.addSeparator(); m.addAction(a4)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self._toggle_vis() if r == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()

    def _toggle_vis(self):
        if self.isVisible(): self.hide()
        else: self.show(); self.activateWindow(); self.raise_()

    def _tick(self):
        if is_live():
            self._status_lbl.setText(f"  ● LIVE  ({S.session_count} found)")
            self._status_lbl.setStyleSheet(f"color:{ACCENT_GREEN}; font-size:{FONT_SIZE_SMALL}px; padding:0 {SPACE_XL}px; font-weight:600;")
        else:
            self._status_lbl.setText("  ● IDLE")
            self._status_lbl.setStyleSheet(f"color:{theme._t()['text_muted']}; font-size:{FONT_SIZE_SMALL}px; padding:0 {SPACE_XL}px;")

    def closeEvent(self, event):
        if self.tray.isVisible():
            self.hide()
            self.tray.showMessage("FilterGuardian",
                "Still monitoring in the background. Double-click tray icon to restore.",
                QSystemTrayIcon.Information, 3000)
            event.ignore()
        else:
            self._quit()

    def _quit(self):
        if is_live(): S.browser_thread.stop()
        if S.brain_process and S.brain_process.poll() is None:
            try: S.brain_process.terminate()
            except: pass
        self.tray.hide()
        QApplication.instance().quit()


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = QApplication(sys.argv)
    _startup_cfg = load_config()
    app.setStyleSheet(apply_theme(_startup_cfg.get("theme", "dark")))
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
