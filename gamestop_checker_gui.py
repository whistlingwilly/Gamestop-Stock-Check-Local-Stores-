"""
GameStop Pokémon Inventory Checker — Visual Desktop App
=======================================================
SETUP (one-time):
    pip install playwright Pillow
    playwright install chromium

RUN:
    python gamestop_checker_gui.py
"""

import asyncio
import configparser
import io
import json
import os
import queue
import random
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from datetime import datetime
from tkinter import scrolledtext

try:
    import winsound
    SOUND_OK = True
except ImportError:
    SOUND_OK = False

# Patchright = drop-in Playwright replacement that patches CDP leaks Cloudflare detects
try:
    from patchright.async_api import async_playwright as _async_pw
    PATCHRIGHT_OK = True
except ImportError:
    try:
        from playwright.async_api import async_playwright as _async_pw
        PATCHRIGHT_OK = False
    except ImportError:
        _async_pw = None
        PATCHRIGHT_OK = False

# ── CONFIG ────────────────────────────────────────────────────────────────────

ZIP_CODE           = ""
RADIUS_MILES       = 50
RADIUS             = f"{RADIUS_MILES} Miles"
CHECK_INTERVAL_MIN = 60
HEADLESS           = True
ROW_H              = 46    # compact list row height
CONFIG_FILE        = "gamestop_config.ini"
GAMES_FILE         = "games.json"

# ── RANDOMISATION (keeps Cloudflare from recognising a pattern) ───────────────
STARTUP_DELAY_MIN  = 2    # minutes — random wait before the very first sweep
STARTUP_DELAY_MAX  = 8    # minutes
BETWEEN_GAMES_MIN  = 25   # seconds between each game check
BETWEEN_GAMES_MAX  = 75   # seconds — wide spread to avoid timing fingerprints
SHUFFLE_ORDER      = True  # randomise which game is checked first each sweep

# ── SYSTEM DETECTION HELPERS ──────────────────────────────────────────────────

# Badge colours keyed by system string
SYS_COLORS = {
    "GBA":  "#8855ee",
    "GBC":  "#1199ee",
    "GB":   "#557755",
    "NS2":  "#cc0033",
    "NSW":  "#e4000f",
    "N3DS": "#0055bb",
    "3DS":  "#0055bb",
    "NDS":  "#cc6600",
    "PS5":  "#003791",
    "XBX":  "#107c10",
    "Game": "#445566",
}

def sys_from_url(url: str) -> str:
    u = url.lower()
    if "game-boy-advance" in u or "/gba" in u:    return "GBA"
    if "game-boy-color"   in u or "/gbc" in u:    return "GBC"
    if "game-boy"         in u:                    return "GB"
    if "nintendo-switch-2" in u or "switch-2" in u: return "NS2"
    if "nintendo-switch"  in u:                    return "NSW"
    if "nintendo-3ds"     in u or "/3ds" in u:    return "N3DS"
    if "nintendo-ds"      in u or "/ds/" in u:    return "NDS"
    if "playstation-5"    in u or "/ps5" in u:    return "PS5"
    if "xbox"             in u:                    return "XBX"
    return "Game"

def name_from_url(url: str) -> str:
    """Best-effort: turn the URL slug into a readable title."""
    try:
        slug = url.rstrip("/").split("/")[-2]   # e.g. "pokemon-emerald-version---game-boy-advance"
        slug = slug.split("---")[0]              # drop system suffix
        return slug.replace("-", " ").title()
    except Exception:
        return "New Game"

def id_from_url(url: str) -> str:
    try:
        part = url.rstrip("/").split("/")[-1]    # "122847.html"
        return part.replace(".html", "")
    except Exception:
        return ""

def bg_from_sys(sys: str) -> str:
    defaults = {
        "GBA": "#6633aa", "GBC": "#1a55aa", "GB": "#3a5544",
        "NS2": "#6d1a8a", "NSW": "#880011", "N3DS": "#003388",
        "NDS": "#884400", "PS5": "#001f55", "XBX": "#0a4a0a",
        "Game": "#2a3a4a",
    }
    return defaults.get(sys, "#2a3a4a")

def load_games() -> list:
    """Load games list from JSON file, falling back to built-in defaults."""
    if os.path.exists(GAMES_FILE):
        try:
            with open(GAMES_FILE) as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return list(PRODUCTS)   # copy of defaults

def save_games(games: list):
    try:
        with open(GAMES_FILE, "w") as f:
            json.dump(games, f, indent=2)
    except Exception:
        pass

# GameStop internal API endpoint (discovered by trent — thanks!)
GS_API = (
    "https://www.gamestop.com/on/demandware.store/Sites-gamestop-us-Site/"
    "default/Stores-FindStores"
    "?hasCondition=true"
    "&hasVariantsAvailableForLookup=false"
    "&hasVariantsAvailableForPickup=true"
    "&source=pdp"
    "&showMap=false"
    "&products={product_id}:1"
    "&selectedStore=undefined"
)

# ── FULL GAME CATALOG (shown in startup selector) ────────────────────────────
# Each entry: name, sys, bg color, GameStop product ID, URL
# Games with no confirmed GameStop listing have url=None and are hidden.

