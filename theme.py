"""
theme.py — Multi-theme system for FilterGuardian v2.0
"""

THEMES = {
    "midnight": {
        "name": "Midnight", "emoji": "🌑",
        "bg_base": "#0D1117", "bg_surface": "#161B22", "bg_card": "#21262D",
        "bg_overlay": "#30363D", "sidebar_bg": "#0D1117", "border": "#30363D",
        "border_heavy": "#484F58", "accent": "#388BFD", "accent_hover": "#58A6FF",
        "accent_dim": "rgba(56,139,253,0.15)", "text_primary": "#E6EDF3",
        "text_secondary": "#8B949E", "text_muted": "#484F58",
        "success": "#3FB950", "warning": "#D29922", "error": "#F85149",
        "info": "#79C0FF", "purple": "#BC8CFF",
        "chart_bg": "#161B22", "chart_fg": "#E6EDF3", "chart_grid": "#30363D",
    },
    "nord": {
        "name": "Nord", "emoji": "🧊",
        "bg_base": "#2E3440", "bg_surface": "#3B4252", "bg_card": "#434C5E",
        "bg_overlay": "#4C566A", "sidebar_bg": "#252A34", "border": "#4C566A",
        "border_heavy": "#646E82", "accent": "#88C0D0", "accent_hover": "#8FBCBB",
        "accent_dim": "rgba(136,192,208,0.15)", "text_primary": "#ECEFF4",
        "text_secondary": "#D8DEE9", "text_muted": "#616E88",
        "success": "#A3BE8C", "warning": "#EBCB8B", "error": "#BF616A",
        "info": "#81A1C1", "purple": "#B48EAD",
        "chart_bg": "#3B4252", "chart_fg": "#ECEFF4", "chart_grid": "#4C566A",
    },
    "dracula": {
        "name": "Dracula", "emoji": "🧛",
        "bg_base": "#282A36", "bg_surface": "#1E1F29", "bg_card": "#313341",
        "bg_overlay": "#44475A", "sidebar_bg": "#191A23", "border": "#44475A",
        "border_heavy": "#6272A4", "accent": "#BD93F9", "accent_hover": "#CBA8FF",
        "accent_dim": "rgba(189,147,249,0.15)", "text_primary": "#F8F8F2",
        "text_secondary": "#6272A4", "text_muted": "#44475A",
        "success": "#50FA7B", "warning": "#F1FA8C", "error": "#FF5555",
        "info": "#8BE9FD", "purple": "#FF79C6",
        "chart_bg": "#1E1F29", "chart_fg": "#F8F8F2", "chart_grid": "#44475A",
    },
    "catppuccin": {
        "name": "Catppuccin", "emoji": "☕",
        "bg_base": "#1E1E2E", "bg_surface": "#181825", "bg_card": "#313244",
        "bg_overlay": "#45475A", "sidebar_bg": "#11111B", "border": "#313244",
        "border_heavy": "#585B70", "accent": "#89B4FA", "accent_hover": "#B4BEFE",
        "accent_dim": "rgba(137,180,250,0.15)", "text_primary": "#CDD6F4",
        "text_secondary": "#A6ADC8", "text_muted": "#585B70",
        "success": "#A6E3A1", "warning": "#F9E2AF", "error": "#F38BA8",
        "info": "#89DCEB", "purple": "#CBA6F7",
        "chart_bg": "#181825", "chart_fg": "#CDD6F4", "chart_grid": "#313244",
    },
    "obsidian": {
        "name": "Obsidian", "emoji": "⬛",
        "bg_base": "#0A0A0A", "bg_surface": "#111111", "bg_card": "#1C1C1C",
        "bg_overlay": "#252525", "sidebar_bg": "#080808", "border": "#2A2A2A",
        "border_heavy": "#3A3A3A", "accent": "#7C5CFC", "accent_hover": "#9B7EFF",
        "accent_dim": "rgba(124,92,252,0.15)", "text_primary": "#F0F0F0",
        "text_secondary": "#888888", "text_muted": "#444444",
        "success": "#00D084", "warning": "#FFA500", "error": "#FF4444",
        "info": "#4EAAFF", "purple": "#CC44FF",
        "chart_bg": "#111111", "chart_fg": "#F0F0F0", "chart_grid": "#2A2A2A",
    },
}

CURRENT_THEME = "midnight"

def _t():
    return THEMES.get(CURRENT_THEME, THEMES["midnight"])

