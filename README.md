# 🎮 Pokémon GameStop Stock Tracker

A desktop app that monitors GameStop store availability for Pokémon games and alerts you the moment one comes back in stock near you.

Built with Python + Patchright (stealth browser automation). Checks your local GameStop stores on a randomized schedule to avoid bot detection, plays a chime alert, and sends a desktop notification when stock is found.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?logo=windows)
![License](https://img.shields.io/badge/License-MIT-green)

---


> The app sitting in the corner of your screen, quietly watching.

| Startup — pick your games | Live tracking dashboard |
|---|---|
| Select from the full Pokémon catalog organized by console | Compact list with colored status dots and last-checked times |

---

## Features

- **Full Pokémon catalog** — every mainline game from Red/Blue through Legends: Z-A, organized by console (Game Boy → GBA → DS → 3DS → Switch → Switch 2)
- **Session game picker** — choose which games to watch each time you open the app, with Select All / None per console
- **Real store availability** — checks your local GameStop stores by zip code, not just "in stock online"
- **Configurable radius** — search 15, 25, 50, or 100 miles from your zip
- **Repeating audio alert** — a gentle 4-note chime that keeps playing every 20 seconds until you hit Snooze, so you won't miss it if you're away from your desk
- **Desktop notification** — pops up alongside the chime alert
- **Clickable rows** — click any game to open its GameStop product page directly in your browser
- **Stealth browser** — uses [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) (a patched Playwright build) with real Chrome to avoid Cloudflare bot detection
- **Human-like behaviour** — randomized check order, variable delays between games (25–75s), mouse movement, character-by-character typing, and natural page scrolling
- **Randomized timing** — 2–8 minute random startup delay, ±5 minute jitter on the hourly interval, so checks never land on a predictable schedule
- **Add custom games** — paste any GameStop product URL to track non-Pokémon games too
- **Settings dialog** — change zip, radius, and check interval without editing code
- **Sharable** — friends in other cities just change their zip in Settings

---

## Supported Games

| Console | Games |
|---|---|
| **Game Boy** | Red, Blue, Yellow, Gold, Silver, Crystal |
| **Game Boy Advance** | Ruby, Sapphire, Emerald, Fire Red, Leaf Green |
| **Nintendo DS** | Diamond, Pearl, Platinum, HeartGold, SoulSilver, Black, White, Black 2, White 2 |
| **Nintendo 3DS** | X, Y, Omega Ruby, Alpha Sapphire, Sun, Moon, Ultra Sun, Ultra Moon |
| **Nintendo Switch** | Let's Go Pikachu/Eevee, Sword, Shield, Brilliant Diamond, Shining Pearl, Legends: Arceus, Scarlet, Violet |
| **Nintendo Switch 2** | Legends: Z-A |

---

## Requirements

- Windows 10 or 11
- Python 3.10 or newer — download from [python.org](https://www.python.org/downloads/)
  - ⚠️ During install, check **"Add Python to PATH"**

---

## Installation

### First time only

1. Download this repo (green **Code** button → **Download ZIP**) and extract it anywhere
2. Double-click **`1_SETUP (run this first).bat`**

The setup script will:
- Install `patchright` and `Pillow` via pip
- Download and install a real Chrome browser for Patchright to use

This takes a few minutes. When it says **"Setup complete!"**, you're done.

### Every time after

Double-click **`2_RUN.bat`**

---

## Usage

### Startup
When the app opens, a game selector appears. Tick the games you want to track this session — use the **all** / **none** links to quickly select an entire console. Hit **Start Tracking**.

### Main window
Each game shows as a compact row:

```
▌ GBA  Pokémon Emerald    ●  No Stock     05/02  01:48 PM
▌ NDS  Pokémon Platinum   ●  In Stock ✓   05/02  01:49 PM
    └─ Desert Palms Power Center (7.4 miles away)
```

Click any row to open that game's GameStop page in your browser.

### Status dots
| Color | Meaning |
|---|---|
| 🔵 Pulsing blue | Currently checking |
| 🔴 Red | No stock found |
| 🟢 Green | **In Stock** |
| 🟡 Amber | Limited Stock |
| ⚫ Dark | Pending (not checked yet) |

### Menu button
The **☰ Menu** button in the top-right opens:
- **Manage Games** — add or remove games, paste any GameStop URL
- **Settings** — change zip code, radius, and check interval
- **Test Alert** — preview the chime sound before it surprises you
- **Multi Zip Code Mode** - Add checking for zip codes all around the country!
- **Stop / Start Checker**

### Snooze
When stock is found an orange flashing banner appears at the top of the window with the store name and distance. The chime repeats every 20 seconds. Hit **Snooze** to dismiss it.

---

## Configuration

All settings are saved to `gamestop_config.ini` next to the script and persist across restarts.

| Setting | Default | Description |
|---|---|---|
| Zip Code | — | Your zip or postal code |
| Radius | 50 miles | How far to search for stores |
| Check Interval | 60 min | How often to run a full sweep |

The randomisation values (startup delay, between-game delays, jitter) are constants at the top of `gamestop_checker_gui.py` if you want to adjust them:

```python
STARTUP_DELAY_MIN  = 2    # minutes
STARTUP_DELAY_MAX  = 8    # minutes
BETWEEN_GAMES_MIN  = 25   # seconds
BETWEEN_GAMES_MAX  = 75   # seconds
```

---

## Adding custom games

1. Open **☰ Menu → Manage Games**
2. Paste a GameStop product URL — the name and system auto-fill
3. Adjust the name or system badge if needed
4. Click **+ Add Game**

Games are saved to `games.json` next to the script.

---

## Sharing with friends

Just zip up the folder and send it. They run `1_SETUP.bat` once, then `2_RUN.bat`. They'll need to change the zip code in **☰ Menu → Settings** to their own location.

---

## How it avoids bot detection

GameStop uses Cloudflare, which is aggressive about blocking scrapers. This app uses several techniques to look like a real human:

- **Patchright** patches the CDP (Chrome DevTools Protocol) leaks that Cloudflare specifically looks for — the biggest giveaway that a browser is automated
- **Real Chrome** instead of Chromium (Cloudflare knows most users don't browse with Chromium)
- **Randomized game order** each sweep — never checks in the same order twice
- **Human mouse movement** — cursor moves to a random point inside each element over 8–20 smooth steps before clicking
- **Character-by-character typing** — zip code is typed one letter at a time with 60–180ms between each keystroke
- **Natural page browsing** — scrolls down and pauses before interacting with anything, mimicking reading the page
- **Cloudflare challenge patience** — waits up to 20 seconds for JS challenges to auto-solve, with occasional mouse movements during the wait
- **Wide random delays** — 25–75 seconds between games, ±5 minute jitter on the hourly interval

---

## Troubleshooting

**"playwright/patchright not installed" in the log**
→ Run `1_SETUP.bat` again

**Still seeing Cloudflare blocks in the log**
→ This is normal occasionally. The app retries on the next sweep. If it's blocking every single check, try increasing `BETWEEN_GAMES_MIN` and `BETWEEN_GAMES_MAX` in the script.

**The window looks broken on first launch**
→ Install Pillow by running `1_SETUP.bat` again

**"No store button found" for a game**
→ GameStop may have changed their page layout. Open an issue with the game name and I'll update the selectors.

**App not finding stock that I can see on the website**
→ The store availability modal uses a different API call than the main product page. Check that your zip code and radius in Settings are correct. If the issue persists, open an issue.

---

## Tech Stack

| Component | Library |
|---|---|
| GUI | `tkinter` (built into Python) |
| Browser automation | [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) |
| Audio alerts | `winsound` (built into Python on Windows) |
| Image processing | [Pillow](https://python-pillow.org/) |
| Async | `asyncio` |

---

## Disclaimer

This tool is for personal use only. It accesses publicly visible store availability information on GameStop's website, the same information you'd see if you visited the page yourself. Use it responsibly — the randomized delays and human-like behaviour are there for a reason. Don't reduce the check intervals dramatically or you risk getting your IP temporarily blocked by Cloudflare.

This project is not affiliated with, endorsed by, or connected to GameStop Corp. or The Pokémon Company in any way.

---

## Contributing

Pull requests are welcome. If a game URL changes, a selector breaks, or you want to add a new console, feel free to open a PR or an issue.

---

## License

MIT — do whatever you want with it, just don't blame me if you miss a restock.