GAME_CATALOG = [
    # ── Game Boy ──────────────────────────────────────────────────────────────
    {"console": "Game Boy",  "name": "Pokémon Red",          "sys": "GB",  "bg": "#cc2222", "id": "123009",
     "url": "https://www.gamestop.com/video-games/retro-gaming/products/pokemon-red-version---game-boy/123009.html"},
    {"console": "Game Boy",  "name": "Pokémon Blue",         "sys": "GB",  "bg": "#1e55aa", "id": "123007",
     "url": "https://www.gamestop.com/video-games/retro-gaming/products/pokemon-blue-version---game-boy-color/123007.html"},
    {"console": "Game Boy",  "name": "Pokémon Yellow",       "sys": "GB",  "bg": "#ccaa00", "id": "123012",
     "url": "https://www.gamestop.com/video-games/retro-gaming/products/pokemon-yellow-version-special-pikachu-edition---game-boy/123012.html"},
    {"console": "Game Boy",  "name": "Pokémon Gold",         "sys": "GBC", "bg": "#aa8800", "id": "123008",
     "url": "https://www.gamestop.com/video-games/retro-gaming/products/pokemon-gold-version---game-boy-color/123008.html"},
    {"console": "Game Boy",  "name": "Pokémon Silver",       "sys": "GBC", "bg": "#778899", "id": "123010",
     "url": "https://www.gamestop.com/video-games/retro-gaming/products/pokemon-silver-version---game-boy/123010.html"},
    {"console": "Game Boy",  "name": "Pokémon Crystal",      "sys": "GBC", "bg": "#1a88bb", "id": "123159",
     "url": "https://www.gamestop.com/video-games/retro-gaming/products/pokemon-crystal-version---game-boy-color/123159.html"},
    # ── Game Boy Advance ──────────────────────────────────────────────────────
    {"console": "Game Boy Advance", "name": "Pokémon Ruby",        "sys": "GBA", "bg": "#aa1133", "id": "122852",
     "url": "https://www.gamestop.com/video-games/retro-gaming/products/pokemon-ruby-version---game-boy-advance/122852.html"},
    {"console": "Game Boy Advance", "name": "Pokémon Sapphire",    "sys": "GBA", "bg": "#1144aa", "id": "122853",
     "url": "https://www.gamestop.com/video-games/retro-gaming/products/pokemon-sapphire-version---game-boy-advance/122853.html"},
    {"console": "Game Boy Advance", "name": "Pokémon Emerald",     "sys": "GBA", "bg": "#2d7a3c", "id": "122847",
     "url": "https://www.gamestop.com/video-games/retro-gaming/products/pokemon-emerald-version---game-boy-advance/122847.html"},
    {"console": "Game Boy Advance", "name": "Pokémon Fire Red",    "sys": "GBA", "bg": "#bb3300", "id": "122848",
     "url": "https://www.gamestop.com/video-games/retro-gaming/products/pokemon-firered-version---game-boy-advance/122848.html"},
    {"console": "Game Boy Advance", "name": "Pokémon Leaf Green",  "sys": "GBA", "bg": "#3a9922", "id": "122849",
     "url": "https://www.gamestop.com/video-games/retro-gaming/products/pokemon-leafgreen-version---game-boy-advance/122849.html"},
    # ── Nintendo DS ───────────────────────────────────────────────────────────
    {"console": "Nintendo DS", "name": "Pokémon Diamond",    "sys": "NDS", "bg": "#4466cc", "id": "919309",
     "url": "https://www.gamestop.com/video-games/nds/products/pokemon-diamond---nintendo-ds/919309.html"},
    {"console": "Nintendo DS", "name": "Pokémon Pearl",      "sys": "NDS", "bg": "#cc44aa", "id": "919310",
     "url": "https://www.gamestop.com/video-games/nds/products/pokemon-pearl---nintendo-ds/919310.html"},
    {"console": "Nintendo DS", "name": "Pokémon Platinum",   "sys": "NDS", "bg": "#555577", "id": "919953",
     "url": "https://www.gamestop.com/video-games/nds/products/pokemon-platinum-version---nintendo-ds/919953.html"},
    {"console": "Nintendo DS", "name": "Pokémon HeartGold",  "sys": "NDS", "bg": "#b8860b", "id": "920299",
     "url": "https://www.gamestop.com/video-games/nds/products/pokemon-heartgold-game-only---nintendo-ds/920299.html"},
    {"console": "Nintendo DS", "name": "Pokémon SoulSilver", "sys": "NDS", "bg": "#3a3a3a", "id": "10077723",
     "url": "https://www.gamestop.com/video-games/nds/products/pokemon-soulsilver-game-only---nintendo-ds/10077723.html"},
    {"console": "Nintendo DS", "name": "Pokémon Black",      "sys": "NDS", "bg": "#2a2a2a", "id": "920599",
     "url": "https://www.gamestop.com/video-games/nds/products/pokemon-black---nintendo-ds/920599.html"},
    {"console": "Nintendo DS", "name": "Pokémon White",      "sys": "NDS", "bg": "#888899", "id": "920600",
     "url": "https://www.gamestop.com/video-games/nds/products/pokemon-white---nintendo-ds/920600.html"},
    {"console": "Nintendo DS", "name": "Pokémon Black 2",    "sys": "NDS", "bg": "#1a1a44", "id": "920776",
     "url": "https://www.gamestop.com/video-games/nds/products/pokemon-black-version-2---nintendo-ds/920776.html"},
    {"console": "Nintendo DS", "name": "Pokémon White 2",    "sys": "NDS", "bg": "#aaaacc", "id": "920777",
     "url": "https://www.gamestop.com/video-games/nds/products/pokemon-white-version-2---nintendo-ds/920777.html"},
    # ── Nintendo 3DS ──────────────────────────────────────────────────────────
    {"console": "Nintendo 3DS", "name": "Pokémon X",             "sys": "3DS", "bg": "#1166cc", "id": "922210",
     "url": "https://www.gamestop.com/video-games/3ds/products/pokemon-x---nintendo-3ds/922210.html"},
    {"console": "Nintendo 3DS", "name": "Pokémon Y",             "sys": "3DS", "bg": "#cc1166", "id": "922211",
     "url": "https://www.gamestop.com/video-games/3ds/products/pokemon-y---nintendo-3ds/922211.html"},
    {"console": "Nintendo 3DS", "name": "Pokémon Omega Ruby",    "sys": "3DS", "bg": "#881122", "id": "105948",
     "url": "https://www.gamestop.com/video-games/3ds/products/pokemon-omega-ruby---nintendo-3ds/105948.html"},
    {"console": "Nintendo 3DS", "name": "Pokémon Alpha Sapphire","sys": "3DS", "bg": "#112288", "id": "105947",
     "url": "https://www.gamestop.com/video-games/3ds/products/pokemon-alpha-sapphire---nintendo-3ds/105947.html"},
    {"console": "Nintendo 3DS", "name": "Pokémon Sun",           "sys": "3DS", "bg": "#cc6600", "id": "134164",
     "url": "https://www.gamestop.com/video-games/3ds/products/pokemon-sun---nintendo-3ds/134164.html"},
    {"console": "Nintendo 3DS", "name": "Pokémon Moon",          "sys": "3DS", "bg": "#224466", "id": "134647",
     "url": "https://www.gamestop.com/video-games/3ds/products/pokemon-moon---nintendo-3ds/134647.html"},
    {"console": "Nintendo 3DS", "name": "Pokémon Ultra Sun",     "sys": "3DS", "bg": "#aa4400", "id": "158249",
     "url": "https://www.gamestop.com/video-games/3ds/products/pokemon-ultra-sun---nintendo-3ds/158249.html"},
    {"console": "Nintendo 3DS", "name": "Pokémon Ultra Moon",    "sys": "3DS", "bg": "#112244", "id": "158248",
     "url": "https://www.gamestop.com/video-games/3ds/products/pokemon-ultra-moon---nintendo-3ds/158248.html"},
    # ── Nintendo Switch ───────────────────────────────────────────────────────
    {"console": "Nintendo Switch", "name": "Pokémon Let's Go Pikachu", "sys": "NSW", "bg": "#cc9900", "id": "184788",
     "url": "https://www.gamestop.com/video-games/nintendo-switch/products/pokemon-lets-go-pikachu---nintendo-switch/184788.html"},
    {"console": "Nintendo Switch", "name": "Pokémon Let's Go Eevee",   "sys": "NSW", "bg": "#aa6600", "id": "184789",
     "url": "https://www.gamestop.com/video-games/nintendo-switch/products/pokemon-lets-go-eevee---nintendo-switch/184789.html"},
    {"console": "Nintendo Switch", "name": "Pokémon Sword",            "sys": "NSW", "bg": "#1155cc", "id": "207999",
     "url": "https://www.gamestop.com/video-games/nintendo-switch/products/pokemon-sword---nintendo-switch/207999.html"},
    {"console": "Nintendo Switch", "name": "Pokémon Shield",           "sys": "NSW", "bg": "#cc1155", "id": "207998",
     "url": "https://www.gamestop.com/video-games/nintendo-switch/products/pokemon-shield---nintendo-switch/207998.html"},
    {"console": "Nintendo Switch", "name": "Pokémon Brilliant Diamond","sys": "NSW", "bg": "#335599", "id": "258864",
     "url": "https://www.gamestop.com/video-games/nintendo-switch/products/pokemon-brilliant-diamond---nintendo-switch/258864.html"},
    {"console": "Nintendo Switch", "name": "Pokémon Shining Pearl",    "sys": "NSW", "bg": "#993355", "id": "258865",
     "url": "https://www.gamestop.com/video-games/nintendo-switch/products/pokemon-shining-pearl---nintendo-switch/258865.html"},
    {"console": "Nintendo Switch", "name": "Pokémon Legends: Arceus",  "sys": "NSW", "bg": "#334455", "id": "324786",
     "url": "https://www.gamestop.com/video-games/nintendo-switch/products/pokemon-legends-arceus---nintendo-switch/324786.html"},
    {"console": "Nintendo Switch", "name": "Pokémon Scarlet",          "sys": "NSW", "bg": "#cc2200", "id": "349083",
     "url": "https://www.gamestop.com/video-games/nintendo-switch/products/pokemon-scarlet---nintendo-switch/349083.html"},
    {"console": "Nintendo Switch", "name": "Pokémon Violet",           "sys": "NSW", "bg": "#6611aa", "id": "349140",
     "url": "https://www.gamestop.com/video-games/nintendo-switch/products/pokemon-violet---nintendo-switch/349140.html"},
    # ── Nintendo Switch 2 ─────────────────────────────────────────────────────
    {"console": "Nintendo Switch 2", "name": "Pokémon Legends: Z-A",  "sys": "NS2", "bg": "#333366", "id": "426426",
     "url": "https://www.gamestop.com/video-games/nintendo-switch-2/products/pokemon-legends-z-a---nintendo-switch-2-edition/426426.html"},
]

# Default PRODUCTS kept for load_games() fallback (previously selected games)
PRODUCTS = [g for g in GAME_CATALOG if g["id"] in {
    "122847","123007","122848","122849","122852",    # Emerald, Blue, Fire Red, Leaf Green, Ruby
    "123159","920599","920600","920777","920776",    # Crystal, Black, White, White2, Black2
    "10077723","920299",                             # SoulSilver, HeartGold
}]


# ── PALETTE ───────────────────────────────────────────────────────────────────

BG      = "#0e0e1c"
CARD    = "#16162a"
EDGE    = "#26264a"
FG      = "#dcdcf0"
DIM     = "#555578"
ACCENT  = "#ff3366"

D_PEND  = "#2e2e50"
D_CHK   = "#44aaff"
D_YES   = "#22dd77"
D_LIM   = "#ffaa22"
D_NO    = "#dd2233"
D_ERR   = "#ff4444"


# ── APP ───────────────────────────────────────────────────────────────────────