# Constants needed by widgets.py (default = midnight)
BG_PRIMARY    = THEMES["midnight"]["bg_base"]
BG_SECONDARY  = THEMES["midnight"]["bg_surface"]
BG_TERTIARY   = THEMES["midnight"]["bg_card"]
BG_ELEVATED   = THEMES["midnight"]["bg_overlay"]
TEXT_PRIMARY   = THEMES["midnight"]["text_primary"]
TEXT_SECONDARY = THEMES["midnight"]["text_secondary"]
TEXT_DISABLED  = THEMES["midnight"]["text_muted"]
ACCENT_BLUE    = THEMES["midnight"]["accent"]
ACCENT_GREEN   = THEMES["midnight"]["success"]
ACCENT_YELLOW  = THEMES["midnight"]["warning"]
ACCENT_RED     = THEMES["midnight"]["error"]
ACCENT_CYAN    = THEMES["midnight"]["info"]
ACCENT_PURPLE  = THEMES["midnight"]["purple"]
BORDER_LIGHT   = THEMES["midnight"]["border"]
BORDER_HEAVY   = THEMES["midnight"]["border_heavy"]

FONT_FAMILY      = "Segoe UI, Inter, -apple-system, BlinkMacSystemFont, sans-serif"
FONT_FAMILY_MONO = "Cascadia Code, Consolas, SF Mono, monospace"
FONT_SIZE_DISPLAY = 28
FONT_SIZE_TITLE   = 20
FONT_SIZE_HEADING = 16
FONT_SIZE_BODY    = 13
FONT_SIZE_SMALL   = 11
FONT_SIZE_MICRO   = 10

SPACE_XS  = 4
SPACE_SM  = 8
SPACE_MD  = 12
SPACE_LG  = 16
SPACE_XL  = 24
SPACE_2XL = 32
SPACE_3XL = 48

RADIUS_SM = 4
RADIUS_MD = 8
RADIUS_LG = 12
RADIUS_XL = 16


def apply_theme(name: str) -> str:
    global CURRENT_THEME
    if name in THEMES:
        CURRENT_THEME = name
    return get_stylesheet()


def get_chart_colors():
    t = _t()
    palette = [t["accent"], t["success"], t["warning"], t["error"],
               t["info"], t["purple"], "#FF8C00", "#20B2AA", "#FF6EB4", "#7FFF00"]
    return t["chart_bg"], t["chart_fg"], t["chart_grid"], palette


