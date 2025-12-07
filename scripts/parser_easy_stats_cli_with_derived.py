#!/usr/bin/env python3
"""
EasyStats HTML → mystats.pro JSON converter (CLI version)
---------------------------------------------------------
Features:
 - Parse EasyStats HTML exports
 - Cleanly extract player + team stats
 - Remove DNP players (all-zero stat lines)
 - CLI for supplying correct date, season, scores, teams
 - Write boxscore JSON → data/boxscores/
 - Update games.json
 - Build derived files:
      player_totals.json
      team_leaders.json
      team_records.json
"""

import argparse
import json
import re
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

DATA_DIR = Path("data")
BOX_DIR = DATA_DIR / "boxscores"
DERIVED_DIR = DATA_DIR / "derived"

for d in [DATA_DIR, BOX_DIR, DERIVED_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------
# Utilities
# -----------------------------------------------------------

def read_json(path: Path, default):
    """Load JSON or return default if missing/empty/invalid."""
    if not path.exists() or path.stat().st_size == 0:
        return default
    try:
        return json.loads(path.read_text(encoding="utf8"))
    except:
        return default


def write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf8")


def norm_id(s: str) -> str:
    return re.sub(r"[^a-z0-9\-]+", "-", s.lower()).strip("-")


def split_made_attempt(s):
    """Turn '6-19' into (6,19)."""
    if not s or s == "-":
        return 0, 0
    m = re.match(r"(\d+)\s*-\s*(\d+)", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0


def to_int(s):
    if s is None:
        return 0
    s = s.strip().replace("%", "")
    if s in ("", "-", "–"):
        return 0
    try:
        return int(float(s))
    except:
        return 0


def stats_all_zero(stats: dict) -> bool:
    """
    Return True if a player has 0 in all numeric categories (DNP).
    """
    for v in stats.values():
        if isinstance(v, (int, float)) and v != 0:
            return False
    return True


# -----------------------------------------------------------
# Parse each player row
# -----------------------------------------------------------

def parse_stats_table(table):
    players = []

    headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]

    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue

        cells = [td.get_text(strip=True) for td in tds]

        # skip Team Totals rows
        if "total" in cells[0].lower():
            continue

        # Parse name + number
        first = cells[0]
        m = re.match(r"#?(\d+)\s+(.*)", first)
        if m:
            number = m.group(1)
            name = m.group(2).strip()
        else:
            number = None
            name = first.strip()

        pid = norm_id(f"{number}-{name}")

        # Build stats
        stats = {}

        for i, h in enumerate(headers):
            if i + 1 >= len(cells):
                continue
            val = cells[i + 1]

            if h == "fg":
                fgm, fga = split_made_attempt(val)
                stats["fgm"], stats["fga"] = fgm, fga

            elif h in ("3pt", "3ptfg", "3ptm"):
                m3, a3 = split_made_attempt(val)
                stats["fg3m"], stats["fg3a"] = m3, a3

            elif h == "ft":
                ftm, fta = split_made_attempt(val)
                stats["ftm"], stats["fta"] = ftm, fta

            elif h in ("oreb", "orb"):
                stats["oreb"] = to_int(val)

            elif h in ("dreb", "drb"):
                stats["dreb"] = to_int(val)

            elif h in ("asst", "ast"):
                stats["ast"] = to_int(val)

            elif h == "stl":
                stats["stl"] = to_int(val)

            elif h in ("to", "turn"):
                stats["turnovers"] = to_int(val)

            elif h == "blk":
                stats["blk"] = to_int(val)

            elif h == "pts":
                stats["pts"] = to_int(val)

        # Default missing fields
        for key in ["fgm","fga","fg3m","fg3a","ftm","fta","oreb","dreb","ast","stl","blk","turnovers","pts"]:
            stats.setdefault(key, 0)

        # Skip DNP players
        if stats_all_zero(stats):
            continue

        players.append({
            "player_id": pid,
            "name": name,
            "number": number,
            "stats": stats
        })

    return players


# -----------------------------------------------------------
# Build derived statistics
# -----------------------------------------------------------

def build_player_totals(boxscores, games_list):
    """Generate season totals + averages for each player."""
    totals = {}

    for g in boxscores.values():
        season = g["season"]
        gtype = g["type"]
        gid = g["game_id"]

        for tname, tdata in g["teams"].items():
            for p in tdata["players"]:
                pid = p["player_id"]
                st = p["stats"]

                key = (pid, season, gtype)

                if key not in totals:
                    totals[key] = {
                        "player_id": pid,
                        "season": season,
                        "type": gtype,
                        "games": 0,
                        "sum": {k: 0 for k in st}
                    }

                totals[key]["games"] += 1
                for k, v in st.items():
                    totals[key]["sum"][k] += v

    # convert to averages
    out = []
    for (pid, season, gtype), rec in totals.items():
        g = rec["games"]
        sums = rec["sum"]
        avg = {k: (v / g) if g > 0 else 0 for k, v in sums.items()}

        out.append({
            "player_id": pid,
            "season": season,
            "type": gtype,
            "games": g,
            "totals": sums,
            "averages": avg
        })

    return out


def build_team_leaders(player_totals):
    """Build top-10 per-game leaders per team per season."""
    # You can expand this later, but for now we leave empty unless needed.
    return []


def build_team_records(boxscores):
    """Build single-game records for each team."""
    # Also optional until later.
    return []


# -----------------------------------------------------------
# Main CLI
# -----------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("htmlfile")
    parser.add_argument("--date")
    parser.add_argument("--season")
    parser.add_argument("--type", choices=["regular","playoff","preseason"])
    parser.add_argument("--away-team")
    parser.add_argument("--home-team")
    parser.add_argument("--away-score")
    parser.add_argument("--home-score")
    args = parser.parse_args()

    html = Path(args.htmlfile).read_text(encoding="utf8")
    soup = BeautifulSoup(html, "lxml")

    # Parse date (CLI overrides file)
    if args.date:
        try:
            parsed_date = datetime.strptime(args.date, "%d/%m/%Y").strftime("%Y-%m-%d")
        except:
            print("Invalid date format; using today's date")
            parsed_date = datetime.now().strftime("%Y-%m-%d")
    else:
        parsed_date = datetime.now().strftime("%Y-%m-%d")

    # Season
    season = args.season or input("Season (e.g. 2025): ").strip()
    if season == "":
        season = "2025"

    gtype = args.type or input("Game type (regular/playoff/preseason): ").strip()
    if gtype == "":
        gtype = "regular"

    away_team = args.away_team or input("Away team name: ").strip()
    home_team = args.home_team or input("Home team name: ").strip()

    away_score = int(args.away_score or input("Away score: ").strip())
    home_score = int(args.home_score or input("Home score: ").strip())

    # Parse tables
    tables = soup.find_all("table", id="stats")
    if len(tables) < 2:
        print("Warning: Expected 2 stats tables, found:", len(tables))

    away_players = parse_stats_table(tables[0]) if len(tables) > 0 else []
    home_players = parse_stats_table(tables[1]) if len(tables) > 1 else []

    # Build the boxscore JSON
    gid = f"game-{parsed_date}-{norm_id(away_team)}-v-{norm_id(home_team)}"
    box = {
        "game_id": gid,
        "date": parsed_date,
        "season": season,
        "type": gtype,
        "away_team": away_team,
        "home_team": home_team,
        "away_score": away_score,
        "home_score": home_score,
        "teams": {
            away_team: {"players": away_players},
            home_team: {"players": home_players},
        }
    }

    # Write boxscore
    out_path = BOX_DIR / f"{gid}.json"
    write_json(out_path, box)
    print("Wrote boxscore JSON:", out_path)

    # Update games.json
    games_path = DATA_DIR / "games.json"
    games = read_json(games_path, [])
    games.append({
        "id": gid,
        "date": parsed_date,
        "season": season,
        "type": gtype,
        "away_team": away_team,
        "home_team": home_team,
        "away_score": away_score,
        "home_score": home_score,
        "boxscore_json": str(out_path)
    })
    write_json(games_path, games)

    # Rebuild derived stats
    print("Rebuilding derived stats...")

    # Load all boxscores again
    boxscores = {}
    for f in BOX_DIR.glob("*.json"):
        data = read_json(f, None)
        if data:
            boxscores[data["game_id"]] = data

    player_totals = build_player_totals(boxscores, games)
    team_leaders = build_team_leaders(player_totals)
    team_records = build_team_records(boxscores)

    write_json(DERIVED_DIR / "player_totals.json", player_totals)
    write_json(DERIVED_DIR / "team_leaders.json", team_leaders)
    write_json(DERIVED_DIR / "team_records.json", team_records)

    print("Done.")


if __name__ == "__main__":
    main()
