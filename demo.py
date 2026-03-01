#!/usr/bin/env python3
"""
GAPI Interactive Demo
=====================
Showcases GAPI functionality without requiring Steam credentials or a
database connection.  Run it with:

    python3 demo.py            # full showcase
    python3 demo.py --quiet    # minimal output (good for CI)

The demo exercises:
  • Game-picker filters (random, unplayed, playtime ranges, genre)
  • Favourites management
  • Multi-user common-game detection
  • Library statistics
  • Export / import of pick history
  • Achievement sync results (mocked)
"""

import argparse
import json
import os
import random
import sys
import tempfile
import time

# ---------------------------------------------------------------------------
# Optional colours (graceful fallback if colorama isn't installed)
# ---------------------------------------------------------------------------
try:
    from colorama import Fore, Style, init as _colorama_init
    _colorama_init(autoreset=True)
    _GREEN  = Fore.GREEN
    _CYAN   = Fore.CYAN
    _YELLOW = Fore.YELLOW
    _BLUE   = Fore.BLUE
    _MAGENTA = Fore.MAGENTA
    _RESET  = Style.RESET_ALL
except ImportError:
    _GREEN = _CYAN = _YELLOW = _BLUE = _MAGENTA = _RESET = ''


# ---------------------------------------------------------------------------
# Rich demo dataset (20 games, mix of platforms / genres / playtime)
# ---------------------------------------------------------------------------
DEMO_GAMES = [
    {"appid": 620,    "name": "Portal 2",                       "playtime_forever": 2720,  "platform": "steam", "genres": ["Puzzle", "Co-op"]},
    {"appid": 440,    "name": "Team Fortress 2",                "playtime_forever": 15430, "platform": "steam", "genres": ["Action", "Multiplayer"]},
    {"appid": 570,    "name": "Dota 2",                         "playtime_forever": 0,     "platform": "steam", "genres": ["Strategy", "MOBA"]},
    {"appid": 730,    "name": "Counter-Strike 2",               "playtime_forever": 4560,  "platform": "steam", "genres": ["Action", "FPS"]},
    {"appid": 72850,  "name": "The Elder Scrolls V: Skyrim",    "playtime_forever": 890,   "platform": "steam", "genres": ["RPG", "Open World"]},
    {"appid": 8930,   "name": "Sid Meier's Civilization V",     "playtime_forever": 0,     "platform": "steam", "genres": ["Strategy", "Turn-based"]},
    {"appid": 292030, "name": "The Witcher 3: Wild Hunt",       "playtime_forever": 85,    "platform": "steam", "genres": ["RPG", "Action"]},
    {"appid": 4000,   "name": "Garry's Mod",                    "playtime_forever": 320,   "platform": "steam", "genres": ["Sandbox"]},
    {"appid": 1091500, "name": "Cyberpunk 2077",                "playtime_forever": 1200,  "platform": "steam", "genres": ["RPG", "Open World"]},
    {"appid": 1245620, "name": "ELDEN RING",                    "playtime_forever": 0,     "platform": "steam", "genres": ["RPG", "Action"]},
    {"appid": 1172470, "name": "Apex Legends",                  "playtime_forever": 3400,  "platform": "steam", "genres": ["Battle Royale", "FPS"]},
    {"appid": 381210,  "name": "Dead by Daylight",              "playtime_forever": 110,   "platform": "steam", "genres": ["Horror", "Multiplayer"]},
    {"appid": 1222670, "name": "The Binding of Isaac: Repentance", "playtime_forever": 680, "platform": "steam", "genres": ["Roguelike", "Indie"]},
    {"appid": 1085660, "name": "Destiny 2",                     "playtime_forever": 0,     "platform": "steam", "genres": ["FPS", "RPG", "Multiplayer"]},
    {"appid": 252490,  "name": "Rust",                          "playtime_forever": 2100,  "platform": "steam", "genres": ["Survival", "Multiplayer"]},
    # Epic Games store entries (no Steam appid — use negative sentinel)
    {"appid": -1,      "name": "Fortnite",                      "playtime_forever": 500,   "platform": "epic",  "genres": ["Battle Royale"]},
    {"appid": -2,      "name": "Rocket League",                 "playtime_forever": 0,     "platform": "epic",  "genres": ["Sports", "Multiplayer"]},
    # Titles owned by a second demo user (for multi-user section)
    {"appid": 620,    "name": "Portal 2",                       "playtime_forever": 900,   "platform": "steam", "genres": ["Puzzle", "Co-op"]},
    {"appid": 440,    "name": "Team Fortress 2",                "playtime_forever": 7200,  "platform": "steam", "genres": ["Action", "Multiplayer"]},
    {"appid": 292030, "name": "The Witcher 3: Wild Hunt",       "playtime_forever": 40,    "platform": "steam", "genres": ["RPG", "Action"]},
]