def get_stylesheet() -> str:
    t = _t()
    B   = t["bg_base"];    S  = t["bg_surface"]; C  = t["bg_card"]; O  = t["bg_overlay"]
    SB  = t["sidebar_bg"]; BD = t["border"];     BH = t["border_heavy"]
    AC  = t["accent"];     AH = t["accent_hover"]; AD = t["accent_dim"]
    TP  = t["text_primary"]; TS = t["text_secondary"]; TM = t["text_muted"]
    GN  = t["success"];    WN = t["warning"];    ER = t["error"]; IF = t["info"]; PU = t["purple"]
    FF  = FONT_FAMILY
    return f"""
    QMainWindow, QWidget {{ background:{B}; color:{TP}; font-family:{FF}; font-size:13px; border:none; outline:none; }}
    QSplitter::handle {{ background:{BD}; }}
    QStackedWidget {{ background:{B}; border:none; }}
    QFrame#sidebar {{ background:{SB}; border-right:1px solid {BD}; }}
    QLabel#brand_title {{ color:{AC}; font-size:15px; font-weight:800; letter-spacing:2px; }}
    QLabel#brand_sub   {{ color:{TM}; font-size:11px; letter-spacing:1px; }}
    QLabel#nav_section_label {{ color:{TM}; font-size:11px; font-weight:700; letter-spacing:1.2px; padding:8px 20px 4px 20px; }}
    QPushButton#sidebar_nav {{
        background:transparent; color:{TS}; border:none; border-radius:8px;
        padding:9px 16px; text-align:left; font-size:13px; font-weight:500; margin:1px 8px;
    }}
    QPushButton#sidebar_nav:hover {{ background:{C}; color:{TP}; }}
    QPushButton#sidebar_nav:checked {{ background:{AD}; color:{AC}; border-left:3px solid {AC}; padding-left:13px; font-weight:600; }}
    QFrame#card {{ background:{S}; border:1px solid {BD}; border-radius:12px; }}
    QFrame#card_elevated {{ background:{C}; border:1px solid {BH}; border-radius:12px; }}
    QFrame#card_accent {{ background:{S}; border:1px solid {AC}; border-radius:12px; }}
    QFrame#stat_card {{ background:{S}; border:1px solid {BD}; border-radius:12px; min-height:100px; }}
    QFrame#feed_item {{ background:{C}; border:1px solid {BD}; border-radius:8px; }}
    QFrame#feed_item:hover {{ border-color:{BH}; background:{O}; }}
    QLabel[objectName="display"]  {{ color:{TP}; font-size:20px; font-weight:700; }}
    QLabel[objectName="title"]    {{ color:{TP}; font-size:16px; font-weight:600; }}
    QLabel[objectName="heading"]  {{ color:{TP}; font-size:16px; font-weight:600; }}
    QLabel[objectName="body"]     {{ color:{TP}; font-size:13px; }}
    QLabel[objectName="subtitle"] {{ color:{TS}; font-size:13px; }}
    QLabel[objectName="caption"]  {{ color:{TS}; font-size:11px; font-weight:500; }}
    QLabel#badge_success {{ color:{GN}; background:rgba(63,185,80,0.15); border-radius:10px; padding:2px 8px; font-size:11px; font-weight:600; }}
    QLabel#badge_warning {{ color:{WN}; background:rgba(210,153,34,0.15); border-radius:10px; padding:2px 8px; font-size:11px; font-weight:600; }}
    QLabel#badge_error   {{ color:{ER}; background:rgba(248,81,73,0.15);  border-radius:10px; padding:2px 8px; font-size:11px; font-weight:600; }}
    QLabel#badge_info    {{ color:{IF}; background:rgba(121,192,255,0.15);border-radius:10px; padding:2px 8px; font-size:11px; font-weight:600; }}
    QLabel#badge_default {{ color:{TS}; background:{C}; border-radius:10px; padding:2px 8px; font-size:11px; }}
    QLabel#status_live  {{ color:{GN}; background:rgba(63,185,80,0.15);   border-radius:10px; padding:3px 10px; font-size:11px; font-weight:700; }}
    QLabel#status_idle  {{ color:{TM}; background:{C};                     border-radius:10px; padding:3px 10px; font-size:11px; font-weight:600; }}
    QLabel#status_warn  {{ color:{WN}; background:rgba(210,153,34,0.15);   border-radius:10px; padding:3px 10px; font-size:11px; font-weight:700; }}
    QLabel#status_error {{ color:{ER}; background:rgba(248,81,73,0.15);    border-radius:10px; padding:3px 10px; font-size:11px; font-weight:700; }}
    QPushButton#primary {{
        background:{AC}; color:white; border:none; border-radius:8px;
        padding:8px 20px; font-size:13px; font-weight:600; min-height:36px;
    }}
    QPushButton#primary:hover {{ background:{AH}; }}
    QPushButton#primary:disabled {{ background:{O}; color:{TM}; }}
    QPushButton {{
        background:{C}; color:{TP}; border:1px solid {BD}; border-radius:8px;
        padding:8px 20px; font-size:13px; font-weight:500; min-height:36px;
    }}
    QPushButton:hover {{ background:{O}; border-color:{BH}; }}
    QPushButton:disabled {{ color:{TM}; }}
    QPushButton#danger {{ background:rgba(248,81,73,0.15); color:{ER}; border:1px solid rgba(248,81,73,0.3); border-radius:8px; padding:8px 20px; font-weight:600; min-height:36px; }}
    QPushButton#danger:hover {{ background:rgba(248,81,73,0.25); border-color:{ER}; }}
    QPushButton#ghost {{ background:transparent; color:{TS}; border:none; border-radius:6px; padding:4px 8px; min-height:28px; }}
    QPushButton#ghost:hover {{ background:{C}; color:{TP}; }}
    QPushButton#icon_btn {{ background:transparent; color:{TS}; border:1px solid {BD}; border-radius:8px; padding:8px; font-size:16px; min-width:36px; min-height:36px; }}
    QPushButton#icon_btn:hover {{ background:{C}; color:{TP}; }}
    QPushButton#theme_btn {{ background:{C}; color:{TS}; border:2px solid {BD}; border-radius:12px; padding:12px 16px; font-size:13px; min-height:60px; }}
    QPushButton#theme_btn:hover {{ border-color:{AC}; color:{TP}; }}
    QPushButton#theme_btn:checked {{ border-color:{AC}; color:{AC}; background:{AD}; }}
    QLineEdit, QTextEdit, QPlainTextEdit {{
        background:{C}; color:{TP}; border:1px solid {BD}; border-radius:8px;
        padding:8px 12px; font-size:13px; min-height:34px;
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color:{AC}; background:{S}; }}
    QLineEdit:disabled {{ color:{TM}; background:{S}; }}
    QComboBox {{
        background:{C}; color:{TP}; border:1px solid {BD}; border-radius:8px;
        padding:8px 12px; font-size:13px; min-height:34px;
    }}
    QComboBox:focus {{ border-color:{AC}; }}
    QComboBox:hover {{ border-color:{BH}; }}
    QComboBox::drop-down {{ border:none; width:24px; }}
    QComboBox QAbstractItemView {{
        background:{C}; color:{TP}; border:1px solid {BD}; border-radius:8px;
        selection-background-color:{AD}; outline:none; padding:4px;
    }}
    QComboBox QAbstractItemView::item {{ padding:8px 12px; border-radius:4px; }}
    QComboBox QAbstractItemView::item:selected {{ background:{AD}; color:{AC}; }}
    QSpinBox {{
        background:{C}; color:{TP}; border:1px solid {BD}; border-radius:8px;
        padding:8px 12px; min-height:34px;
    }}
    QSpinBox:focus {{ border-color:{AC}; }}
    QSpinBox::up-button, QSpinBox::down-button {{ background:transparent; border:none; width:20px; }}
    QTableWidget, QTableView {{
        background:{S}; color:{TP}; gridline-color:{BD}; border:1px solid {BD};
        border-radius:8px; alternate-background-color:{B};
        selection-background-color:{AD}; selection-color:{TP}; outline:none;
    }}
    QTableWidget::item, QTableView::item {{ padding:8px 12px; border:none; border-bottom:1px solid {BD}; }}
    QTableWidget::item:selected {{ background:{AD}; }}
    QHeaderView::section {{
        background:{C}; color:{TS}; border:none; border-bottom:1px solid {BD};
        border-right:1px solid {BD}; padding:8px 12px; font-size:11px; font-weight:700; letter-spacing:0.6px;
    }}
    QHeaderView::section:last {{ border-right:none; }}
    QHeaderView::section:hover {{ background:{O}; color:{TP}; }}
    QScrollBar:vertical {{ background:transparent; width:10px; margin:2px; }}
    QScrollBar::handle:vertical {{ background:{O}; border-radius:5px; min-height:30px; }}
    QScrollBar::handle:vertical:hover {{ background:{BH}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ background:none; height:0; }}
    QScrollBar:horizontal {{ background:transparent; height:10px; margin:2px; }}
    QScrollBar::handle:horizontal {{ background:{O}; border-radius:5px; min-width:30px; }}
    QScrollBar::handle:horizontal:hover {{ background:{BH}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ background:none; width:0; }}
    QProgressBar {{ background:{C}; border:none; border-radius:3px; height:6px; color:transparent; }}
    QProgressBar::chunk {{ background:{AC}; border-radius:3px; }}
    QCheckBox {{ color:{TP}; spacing:8px; font-size:13px; }}
    QCheckBox::indicator {{ width:16px; height:16px; border:1px solid {BH}; border-radius:3px; background:{C}; }}
    QCheckBox::indicator:hover {{ border-color:{AC}; }}
    QCheckBox::indicator:checked {{ background:{AC}; border-color:{AC}; }}
    QFrame[frameShape="4"], QFrame[frameShape="5"] {{ color:{BD}; background:{BD}; max-height:1px; border:none; }}
    QMessageBox, QDialog {{ background:{S}; }}
    QMessageBox QLabel, QDialog QLabel {{ color:{TP}; font-size:13px; }}
    QToolTip {{ background:{O}; color:{TP}; border:1px solid {BD}; border-radius:4px; padding:6px 10px; font-size:11px; }}
    QScrollArea {{ border:none; background:transparent; }}
    QScrollArea > QWidget > QWidget {{ background:transparent; }}
    QMenu {{ background:{C}; border:1px solid {BD}; border-radius:8px; padding:4px; }}
    QMenu::item {{ padding:7px 18px; border-radius:4px; color:{TP}; font-size:13px; }}
    QMenu::item:selected {{ background:{AD}; color:{AC}; }}
    QMenu::separator {{ height:1px; background:{BD}; margin:4px 0; }}
    QTabWidget::pane {{ border:1px solid {BD}; border-radius:8px; top:-1px; }}
    QTabBar::tab {{ background:transparent; color:{TS}; padding:8px 16px; border:none; border-bottom:2px solid transparent; font-weight:500; }}
    QTabBar::tab:selected {{ color:{AC}; border-bottom:2px solid {AC}; font-weight:600; }}
    QTabBar::tab:hover:!selected {{ color:{TP}; }}
    """