class App:
    def __init__(self, root: tk.Tk):
        self.root    = root
        self.q       = queue.Queue()
        self.running = False
        self.loop    = None
        self.thread  = None
        self.next_ts = None

        # ── User-editable settings (loaded from config, saved on change) ──────
        cfg = self._load_settings()
        self.zip_code    = cfg.get("zip_code",    ZIP_CODE)
        self.radius_mi   = int(cfg.get("radius_miles", str(RADIUS_MILES)))
        self.interval_min = int(cfg.get("interval_min", str(CHECK_INTERVAL_MIN)))

        # runtime games list (can be edited while app is running)
        self.runtime_games = load_games()

        # persistent alert state
        self.alert_active = False
        self.alert_event  = threading.Event()   # used to interrupt the 20s wait

        # per-row widget refs
        self.dot_canvas  = []
        self.stat_labels = []
        self.time_labels = []
        self.det_labels  = []
        self.pulse_on    = []

        root.title("GameStop Pokémon Checker")
        root.configure(bg=BG)
        root.resizable(True, True)
        root.minsize(520, 400)

        self._build()
        self._tick()
        self._poll()

        # Show game selection dialog on every launch
        root.after(150, self._show_game_selector)

    # ─────────────────────────────────────────────────────────────────────────
    # UI BUILD
    # ─────────────────────────────────────────────────────────────────────────

    def _build(self):
        # ── Top bar ───────────────────────────────────────────────────────────
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=18, pady=(14, 4))

        tk.Label(top, text="🎮  Pokémon GameStop Tracker",
                 bg=BG, fg=FG, font=("Helvetica", 15, "bold")).pack(side="left")

        self.btn_now = tk.Button(
            top, text="  Check Now  ", bg=ACCENT, fg="white",
            activebackground="#cc2255", activeforeground="white",
            relief="flat", padx=10, pady=4, cursor="hand2",
            font=("Helvetica", 10, "bold"), command=self._on_now)
        self.btn_now.pack(side="right")

        self.btn_menu = tk.Button(
            top, text="  ☰ Menu  ", bg=EDGE, fg=FG,
            activebackground="#333355", activeforeground=FG,
            relief="flat", padx=10, pady=4, cursor="hand2",
            font=("Helvetica", 10), command=self._show_menu)
        self.btn_menu.pack(side="right", padx=(0, 8))

        # ── SNOOZE banner — hidden until alert fires ───────────────────────
        self.snooze_frame = tk.Frame(self.root, bg="#994400")
        # (not packed yet — shown only when alert is active)

        self.snooze_lbl = tk.Label(
            self.snooze_frame,
            text="", bg="#994400", fg="white",
            font=("Helvetica", 11, "bold"))
        self.snooze_lbl.pack(side="left", padx=18, pady=8, expand=True, fill="x")

        tk.Button(
            self.snooze_frame, text="  🔕  Snooze  ", bg="#cc5500", fg="white",
            activebackground="#aa3300", activeforeground="white",
            relief="flat", padx=14, pady=6, cursor="hand2",
            font=("Helvetica", 11, "bold"), command=self._snooze_alert,
        ).pack(side="right", padx=12, pady=6)

        # ── Info / countdown bar ──────────────────────────────────────────────
        bar = tk.Frame(self.root, bg=CARD)
        bar.pack(fill="x", padx=18, pady=(4, 10))

        self.settings_lbl = tk.Label(bar, text=f"  {self._settings_text()}",
                 bg=CARD, fg=DIM, font=("Helvetica", 9))
        self.settings_lbl.pack(side="left", pady=5)

        self.cd_lbl = tk.Label(bar, text="Next: —", bg=CARD, fg=DIM, font=("Helvetica", 9))
        self.cd_lbl.pack(side="right", padx=10)

        # ── Game rows (scrollable container) ─────────────────────────────────
        self.rows_container = tk.Frame(self.root, bg=BG)
        self.rows_container.pack(padx=18, fill="x")
        self._build_game_rows()

        # ── Log ───────────────────────────────────────────────────────────────
        tk.Label(self.root, text="  Activity log", bg=BG, fg=DIM,
                 font=("Helvetica", 8)).pack(anchor="w", padx=18, pady=(10, 2))

        self.log = scrolledtext.ScrolledText(
            self.root, height=8, bg="#090915", fg=FG,
            font=("Courier", 8), relief="flat", bd=0,
            wrap="word", state="disabled", insertbackground=FG)
        self.log.pack(padx=18, pady=(0, 14), fill="x")
        self.log.tag_config("ts",   foreground=DIM)
        self.log.tag_config("info", foreground=D_CHK)
        self.log.tag_config("ok",   foreground=D_YES)
        self.log.tag_config("warn", foreground=D_LIM)
        self.log.tag_config("err",  foreground=D_ERR)
        self.log.tag_config("dim",  foreground="#33334a")

        self.root.update_idletasks()

    # ─────────────────────────────────────────────────────────────────────────
    # STARTUP GAME SELECTOR
    # ─────────────────────────────────────────────────────────────────────────

    def _show_game_selector(self):
        """
        Startup dialog — pick which games to track this session.
        Organized by console with Select All / None per section.
        Custom games already in games.json are shown at the bottom.
        """
        dlg = tk.Toplevel(self.root)
        dlg.title("Select Games to Track")
        dlg.configure(bg=BG)
        dlg.resizable(False, True)
        dlg.grab_set()

        self.root.update_idletasks()
        # Centre over main window
        x = self.root.winfo_x() + self.root.winfo_width()  // 2 - 240
        y = max(0, self.root.winfo_y() - 20)
        dlg.geometry(f"480x680+{x}+{y}")

        # ── Header ────────────────────────────────────────────────────────────
        tk.Label(dlg, text="🎮  Which games do you want to track?",
                 bg=BG, fg=FG, font=("Helvetica", 13, "bold")).pack(
                 anchor="w", padx=18, pady=(16, 2))
        tk.Label(dlg,
                 text="Enter your location, pick your games, and hit Start.",
                 bg=BG, fg=DIM, font=("Helvetica", 9),
                 justify="left").pack(anchor="w", padx=18, pady=(0, 10))

        # ── Zip + Radius row ──────────────────────────────────────────────────
        loc_frame = tk.Frame(dlg, bg=CARD, highlightbackground=EDGE,
                             highlightthickness=1)
        loc_frame.pack(fill="x", padx=18, pady=(0, 12))

        loc_inner = tk.Frame(loc_frame, bg=CARD)
        loc_inner.pack(fill="x", padx=12, pady=10)

        # Zip label + entry
        tk.Label(loc_inner, text="📍  Your Zip Code", bg=CARD, fg=DIM,
                 font=("Helvetica", 9)).pack(anchor="w")
        zip_var = tk.StringVar(value=self.zip_code if self.zip_code != ZIP_CODE else "")
        zip_entry = tk.Entry(loc_inner, textvariable=zip_var, bg=BG, fg=FG,
                             insertbackground=FG, relief="flat",
                             font=("Helvetica", 14, "bold"), width=12)
        zip_entry.pack(anchor="w", pady=(2, 0))

        # Divider
        tk.Frame(loc_inner, bg=EDGE, height=1).pack(fill="x", pady=8)

        # Radius label + radio buttons
        tk.Label(loc_inner, text="🔍  Search Radius", bg=CARD, fg=DIM,
                 font=("Helvetica", 9)).pack(anchor="w")
        radius_var = tk.StringVar(value=str(self.radius_mi))
        rad_row = tk.Frame(loc_inner, bg=CARD)
        rad_row.pack(anchor="w", pady=(4, 0))
        for mi in ["15", "25", "50", "100"]:
            tk.Radiobutton(rad_row, text=f"{mi} mi", variable=radius_var, value=mi,
                           bg=CARD, fg=FG, selectcolor=BG, activebackground=CARD,
                           activeforeground=FG, font=("Helvetica", 10),
                           cursor="hand2").pack(side="left", padx=(0, 14))

        # ── Scrollable content ────────────────────────────────────────────────
        outer = tk.Frame(dlg, bg=BG)
        outer.pack(fill="both", expand=True, padx=18, pady=(0, 6))

        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb     = tk.Scrollbar(outer, orient="vertical", command=canvas.yview,
                              bg=CARD, troughcolor=BG)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        content = tk.Frame(canvas, bg=BG)
        cw = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))

        def _wheel(e):  canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _wheel)
        dlg.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # Build checkvar dict keyed by game id
        check_vars = {}

        # Previously selected ids (from runtime_games) — pre-tick these
        prev_ids = {g.get("id") for g in self.runtime_games}

        def add_section(title, games):
            # Section header row with Select All / None buttons
            hdr = tk.Frame(content, bg=BG)
            hdr.pack(fill="x", pady=(10, 2))
            # Colored left bar per console
            console_colors = {
                "Game Boy": "#557755",
                "Game Boy Advance": "#8855ee",
                "Nintendo DS": "#cc6600",
                "Nintendo 3DS": "#0055bb",
                "Nintendo Switch": "#e4000f",
                "Nintendo Switch 2": "#cc0033",
                "Custom": "#445566",
            }
            bar_color = console_colors.get(title, "#445566")
            tk.Frame(hdr, width=4, bg=bar_color).pack(side="left", fill="y", padx=(0, 8))
            tk.Label(hdr, text=title.upper(), bg=BG, fg=bar_color,
                     font=("Helvetica", 9, "bold")).pack(side="left")

            # Select All / None tiny buttons
            all_btn = tk.Label(hdr, text="all", bg=BG, fg=DIM,
                               font=("Helvetica", 8), cursor="hand2")
            all_btn.pack(side="right", padx=(0, 4))
            none_btn = tk.Label(hdr, text="none", bg=BG, fg=DIM,
                                font=("Helvetica", 8), cursor="hand2")
            none_btn.pack(side="right", padx=(0, 6))

            gids = [g["id"] for g in games if g["id"] in check_vars]

            all_btn.bind("<Button-1>",  lambda e, ids=gids: [check_vars[i].set(True)  for i in ids])
            none_btn.bind("<Button-1>", lambda e, ids=gids: [check_vars[i].set(False) for i in ids])

            # Game rows
            for g in games:
                gid = g["id"]
                var = check_vars.get(gid)
                if var is None:
                    continue
                row = tk.Frame(content, bg=CARD,
                               highlightbackground=EDGE, highlightthickness=1)
                row.pack(fill="x", pady=1)

                cb = tk.Checkbutton(row, variable=var,
                                    bg=CARD, activebackground=CARD,
                                    selectcolor="#223344",
                                    fg=FG, cursor="hand2")
                cb.pack(side="left", padx=(4, 0))

                sys_col = SYS_COLORS.get(g.get("sys", "Game"), SYS_COLORS["Game"])
                tk.Label(row, text=g.get("sys", "?"), bg=sys_col, fg="white",
                         font=("Helvetica", 7, "bold"), padx=3).pack(side="left", padx=(4, 6))

                name_lbl = tk.Label(row, text=g["name"], bg=CARD, fg=FG,
                                    font=("Helvetica", 10), anchor="w")
                name_lbl.pack(side="left", fill="x", expand=True)
                # Clicking the label also toggles
                name_lbl.bind("<Button-1>", lambda e, v=var: v.set(not v.get()))

        # Register vars and build catalog sections
        for g in GAME_CATALOG:
            check_vars[g["id"]] = tk.BooleanVar(value=False)

        # Group by console
        from collections import OrderedDict
        sections = OrderedDict()
        for g in GAME_CATALOG:
            sections.setdefault(g["console"], []).append(g)
        for console, games in sections.items():
            add_section(console, games)

        # Custom games (in runtime_games but not in GAME_CATALOG)
        catalog_ids = {g["id"] for g in GAME_CATALOG}
        custom = [g for g in self.runtime_games if g.get("id") not in catalog_ids]
        if custom:
            for g in custom:
                check_vars[g["id"]] = tk.BooleanVar(value=True)
            add_section("Custom", custom)

        # ── Bottom buttons ────────────────────────────────────────────────────
        sep = tk.Frame(dlg, bg=EDGE, height=1)
        sep.pack(fill="x", padx=18, pady=(4, 8))

        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(fill="x", padx=18, pady=(0, 14))

        count_lbl = tk.Label(btn_row, text="", bg=BG, fg=DIM, font=("Helvetica", 9))
        count_lbl.pack(side="left")

        def update_count(*_):
            n = sum(1 for v in check_vars.values() if v.get())
            count_lbl.config(text=f"{n} game{'s' if n != 1 else ''} selected")

        for v in check_vars.values():
            v.trace_add("write", update_count)
        update_count()

        def on_start():
            # Validate zip
            z = zip_var.get().strip()
            if not z:
                zip_entry.config(bg="#331111")
                zip_entry.focus_set()
                return
            zip_entry.config(bg=BG)

            selected_ids = {gid for gid, v in check_vars.items() if v.get()}
            if not selected_ids:
                count_lbl.config(text="Pick at least one game!", fg=D_ERR)
                return

            # Save zip + radius to settings
            self.zip_code  = z
            self.radius_mi = int(radius_var.get())
            self._save_settings()
            self.settings_lbl.config(text=self._settings_text())

            # Build runtime list: catalog games in catalog order, then custom
            selected = [g for g in GAME_CATALOG if g["id"] in selected_ids]
            selected += [g for g in custom       if g["id"] in selected_ids]
            self.runtime_games = selected
            save_games(self.runtime_games)
            self._rebuild_rows()
            dlg.destroy()
            self._start()

        tk.Button(btn_row, text="  Start Tracking  ", bg=ACCENT, fg="white",
                  activebackground="#cc2255", activeforeground="white",
                  relief="flat", padx=14, pady=6, cursor="hand2",
                  font=("Helvetica", 11, "bold"), command=on_start,
                  ).pack(side="right")

        tk.Button(btn_row, text="  + Add Custom Game  ", bg=EDGE, fg=FG,
                  activebackground="#333355", activeforeground=FG,
                  relief="flat", padx=10, pady=6, cursor="hand2",
                  font=("Helvetica", 9), command=lambda: [dlg.destroy(), self._manage_games()],
                  ).pack(side="right", padx=(0, 8))

        dlg.bind("<Return>", lambda e: on_start())

    # ─────────────────────────────────────────────────────────────────────────
    # SETTINGS — zip, radius, interval
    # ─────────────────────────────────────────────────────────────────────────

    def _settings_text(self):
        return f"Zip {self.zip_code}  ·  {self.radius_mi} mi  ·  every {self.interval_min} min"

    def _load_settings(self) -> dict:
        cfg = configparser.ConfigParser()
        if os.path.exists(CONFIG_FILE):
            cfg.read(CONFIG_FILE)
        return dict(cfg["settings"]) if "settings" in cfg else {}

    def _save_settings(self):
        cfg = configparser.ConfigParser()
        if os.path.exists(CONFIG_FILE):
            cfg.read(CONFIG_FILE)
        cfg["settings"] = {
            "zip_code":     self.zip_code,
            "radius_miles": str(self.radius_mi),
            "interval_min": str(self.interval_min),
        }
        with open(CONFIG_FILE, "w") as f:
            cfg.write(f)

    def _show_settings(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Settings")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()

        self.root.update_idletasks()
        x = self.root.winfo_x() + self.root.winfo_width()  // 2 - 175
        y = self.root.winfo_y() + self.root.winfo_height() // 2 - 140
        dlg.geometry(f"350x310+{x}+{y}")

        pad = {"padx": 20, "anchor": "w"}

        tk.Label(dlg, text="⚙  Settings", bg=BG, fg=FG,
                 font=("Helvetica", 13, "bold")).pack(**pad, pady=(18, 4))
        tk.Label(dlg, text="These are shared when you send the tool to a friend.",
                 bg=BG, fg=DIM, font=("Helvetica", 9),
                 wraplength=310, justify="left").pack(**pad, pady=(0, 14))

        # ── Zip code
        tk.Label(dlg, text="Zip Code / Postal Code", bg=BG, fg=FG,
                 font=("Helvetica", 10)).pack(**pad)
        zip_var = tk.StringVar(value=self.zip_code)
        zip_entry = tk.Entry(dlg, textvariable=zip_var, bg=CARD, fg=FG,
                             insertbackground=FG, relief="flat",
                             font=("Helvetica", 12), width=14)
        zip_entry.pack(padx=20, anchor="w", pady=(2, 12))

        # ── Radius
        tk.Label(dlg, text="Search Radius (miles)", bg=BG, fg=FG,
                 font=("Helvetica", 10)).pack(**pad)
        radius_var = tk.StringVar(value=str(self.radius_mi))
        radius_frame = tk.Frame(dlg, bg=BG)
        radius_frame.pack(padx=20, anchor="w", pady=(2, 12))
        for val in ["15", "25", "50", "100"]:
            tk.Radiobutton(
                radius_frame, text=f"{val} mi", variable=radius_var, value=val,
                bg=BG, fg=FG, selectcolor=CARD, activebackground=BG,
                activeforeground=FG, font=("Helvetica", 10),
            ).pack(side="left", padx=(0, 12))

        # ── Interval
        tk.Label(dlg, text="Check Interval (minutes)", bg=BG, fg=FG,
                 font=("Helvetica", 10)).pack(**pad)
        interval_var = tk.StringVar(value=str(self.interval_min))
        interval_frame = tk.Frame(dlg, bg=BG)
        interval_frame.pack(padx=20, anchor="w", pady=(2, 16))
        for val in ["30", "60", "90", "120"]:
            tk.Radiobutton(
                interval_frame, text=f"{val}m", variable=interval_var, value=val,
                bg=BG, fg=FG, selectcolor=CARD, activebackground=BG,
                activeforeground=FG, font=("Helvetica", 10),
            ).pack(side="left", padx=(0, 10))

        # ── Buttons
        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(0, 16))

        def on_save():
            z = zip_var.get().strip()
            if not z:
                zip_entry.config(bg="#331111")
                return
            self.zip_code     = z
            self.radius_mi    = int(radius_var.get())
            self.interval_min = int(interval_var.get())
            self._save_settings()
            self.settings_lbl.config(text=self._settings_text())
            self._log(f"Settings saved — Zip {self.zip_code}, {self.radius_mi}mi, "
                      f"every {self.interval_min}min", "ok")
            dlg.destroy()

        tk.Button(btn_row, text="  Save  ", bg=ACCENT, fg="white",
                  activebackground="#cc2255", activeforeground="white",
                  relief="flat", padx=10, pady=5, cursor="hand2",
                  font=("Helvetica", 10, "bold"), command=on_save).pack(side="left")
        tk.Button(btn_row, text="  Cancel  ", bg=EDGE, fg=FG,
                  activebackground="#333355", activeforeground=FG,
                  relief="flat", padx=10, pady=5, cursor="hand2",
                  font=("Helvetica", 10), command=dlg.destroy).pack(side="left", padx=(8, 0))

        dlg.bind("<Return>", lambda e: on_save())
        zip_entry.focus_set()
        zip_entry.select_range(0, "end")

    # ─────────────────────────────────────────────────────────────────────────
    # GAME ROWS — build / rebuild
    # ─────────────────────────────────────────────────────────────────────────

    def _build_game_rows(self):
        """Compact list view — no cover art, one row per game."""
        self.dot_canvas  = []
        self.stat_labels = []
        self.time_labels = []
        self.det_labels  = []
        self.pulse_on    = []

        for idx, p in enumerate(self.runtime_games):
            url = p.get("url", "")
            def _open(event, u=url): webbrowser.open(u)

            sys_col = SYS_COLORS.get(p.get("sys", "Game"), SYS_COLORS["Game"])

            # ── Card (auto-height so detail line can expand it) ───────────────
            card = tk.Frame(self.rows_container, bg=CARD,
                            highlightbackground=EDGE, highlightthickness=1)
            card.pack(fill="x", pady=2)

            # Left colour accent bar
            accent = tk.Frame(card, width=4, bg=sys_col)
            accent.place(x=0, y=0, relheight=1)

            # ── Main row ──────────────────────────────────────────────────────
            row = tk.Frame(card, bg=CARD)
            row.pack(fill="x", padx=(12, 8), pady=6)

            # System badge
            sys_lbl = tk.Label(row, text=p.get("sys", "?"), bg=sys_col, fg="white",
                               font=("Helvetica", 8, "bold"), padx=5, pady=2)
            sys_lbl.pack(side="left", padx=(0, 10))

            # Game name (expands to fill space)
            name_lbl = tk.Label(row, text=p["name"], bg=CARD, fg=FG,
                                font=("Helvetica", 10, "bold"), anchor="w")
            name_lbl.pack(side="left", fill="x", expand=True)

            # Last-check time (right side)
            tl = tk.Label(row, text="", bg=CARD, fg=DIM,
                          font=("Helvetica", 8), anchor="e", width=15)
            tl.pack(side="right", padx=(6, 0))
            self.time_labels.append(tl)

            # Status text
            sl = tk.Label(row, text="Pending", bg=CARD, fg=DIM,
                          font=("Helvetica", 9, "bold"), width=12, anchor="e")
            sl.pack(side="right", padx=(4, 0))
            self.stat_labels.append(sl)

            # Status dot
            ds = 14
            cv = tk.Canvas(row, width=ds, height=ds, bg=CARD, highlightthickness=0)
            cv.pack(side="right", padx=(8, 2))
            cv.create_oval(2, 2, ds-2, ds-2, fill=D_PEND, outline="", tags="dot")
            self.dot_canvas.append(cv)
            self.pulse_on.append(False)

            # ── Detail line (store info, hidden until stock found) ────────────
            dl = tk.Label(card, text="", bg=CARD, fg=D_YES,
                          font=("Helvetica", 8), anchor="w", padx=16)
            # Not packed yet — appears below main row when stock is found
            self.det_labels.append(dl)

            # ── Click + hover ─────────────────────────────────────────────────
            all_w = [card, accent, row, sys_lbl, name_lbl, cv, sl, tl, dl]
            for w in all_w:
                w.bind("<Button-1>", _open)
                try: w.config(cursor="hand2")
                except Exception: pass

            def _hin(e, c=card): c.config(highlightbackground="#4466aa")
            def _hout(e, c=card): c.config(highlightbackground=EDGE)
            for w in all_w:
                w.bind("<Enter>", _hin)
                w.bind("<Leave>", _hout)

    def _rebuild_rows(self):
        """Destroy all game rows and rebuild from self.runtime_games."""
        for widget in self.rows_container.winfo_children():
            widget.destroy()
        self._build_game_rows()
        self.root.update_idletasks()

    # ─────────────────────────────────────────────────────────────────────────
    # MANAGE GAMES DIALOG
    # ─────────────────────────────────────────────────────────────────────────

    def _manage_games(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Manage Games")
        dlg.configure(bg=BG)
        dlg.resizable(False, True)
        dlg.grab_set()

        self.root.update_idletasks()
        x = self.root.winfo_x() + self.root.winfo_width()  // 2 - 220
        y = self.root.winfo_y() + 40
        dlg.geometry(f"440x620+{x}+{y}")

        # ── Header (fixed) ────────────────────────────────────────────────────
        tk.Label(dlg, text="⚙  Manage Games", bg=BG, fg=FG,
                 font=("Helvetica", 13, "bold")).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(dlg, text="Click ✕ to remove a game. Scroll if the list is long.",
                 bg=BG, fg=DIM, font=("Helvetica", 9)).pack(anchor="w", padx=18, pady=(0, 8))

        # ── Scrollable game list ──────────────────────────────────────────────
        list_outer = tk.Frame(dlg, bg=BG, height=220)
        list_outer.pack(fill="x", padx=18, pady=(0, 4))
        list_outer.pack_propagate(False)

        canvas   = tk.Canvas(list_outer, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(list_outer, orient="vertical", command=canvas.yview,
                                 bg=CARD, troughcolor=BG)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        list_frame = tk.Frame(canvas, bg=BG)
        cw = canvas.create_window((0, 0), window=list_frame, anchor="nw")

        def _on_frame_size(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_size(e):
            canvas.itemconfig(cw, width=e.width)
        list_frame.bind("<Configure>", _on_frame_size)
        canvas.bind("<Configure>", _on_canvas_size)

        # Mouse-wheel scroll
        def _on_wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_wheel)
        dlg.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        def refresh_list():
            for w in list_frame.winfo_children():
                w.destroy()
            for i, p in enumerate(self.runtime_games):
                row = tk.Frame(list_frame, bg=CARD, pady=5, padx=8,
                               highlightbackground=EDGE, highlightthickness=1)
                row.pack(fill="x", pady=2)
                sc = SYS_COLORS.get(p.get("sys", "Game"), SYS_COLORS["Game"])
                tk.Label(row, text=p.get("sys", "?"), bg=sc, fg="white",
                         font=("Helvetica", 8, "bold"), padx=4).pack(side="left", padx=(0, 8))
                tk.Label(row, text=p["name"], bg=CARD, fg=FG,
                         font=("Helvetica", 10), anchor="w").pack(side="left", fill="x", expand=True)

                def remove(idx=i):
                    self.runtime_games.pop(idx)
                    save_games(self.runtime_games)
                    self._rebuild_rows()
                    refresh_list()

                tk.Button(row, text="  ✕  ", bg=EDGE, fg="#ff6666",
                          activebackground="#330000", activeforeground="#ff6666",
                          relief="flat", padx=4, pady=1, cursor="hand2",
                          font=("Helvetica", 10, "bold"), command=remove,
                          ).pack(side="right")

        refresh_list()

        # ── Separator ─────────────────────────────────────────────────────────
        tk.Frame(dlg, bg=EDGE, height=1).pack(fill="x", padx=18, pady=(8, 10))

        # ── Add section (always visible, never scrolls away) ──────────────────
        tk.Label(dlg, text="Add a game", bg=BG, fg=FG,
                 font=("Helvetica", 11, "bold")).pack(anchor="w", padx=18, pady=(0, 6))

        pad = {"padx": 18, "anchor": "w"}

        tk.Label(dlg, text="GameStop URL  (paste the product page URL)",
                 bg=BG, fg=DIM, font=("Helvetica", 9)).pack(**pad)
        url_var   = tk.StringVar()
        url_entry = tk.Entry(dlg, textvariable=url_var, bg=CARD, fg=FG,
                             insertbackground=FG, relief="flat",
                             font=("Helvetica", 10), width=46)
        url_entry.pack(padx=18, fill="x", pady=(2, 8))

        name_var = tk.StringVar()
        sys_var  = tk.StringVar(value="Game")

        def on_url_change(*_):
            u = url_var.get().strip()
            if "gamestop.com" in u:
                if not name_var.get():
                    name_var.set(name_from_url(u))
                sys_var.set(sys_from_url(u))

        url_var.trace_add("write", on_url_change)

        tk.Label(dlg, text="Name", bg=BG, fg=DIM, font=("Helvetica", 9)).pack(**pad)
        tk.Entry(dlg, textvariable=name_var, bg=CARD, fg=FG,
                 insertbackground=FG, relief="flat",
                 font=("Helvetica", 10), width=46).pack(padx=18, fill="x", pady=(2, 8))

        tk.Label(dlg, text="System", bg=BG, fg=DIM, font=("Helvetica", 9)).pack(**pad)
        sys_menu = tk.OptionMenu(dlg, sys_var, *SYS_COLORS.keys())
        sys_menu.config(bg=CARD, fg=FG, activebackground=EDGE, activeforeground=FG,
                        relief="flat", font=("Helvetica", 10), bd=0, highlightthickness=0)
        sys_menu.pack(padx=18, anchor="w", pady=(2, 12))

        def add_game():
            u    = url_var.get().strip()
            name = name_var.get().strip() or name_from_url(u)
            sys  = sys_var.get()
            gid  = id_from_url(u)
            bg_c = bg_from_sys(sys)
            if not u or "gamestop.com" not in u:
                url_entry.config(bg="#331111")
                return
            self.runtime_games.append({"name": name, "sys": sys,
                                       "bg": bg_c, "id": gid, "url": u})
            save_games(self.runtime_games)
            self._rebuild_rows()
            refresh_list()
            url_var.set("")
            name_var.set("")
            sys_var.set("Game")
            url_entry.config(bg=CARD)
            # Scroll to bottom of list so user sees the new game
            canvas.update_idletasks()
            canvas.yview_moveto(1.0)

        tk.Button(dlg, text="  + Add Game  ", bg=ACCENT, fg="white",
                  activebackground="#cc2255", activeforeground="white",
                  relief="flat", padx=10, pady=6, cursor="hand2",
                  font=("Helvetica", 10, "bold"), command=add_game,
                  ).pack(padx=18, anchor="w", pady=(0, 16))

        dlg.bind("<Return>", lambda e: add_game())
        url_entry.focus_set()

    # ─────────────────────────────────────────────────────────────────────────
    # LOGIN DIALOG
    # ─────────────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────
    # MENU DROPDOWN
    # ─────────────────────────────────────────────────────────────────────────

    def _show_menu(self):
        m = tk.Menu(self.root, tearoff=0,
                    bg=CARD, fg=FG, activebackground="#334466",
                    activeforeground=FG, relief="flat", bd=1)
        m.add_command(label="⚙  Manage Games",  command=self._manage_games)
        m.add_command(label="⚙  Settings",       command=self._show_settings)
        m.add_separator()
        m.add_command(label="🔊  Test Alert",     command=self._play_once)
        m.add_separator()
        if self.running:
            m.add_command(label="⏹  Stop Checker",  command=self._on_toggle)
        else:
            m.add_command(label="▶  Start Checker", command=self._on_toggle)
        # Show menu below the button
        self.root.update_idletasks()
        x = self.btn_menu.winfo_rootx()
        y = self.btn_menu.winfo_rooty() + self.btn_menu.winfo_height()
        m.post(x, y)

    # ─────────────────────────────────────────────────────────────────────────
    # PERSISTENT ALERT + SNOOZE
    # ─────────────────────────────────────────────────────────────────────────

    def _start_alert(self, game_name, detail):
        """Begin repeating alarm — keeps going until user hits Snooze."""
        self.alert_active = True
        self.alert_event.clear()
        # Show snooze banner
        self.snooze_lbl.config(
            text=f"  🎮  STOCK FOUND: {game_name}  —  {detail}")
        self.snooze_frame.pack(fill="x", padx=18, pady=(0, 6))
        self._pulse_snooze(True)
        threading.Thread(target=self._alert_loop, daemon=True).start()

    def _alert_loop(self):
        """Plays the chime, waits 20 s, repeats until snoozed."""
        while self.alert_active:
            self._chime()
            # Wait up to 20 s; alert_event.set() lets us break out early
            self.alert_event.wait(timeout=20)
            self.alert_event.clear()

    def _snooze_alert(self):
        self.alert_active = False
        self.alert_event.set()   # wake the loop so it exits immediately
        self.snooze_frame.pack_forget()

    def _pulse_snooze(self, bright):
        """Flash the snooze banner orange/dark-orange while alert is active."""
        if not self.alert_active:
            return
        self.snooze_frame.config(bg="#cc5500" if bright else "#882200")
        self.snooze_lbl.config(bg="#cc5500" if bright else "#882200")
        self.root.after(600, lambda: self._pulse_snooze(not bright))

    # ─────────────────────────────────────────────────────────────────────────
    # SOUND
    # ─────────────────────────────────────────────────────────────────────────

    def _chime(self):
        """4-note ascending chime — runs in a thread."""
        def play():
            if SOUND_OK:
                for freq, dur in [(523, 120), (659, 120), (784, 120), (1047, 350)]:
                    if not self.alert_active and not threading.current_thread().name == "test":
                        break
                    winsound.Beep(freq, dur)
        t = threading.Thread(target=play, daemon=True)
        t.start()

    def _play_once(self):
        """Test button — plays chime once."""
        def play():
            if SOUND_OK:
                for freq, dur in [(523, 120), (659, 120), (784, 120), (1047, 350)]:
                    winsound.Beep(freq, dur)
        threading.Thread(target=play, daemon=True, name="test").start()

    # ─────────────────────────────────────────────────────────────────────────
    # STATUS HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _set_dot(self, idx, color):
        self.dot_canvas[idx].itemconfig("dot", fill=color)

    def _set_status(self, idx, text, dot_color, fg):
        self.pulse_on[idx] = False
        self._set_dot(idx, dot_color)
        self.stat_labels[idx].config(text=text, fg=fg)

    def _start_pulse(self, idx):
        self.pulse_on[idx] = True
        self._pulse_step(idx, True)

    def _pulse_step(self, idx, bright):
        if not self.pulse_on[idx]:
            return
        self._set_dot(idx, D_CHK if bright else "#1a4466")
        self.root.after(450, lambda: self._pulse_step(idx, not bright))

    def _log(self, text, tag=""):
        ts = datetime.now().strftime("%I:%M:%S %p")
        self.log.config(state="normal")
        self.log.insert("end", f"[{ts}]  ", "ts")
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.config(state="disabled")

    # ─────────────────────────────────────────────────────────────────────────
    # COUNTDOWN + QUEUE POLL
    # ─────────────────────────────────────────────────────────────────────────

    def _tick(self):
        if self.next_ts is not None:
            rem = max(0, int(self.next_ts - time.time()))
            m, s = divmod(rem, 60)
            self.cd_lbl.config(text=f"Next: {m:02d}:{s:02d}")
        self.root.after(1000, self._tick)

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                t   = msg.get("type")

                if t == "log":
                    self._log(msg["text"], msg.get("tag", ""))

                elif t == "status":
                    i  = msg["idx"]
                    s  = msg["status"]
                    ts = msg.get("ts", "")
                    dt = msg.get("detail", "")

                    if s == "checking":
                        self.stat_labels[i].config(text="Checking…", fg=D_CHK)
                        self._start_pulse(i)
                        self.det_labels[i].config(text="")
                        self.det_labels[i].pack_forget()
                    elif s == "in_stock":
                        self._set_status(i, "In Stock  ✓", D_YES, D_YES)
                        self.det_labels[i].config(text=dt, fg=D_YES)
                        self.det_labels[i].pack(fill="x", pady=(0, 4))
                        self.time_labels[i].config(text=ts)
                    elif s == "limited":
                        self._set_status(i, "Limited Stock", D_LIM, D_LIM)
                        self.det_labels[i].config(text=dt, fg=D_LIM)
                        self.det_labels[i].pack(fill="x", pady=(0, 4))
                        self.time_labels[i].config(text=ts)
                    elif s == "no_stock":
                        self._set_status(i, "No Stock", D_NO, D_NO)
                        self.det_labels[i].config(text="")
                        self.det_labels[i].pack_forget()
                        self.time_labels[i].config(text=ts)
                    elif s == "error":
                        self._set_status(i, "Error", D_ERR, D_ERR)
                        self.time_labels[i].config(text=ts)

                elif t == "alert":
                    self._start_alert(msg["game"], msg["detail"])

        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    # ─────────────────────────────────────────────────────────────────────────
    # BUTTON HANDLERS
    # ─────────────────────────────────────────────────────────────────────────

    def _on_toggle(self):
        if self.running:
            self.running = False
            pass  # menu updates dynamically
            self.next_ts = None
            self.cd_lbl.config(text="Next: —")
            self._log("Checker paused.", "dim")
        else:
            self._start()

    def _on_now(self):
        if not self.running:
            self._start()
        else:
            self.next_ts = time.time()

    # ─────────────────────────────────────────────────────────────────────────
    # START / BG THREAD
    # ─────────────────────────────────────────────────────────────────────────

    def _start(self):
        if self.running:
            return
        self.running = True
        pass  # menu updates dynamically
        self._log("Checker started.", "info")
        self.thread = threading.Thread(target=self._bg_thread, daemon=True)
        self.thread.start()

    def _bg_thread(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._bg_loop())
        self.loop.close()

    async def _bg_loop(self):
        # ── Random startup delay — don't hit the site the instant the app opens
        delay_secs = random.randint(STARTUP_DELAY_MIN * 60, STARTUP_DELAY_MAX * 60)
        self.next_ts = time.time() + delay_secs
        m, s = divmod(delay_secs, 60)
        self.q.put({"type": "log",
                    "text": f"First sweep in {m}m {s}s (randomised startup delay)",
                    "tag": "info"})
        while self.running and time.time() < self.next_ts:
            await asyncio.sleep(1)

        while self.running:
            await self._sweep()
            # Random ±5 min jitter on the hourly interval too
            jitter = random.randint(-300, 300)
            self.next_ts = time.time() + self.interval_min * 60 + jitter
            while self.running and time.time() < self.next_ts:
                await asyncio.sleep(1)

    # ─────────────────────────────────────────────────────────────────────────
    # SWEEP  (API-based — much faster + lower footprint than UI automation)
    # ─────────────────────────────────────────────────────────────────────────

    async def _sweep(self):
        self.q.put({"type": "log", "text": "── Starting sweep ──────────────", "tag": "info"})

        if _async_pw is None:
            self.q.put({"type": "log",
                        "text": "patchright/playwright not installed — run 1_SETUP.bat",
                        "tag": "err"})
            self.running = False
            return

        # Announce which engine we're using
        engine = "Patchright ✓ (stealth)" if PATCHRIGHT_OK else "Playwright (install patchright for better stealth)"
        self.q.put({"type": "log", "text": f"Engine: {engine}", "tag": "ok" if PATCHRIGHT_OK else "warn"})

        # Shuffle game order each sweep so timing pattern is never the same
        indices = list(range(len(self.runtime_games)))
        if SHUFFLE_ORDER:
            random.shuffle(indices)
            names = [self.runtime_games[i]["name"].split()[-1] for i in indices]
            self.q.put({"type": "log", "text": f"Order: {' → '.join(names)}", "tag": "dim"})

        async with _async_pw() as pw:
            # Use real Chrome if available — Chromium is a bot fingerprint giveaway
            try:
                browser = await pw.chromium.launch(
                    channel="chrome",   # real Chrome install
                    headless=HEADLESS)
                self.q.put({"type": "log", "text": "Using real Chrome ✓", "tag": "ok"})
            except Exception:
                # Chrome not installed — fall back to Chromium
                browser = await pw.chromium.launch(headless=HEADLESS)
                self.q.put({"type": "log",
                            "text": "Chrome not found — using Chromium (install Chrome for better stealth)",
                            "tag": "warn"})

            ctx = await browser.new_context(
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"),
                viewport={"width": random.randint(1260, 1400),
                          "height": random.randint(780, 900)})
            page = await ctx.new_page()

            # Get session cookies + CSRF token from first product page
            self.q.put({"type": "log", "text": "Getting session token…", "tag": "info"})
            csrf_token = await self._get_session(page, indices[0])
            if csrf_token:
                self.q.put({"type": "log", "text": "  Session ready ✓", "tag": "ok"})
            else:
                self.q.put({"type": "log",
                            "text": "  No CSRF token — will still attempt checks",
                            "tag": "warn"})

            # Check each game in shuffled order
            for loop_pos, i in enumerate(indices):
                if not self.running:
                    break

                product = self.runtime_games[i]
                self.q.put({"type": "status", "idx": i, "status": "checking"})

                try:
                    stores = await asyncio.wait_for(
                        self._check_api(page, i, product, csrf_token), timeout=30)
                except asyncio.TimeoutError:
                    stores = None
                    self.q.put({"type": "log",
                                "text": f"  API timed out for {product['name']}", "tag": "warn"})

                if stores is None:
                    self.q.put({"type": "log",
                                "text": f"  Falling back to UI for {product['name']}…",
                                "tag": "warn"})
                    try:
                        stores = await asyncio.wait_for(
                            self._check_ui(page, i, product), timeout=90)
                    except asyncio.TimeoutError:
                        stores = []
                        self.q.put({"type": "log",
                                    "text": f"  UI also timed out — {product['name']}",
                                    "tag": "err"})

                ts_str = datetime.now().strftime("%m/%d  %I:%M %p")

                if stores:
                    has_in = any(s["status"] == "In Stock" for s in stores)
                    detail = "  ·  ".join(
                        f"{s['store']} ({s['distance']})" for s in stores)
                    kind  = "in_stock" if has_in else "limited"
                    tag   = "ok" if has_in else "warn"
                    label = "In Stock" if has_in else "Limited Stock"
                    self.q.put({"type": "status", "idx": i, "status": kind,
                                "detail": detail, "ts": ts_str})
                    self.q.put({"type": "log",
                                "text": f"  ★ {label}: {product['name']} → {detail}",
                                "tag": tag})
                    self.q.put({"type": "alert", "game": product["name"], "detail": detail})
                    self._desktop_notify(f"🎮 {label}: {product['name']}", detail)
                else:
                    self.q.put({"type": "status", "idx": i,
                                "status": "no_stock", "ts": ts_str})
                    self.q.put({"type": "log",
                                "text": f"  No stock — {product['name']}", "tag": "dim"})

                # Random delay between games — wide range prevents pattern detection
                if loop_pos < len(indices) - 1 and self.running:
                    wait = random.randint(BETWEEN_GAMES_MIN, BETWEEN_GAMES_MAX)
                    self.q.put({"type": "log",
                                "text": f"  Waiting {wait}s before next…", "tag": "dim"})
                    await asyncio.sleep(wait)

            await browser.close()

        self.q.put({"type": "log", "text": "── Sweep complete ──────────────", "tag": "info"})

    # ─────────────────────────────────────────────────────────────────────────
    # GET SESSION / CSRF TOKEN
    # ─────────────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────
    # HUMAN-LIKE BROWSER HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    async def _human_pause(self, lo=0.4, hi=1.2):
        """Random pause — mimics hesitation between actions."""
        await asyncio.sleep(random.uniform(lo, hi))

    async def _human_scroll(self, page, amount=None):
        """Scroll the page a natural-looking random distance."""
        px = amount or random.randint(200, 500)
        await page.mouse.wheel(0, px)
        await self._human_pause(0.3, 0.8)

    async def _human_move(self, page, locator):
        """Move mouse to element slowly before interacting."""
        try:
            box = await locator.bounding_box()
            if box:
                # Move to a random point inside the element
                tx = box["x"] + box["width"]  * random.uniform(0.2, 0.8)
                ty = box["y"] + box["height"] * random.uniform(0.2, 0.8)
                await page.mouse.move(tx, ty, steps=random.randint(8, 20))
                await self._human_pause(0.15, 0.45)
        except Exception:
            pass

    async def _human_click(self, page, locator):
        """Scroll into view → move mouse → pause → click."""
        await locator.scroll_into_view_if_needed()
        await self._human_pause(0.3, 0.7)
        await self._human_move(page, locator)
        await locator.click()
        await self._human_pause(0.4, 0.9)

    async def _human_type(self, page, locator, text):
        """Click field, clear it, then type one character at a time."""
        await self._human_click(page, locator)
        await locator.clear()
        await self._human_pause(0.2, 0.5)
        for char in text:
            await locator.type(char, delay=random.randint(60, 180))
        await self._human_pause(0.3, 0.7)

    async def _wait_for_cloudflare(self, page, log_fn, max_wait=20):
        """
        Wait up to max_wait seconds for Cloudflare to auto-solve.
        Scrolls and moves the mouse occasionally to look human.
        Returns True if page is clear, False if still blocked.
        """
        for i in range(max_wait):
            title = await page.title()
            if "just a moment" not in title.lower() and "captcha" not in title.lower():
                if i > 0:
                    log_fn("Cloudflare resolved ✓", "ok")
                return True
            if i == 0:
                log_fn("Cloudflare challenge — waiting…", "warn")
            # Occasional idle mouse movement so we don't look like a frozen bot
            if i % 4 == 2:
                try:
                    vp = page.viewport_size or {"width": 1280, "height": 800}
                    await page.mouse.move(
                        random.randint(100, vp["width"]  - 100),
                        random.randint(100, vp["height"] - 100),
                        steps=random.randint(5, 12))
                except Exception:
                    pass
            await asyncio.sleep(1)
        log_fn(f"Still blocked after {max_wait}s — skipping", "err")
        return False

    # ─────────────────────────────────────────────────────────────────────────
    # SESSION WARM-UP
    # ─────────────────────────────────────────────────────────────────────────

    async def _get_session(self, page, first_idx: int):
        """Browse the first product page naturally to warm up session + get CSRF."""
        product = self.runtime_games[first_idx] if self.runtime_games else None
        if not product:
            return None
        def log(msg, tag=""):
            self.q.put({"type": "log", "text": f"  {msg}", "tag": tag})
        try:
            try:
                await page.goto(product["url"], wait_until="networkidle", timeout=35_000)
            except Exception:
                pass

            title = await page.title()
            if "just a moment" in title.lower() or "captcha" in title.lower():
                ok = await self._wait_for_cloudflare(page, log, max_wait=20)
                if not ok:
                    return None

            # Browse naturally before extracting token
            await self._human_pause(1.5, 3.0)
            await self._human_scroll(page, random.randint(300, 600))
            await self._human_pause(0.8, 2.0)
            await self._human_scroll(page, random.randint(-150, -50))
            await self._human_pause(1.0, 2.5)

            token = await page.evaluate("""() => {
                const m = document.querySelector('meta[name="csrf-token"]');
                if (m) return m.getAttribute('content');
                const inp = document.querySelector('input[name="csrf_token"]');
                if (inp) return inp.value;
                if (window.pageContext && window.pageContext.csrf) return window.pageContext.csrf;
                if (window.CSRF_TOKEN) return window.CSRF_TOKEN;
                const b = document.querySelector('[data-csrf]');
                if (b) return b.getAttribute('data-csrf');
                return null;
            }""")
            if not token:
                try:
                    cookies = await page.context.cookies()
                    for c in cookies:
                        if 'csrf' in c['name'].lower():
                            token = c['value']
                            break
                except Exception:
                    pass
            return token or None
        except Exception as e:
            self.q.put({"type": "log", "text": f"  Session error: {e}", "tag": "err"})
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # API CHECK  (fast — one POST request per game)
    # ─────────────────────────────────────────────────────────────────────────

    async def _check_api(self, page, idx, product, csrf_token):
        """
        Call GameStop's internal Stores-FindStores endpoint using the browser's
        own fetch() — this inherits the session cookies so it never gets a 403.
        Returns list of store dicts, empty list if none, or None if the call failed.
        """
        name = product["name"]
        pid  = product["id"]

        self.q.put({"type": "log", "text": f"  [{name}] API call (browser-based)…"})

        # Build the query string
        params = (
            f"?hasCondition=true"
            f"&hasVariantsAvailableForLookup=false"
            f"&hasVariantsAvailableForPickup=true"
            f"&source=pdp&showMap=false"
            f"&products={pid}:1"
            f"&selectedStore=undefined"
            f"&postalCode={self.zip_code}"
            f"&radius={self.radius_mi}"
        )
        api_url = (
            "https://www.gamestop.com/on/demandware.store/Sites-gamestop-us-Site/"
            f"default/Stores-FindStores{params}"
        )

        try:
            # Run fetch() inside the browser — uses GameStop's session cookies
            result = await page.evaluate("""async (url) => {
                try {
                    const r = await fetch(url, {
                        credentials: 'include',
                        headers: {
                            'Accept': 'text/html, application/json, */*',
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    });
                    return {status: r.status, text: await r.text()};
                } catch(e) {
                    return {status: 0, error: e.message};
                }
            }""", api_url)

            status = result.get("status", 0)
            if status != 200:
                self.q.put({"type": "log",
                            "text": f"  [{name}] API returned {status} — trying UI fallback",
                            "tag": "warn"})
                return None  # signal to try UI fallback

            text = result.get("text", "")

            # Try JSON parse first
            try:
                import json as _json
                data   = _json.loads(text)
                stores = data.get("stores", [])
                if not stores:
                    self.q.put({"type": "log",
                                "text": f"  [{name}] No stores in radius"})
                    return []
                results = []
                for s in stores:
                    store_name = (s.get("name") or s.get("storeDisplayName")
                                  or s.get("storeName") or "Unknown Store")
                    distance   = s.get("distance", "")
                    dist_str   = f"{distance} miles away" if distance else ""
                    inv = s.get("availability") or s.get("inventoryStatus") or ""
                    if isinstance(inv, dict):
                        inv = inv.get("status", "")
                    status_str = ("In Stock" if "instock" in str(inv).lower().replace(" ", "")
                                  else "Limited Stock")
                    results.append({"store": store_name, "status": status_str,
                                    "distance": dist_str})
                self.q.put({"type": "log",
                            "text": f"  [{name}] {len(results)} store(s) — API ✓", "tag": "ok"})
                return results
            except Exception:
                pass

            # HTML response — check for stock keywords
            tl = text.lower()
            if "no store" in tl or "no stores" in tl or "currently has inventory" in tl:
                self.q.put({"type": "log", "text": f"  [{name}] No stores in radius"})
                return []
            if "in stock" in tl or "limited stock" in tl or "pick up here" in tl:
                # Parse store names from HTML
                import re as _re
                store_names = _re.findall(
                    r'class="[^"]*store-name[^"]*"[^>]*>([^<]+)<', text)
                if not store_names:
                    store_names = ["Store found"]
                has_in = "in stock" in tl and "limited" not in tl
                status_str = "In Stock" if has_in else "Limited Stock"
                results = [{"store": s.strip(), "status": status_str,
                            "distance": ""} for s in store_names[:3]]
                self.q.put({"type": "log",
                            "text": f"  [{name}] {len(results)} store(s) — API (HTML) ✓",
                            "tag": "ok"})
                return results

            # Can't parse — fall through to UI
            return None

        except Exception as e:
            self.q.put({"type": "log", "text": f"  [{name}] API error: {e}", "tag": "warn"})
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # UI FALLBACK CHECK  (original method, used only when API fails)
    # ─────────────────────────────────────────────────────────────────────────

    async def _check_ui(self, page, idx, product):
        """
        Full UI automation with human-like pacing.
        Every action has natural mouse movement, realistic typing speed,
        and random pauses so it looks like a person browsing slowly.
        """
        stores = []
        name = product["name"]
        def log(msg, tag=""):
            self.q.put({"type": "log", "text": f"  [{name}] {msg}", "tag": tag})

        try:
            # ── 1. Load the page ─────────────────────────────────────────────
            log("Loading page…")
            try:
                await page.goto(product["url"], wait_until="networkidle", timeout=35_000)
            except Exception:
                pass
            await self._human_pause(2.0, 4.0)

            # ── 2. Handle Cloudflare ──────────────────────────────────────────
            title = await page.title()
            if "just a moment" in title.lower() or "captcha" in title.lower():
                ok = await self._wait_for_cloudflare(page, log, max_wait=20)
                if not ok:
                    return []

            if "access denied" in title.lower():
                log("Access denied — skipping", "err")
                return []

            # ── 3. Browse naturally before touching anything ──────────────────
            log("Browsing page…")
            await self._human_scroll(page, random.randint(250, 450))
            await self._human_pause(1.0, 2.5)
            await self._human_scroll(page, random.randint(100, 300))
            await self._human_pause(0.8, 2.0)
            # Scroll back up a bit so the store button is visible
            await self._human_scroll(page, random.randint(-200, -100))
            await self._human_pause(1.5, 3.0)

            # ── 4. Find and click store availability button ───────────────────
            log("Looking for store button…")
            opened = False
            for sel in [
                "button:has-text('Check Store Availability')",
                "button:has-text('Pick Up in Store')",
                "button:has-text('Find in Store')",
                "button:has-text('Pick up')",
                "button:has-text('Check availability')",
                "[class*='store-availability'] button",
            ]:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=3_000):
                        log("Found store button — clicking…")
                        await self._human_click(page, btn)
                        opened = True
                        break
                except Exception:
                    continue

            if not opened:
                log("Store button not found", "err")
                return []

            # ── 5. Wait for modal to fully appear ─────────────────────────────
            await self._human_pause(2.5, 4.0)

            # ── 6. Type zip code one character at a time ─────────────────────
            log(f"Typing zip {self.zip_code}…")
            zip_filled = False
            for sel in ["input[placeholder*='ZIP']", "input[placeholder*='Zip']",
                        "input[placeholder*='City']", "#zipCodeField"]:
                try:
                    inp = page.locator(sel).first
                    if await inp.is_visible(timeout=3_000):
                        await self._human_type(page, inp, self.zip_code)
                        zip_filled = True
                        break
                except Exception:
                    continue

            if not zip_filled:
                log("Could not find zip input", "err")
                return []

            # Pause after typing — let any autocomplete dropdown appear
            await self._human_pause(1.2, 2.0)

            # Dismiss autocomplete dropdown with Down + Enter if it appeared
            try:
                dropdown_sels = [
                    "[class*='autocomplete'] li",
                    "[class*='suggestion']",
                    "[class*='dropdown'] li",
                    "[role='option']",
                    "[role='listbox'] li",
                ]
                for dsel in dropdown_sels:
                    if await page.locator(dsel).first.is_visible(timeout=1_000):
                        log("Autocomplete dropdown found — pressing Down + Enter")
                        await page.keyboard.press("ArrowDown")
                        await self._human_pause(0.4, 0.7)
                        await page.keyboard.press("Enter")
                        await self._human_pause(0.6, 1.0)
                        break
            except Exception:
                pass

            await self._human_pause(0.8, 1.5)

            # ── 7. Set radius dropdown ────────────────────────────────────────
            log(f"Setting radius to {self.radius_mi} miles…")
            for sel in ["select:near(label:has-text('Radius'))",
                        "select:near(text='RADIUS')", ".store-radius-select",
                        "select[name*='radius']"]:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=2_000):
                        await self._human_move(page, el)
                        await el.select_option(label=f"{self.radius_mi} Miles")
                        await self._human_pause(0.6, 1.2)
                        break
                except Exception:
                    continue

            await self._human_pause(1.0, 2.0)

            # ── 8. Click Search ───────────────────────────────────────────────
            log("Clicking Search…")
            for sel in ["button:has-text('Search')", "button:has-text('SEARCH')"]:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=3_000):
                        await self._human_click(page, btn)
                        break
                except Exception:
                    continue

            # ── 9. Wait for results ───────────────────────────────────────────
            log("Waiting for results…")
            await self._human_pause(4.0, 6.0)

            # ── 9a. Dismiss "nickname" / "save location" dialog if it appears ─
            # GameStop sometimes asks you to save this location with a nickname
            try:
                nickname_sels = [
                    "button:has-text('No')",
                    "button:has-text('No Thanks')",
                    "button:has-text('No, thanks')",
                    "button:has-text('Skip')",
                    "button:has-text('Cancel')",
                    "[aria-label*='close' i]:visible",
                    "[class*='modal'] button:has-text('No')",
                    "[class*='dialog'] button:has-text('No')",
                ]
                for nsel in nickname_sels:
                    try:
                        nbtn = page.locator(nsel).first
                        if await nbtn.is_visible(timeout=1_500):
                            log("Nickname/save dialog found — dismissing")
                            await self._human_pause(0.4, 0.8)
                            await self._human_click(page, nbtn)
                            await self._human_pause(0.8, 1.5)
                            break
                    except Exception:
                        continue
            except Exception:
                pass

            # ── 10. Check for no-stock message ────────────────────────────────
            for phrase in ["Sorry, no store", "no store within", "currently has inventory"]:
                try:
                    if await page.locator(f"text={phrase}").first.is_visible(timeout=2_000):
                        log("No stores in range")
                        return []
                except Exception:
                    continue

            # ── 11. Parse store rows ──────────────────────────────────────────
            for rsel in [".store-result", ".store-list-item",
                         "[class*='StoreResult']", "[class*='store-item']"]:
                rows = page.locator(rsel)
                n = await rows.count()
                if not n:
                    continue
                for j in range(n):
                    row = rows.nth(j)
                    try:
                        nm = await row.locator(
                            "h3, h4, strong, .store-name, [class*='storeName']"
                        ).first.inner_text(timeout=1_000)
                    except Exception:
                        nm = f"Store #{j+1}"
                    status = None
                    try:
                        if await row.locator("text=In Stock").is_visible(timeout=500):
                            status = "In Stock"
                        elif await row.locator("text=Limited Stock").is_visible(timeout=500):
                            status = "Limited Stock"
                    except Exception:
                        pass
                    if not status:
                        continue
                    try:
                        dist = await row.locator(
                            "text=miles away").first.inner_text(timeout=500)
                    except Exception:
                        dist = ""
                    stores.append({"store": nm.strip(), "status": status,
                                   "distance": dist.strip()})
                if stores:
                    log(f"Found {len(stores)} store(s) ✓", "ok")
                break

            # Fallback badge scan
            if not stores:
                in_n  = await page.locator("text=In Stock").count()
                lim_n = await page.locator("text=Limited Stock").count()
                if in_n + lim_n:
                    stores.append({"store": "Store(s) found",
                                   "status": "In Stock" if in_n else "Limited Stock",
                                   "distance": "see gamestop.com"})
                    log("Stock detected (fallback scan) ✓", "ok")

        except Exception as e:
            log(f"UI error: {e}", "err")

        return stores

    # ─────────────────────────────────────────────────────────────────────────
    # GAMESTOP LOGIN
    # ─────────────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────
    # SINGLE PRODUCT CHECK
    # ─────────────────────────────────────────────────────────────────────────
    # DESKTOP NOTIFY
    # ─────────────────────────────────────────────────────────────────────────

    def _desktop_notify(self, title, body):
        try:
            from plyer import notification
            notification.notify(title=title, message=body,
                                app_name="GameStop Checker", timeout=20)
        except Exception:
            pass


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app  = App(root)
    root.mainloop()