# Subset owned by "demo_user"
USER1_GAMES = DEMO_GAMES[:16]
# Subset owned by "demo_friend"
USER2_GAMES = DEMO_GAMES[17:]  # Portal 2, TF2, Witcher 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sep(char: str = "─", width: int = 60) -> str:
    return char * width


def _header(text: str) -> None:
    print()
    print(_CYAN + _sep("═") + _RESET)
    print(_CYAN + f"  {text}" + _RESET)
    print(_CYAN + _sep("═") + _RESET)


def _section(text: str) -> None:
    print()
    print(_YELLOW + _sep("─") + _RESET)
    print(_YELLOW + f"  {text}" + _RESET)
    print(_YELLOW + _sep("─") + _RESET)


def _ok(msg: str) -> None:
    print(_GREEN + f"  ✓ {msg}" + _RESET)


def _info(msg: str) -> None:
    print(f"    {msg}")


def _pause(quiet: bool, seconds: float = 0.4) -> None:
    if not quiet:
        time.sleep(seconds)


def _pick(games: list, label: str) -> None:
    """Mimic the picker selecting a random game."""
    if not games:
        print(f"    (no games match the '{label}' filter)")
        return
    chosen = random.choice(games)
    print(_BLUE + f"  🎮 [{label}] → {chosen['name']}" + _RESET)
    hours = chosen["playtime_forever"] // 60
    mins  = chosen["playtime_forever"] % 60
    print(f"       Playtime: {hours}h {mins}m  |  Platform: {chosen['platform'].capitalize()}")


# ---------------------------------------------------------------------------
# Demo sections
# ---------------------------------------------------------------------------

def demo_filters(games: list, quiet: bool) -> None:
    _section("🎯 Game Picker — Filter Showcase")
    _pause(quiet)

    all_g    = games
    unplayed = [g for g in games if g["playtime_forever"] == 0]
    barely   = [g for g in games if 0 < g["playtime_forever"] < 120]  # < 2 h
    well     = [g for g in games if g["playtime_forever"] >= 600]      # ≥ 10 h
    rpg      = [g for g in games if "RPG" in g.get("genres", [])]
    coop     = [g for g in games if "Co-op" in g.get("genres", []) or
                                    "Multiplayer" in g.get("genres", [])]

    _pick(all_g,    "Any game")
    _pick(unplayed, "Unplayed")
    _pick(barely,   "Barely played (< 2 h)")
    _pick(well,     "Well-played (≥ 10 h)")
    _pick(rpg,      "Genre: RPG")
    _pick(coop,     "Co-op / Multiplayer")


def demo_favourites(games: list, quiet: bool) -> None:
    _section("⭐ Favourites Management")
    _pause(quiet)

    favs = [g["name"] for g in games[:3]]
    for name in favs:
        _ok(f"Marked as favourite: {name}")

    chosen = random.choice(favs)
    print(_BLUE + f"  🎮 [Favourites] → {chosen}" + _RESET)


def demo_multiuser(quiet: bool) -> None:
    _section("👥 Multi-User — Common Games")
    _pause(quiet)

    u1_names = {g["name"] for g in USER1_GAMES}
    u2_names = {g["name"] for g in USER2_GAMES}
    common   = sorted(u1_names & u2_names)

    _info(f"demo_user   owns {len(u1_names)} unique games")
    _info(f"demo_friend owns {len(u2_names)} unique games")
    print()
    if common:
        _ok(f"Common games ({len(common)}):")
        for name in common:
            _info(f"  • {name}")
    else:
        _info("No common games found.")

    if common:
        print(_BLUE + f"  🎮 [Multi-User Pick] → {random.choice(common)}" + _RESET)


def demo_stats(games: list, quiet: bool) -> None:
    _section("📊 Library Statistics")
    _pause(quiet)

    total     = len(games)
    played    = sum(1 for g in games if g["playtime_forever"] > 0)
    unplayed  = total - played
    total_hrs = sum(g["playtime_forever"] for g in games) // 60
    avg_hrs   = total_hrs // max(played, 1)

    genres: dict = {}
    for g in games:
        for genre in g.get("genres", []):
            genres[genre] = genres.get(genre, 0) + 1

    _info(f"Total games      : {total}")
    _info(f"Played           : {played}  ({played * 100 // total}%)")
    _info(f"Unplayed         : {unplayed}  ({unplayed * 100 // total}%)")
    _info(f"Total playtime   : {total_hrs} h")
    _info(f"Average playtime : {avg_hrs} h (played games only)")
    print()
    _ok("Top genres:")
    for genre, count in sorted(genres.items(), key=lambda x: -x[1])[:5]:
        bar = "█" * count
        _info(f"  {genre:<20} {bar} ({count})")


def demo_export(quiet: bool) -> None:
    _section("📤 Export / Import Pick History")
    _pause(quiet)

    history = [
        {"game": "Portal 2",    "timestamp": "2026-02-28T20:00:00Z"},
        {"game": "Garry's Mod", "timestamp": "2026-02-27T18:30:00Z"},
        {"game": "Rust",        "timestamp": "2026-02-25T22:15:00Z"},
    ]
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json',
                                    delete=False) as f:
        json.dump({"history": history}, f, indent=2)
        tmp_path = f.name

    _ok(f"Exported {len(history)} picks → {tmp_path}")

    with open(tmp_path) as f:
        loaded = json.load(f)
    _ok(f"Imported {len(loaded['history'])} picks from file")

    os.unlink(tmp_path)


def demo_achievement_sync(quiet: bool) -> None:
    _section("🏆 Achievement Sync (Steam API mock)")
    _pause(quiet)

    mock_results = [
        {"app_id": "620",    "game_name": "Portal 2",            "added": 51, "updated": 0},
        {"app_id": "4000",   "game_name": "Garry's Mod",         "added":  8, "updated": 2},
        {"app_id": "292030", "game_name": "The Witcher 3",        "added": 78, "updated": 5},
    ]
    for r in mock_results:
        _ok(f"{r['game_name']:<35} +{r['added']} added, {r['updated']} updated")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_demo(quiet: bool = False) -> None:
    _header("🎮  GAPI — Interactive Demo")
    _info("Running in demo mode — no Steam credentials or database required.")
    _info("See README.md for the full installation guide.")

    demo_filters(USER1_GAMES, quiet)
    demo_favourites(USER1_GAMES, quiet)
    demo_multiuser(quiet)
    demo_stats(USER1_GAMES, quiet)
    demo_export(quiet)
    demo_achievement_sync(quiet)

    print()
    print(_CYAN + _sep("═") + _RESET)
    print(_GREEN + "  ✅  Demo complete!  Ready to try GAPI with your own library?" + _RESET)
    print(_CYAN + _sep("─") + _RESET)
    print("  1. Copy config_template.json → config.json")
    print("  2. Add your Steam API key   (https://steamcommunity.com/dev/apikey)")
    print("  3. Add your Steam ID        (https://steamid.io/)")
    print("  4. Run: python3 gapi_gui.py  →  http://127.0.0.1:5000")
    print(_CYAN + _sep("═") + _RESET)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GAPI demo — showcase features without Steam credentials."
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Skip artificial delays (useful for CI / automated runs)",
    )
    args = parser.parse_args()
    run_demo(quiet=args.quiet)


if __name__ == "__main__":
    main()

