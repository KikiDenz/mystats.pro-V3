#!/usr/bin/env python3
"""
============================================================
mystats.pro – EasyStats HTML Parser
Option C – Single-team boxscore files
Rebound Style R2 – OREB + DREB + REB stored
============================================================

Features:
 - Parses EasyStats HTML with dynamic header mapping
 - Extracts FULL stat categories:
      FGM/FGA/FG%, 3PM/3PA/3P%, FTM/FTA/FT%, OREB, DREB, REB,
      AST, STL, BLK, TO, PF, +/- , PTS
 - Removes DNP players (all stats = 0)
 - Correct team assignment (no cross-team bug)
 - Outputs ONE clean boxscore per your team only
 - Produces team totals row
 - Updates games.json
 - Builds derived:
      player_totals.json
      team_leaders.json
      team_records.json
============================================================
"""

import argparse
import json
import re
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

DATA = Path("data")
BOX = DATA / "boxscores"
DER = DATA / "derived"

for d in (DATA, BOX, DER):
    d.mkdir(parents=True, exist_ok=True)


# -----------------------------------------------------------
# Utility functions
# -----------------------------------------------------------

def read_json(path: Path, default):
    """Safe JSON load."""
    if not path.exists() or path.stat().st_size == 0:
        return default
    try:
        return json.loads(path.read_text(encoding="utf8"))
    except:
        return default


def write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf8")


def norm_id(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def to_num(x):
    if x is None:
        return 0
    x = x.strip().replace("%", "")
    if x in ("", "-", "–"):
        return 0
    try:
        return float(x)
    except:
        return 0


def split_made_attempt(s):
    """Convert '4-12' → (4,12)."""
    if not s or s in ("", "-", "–"):
        return 0, 0
    m = re.match(r"(\d+)\s*-\s*(\d+)", s)
    if not m:
        return 0, 0
    return int(m.group(1)), int(m.group(2))


def stats_all_zero(stats: dict) -> bool:
    """DNP = all numeric stats zero."""
    return all((v == 0 for v in stats.values()))


# -----------------------------------------------------------
# Dynamic stat column mapping
# -----------------------------------------------------------

COLUMN_MAP = {
    # basic
    "fgm": "fgm",
    "fga": "fga",
    "fg%": "fg_pct",

    "3pm": "fg3m",
    "3pa": "fg3a",
    "3p%": "fg3_pct",

    "ftm": "ftm",
    "fta": "fta",
    "ft%": "ft_pct",

    "oreb": "oreb",
    "dreb": "dreb",
    "reb": "reb",

    "ast": "ast",
    "stl": "stl",
    "blk": "blk",
    "to": "turnovers",
    "pf": "pf",

    "+/-": "plusminus",
    "pts": "pts",
}


def normalize_header(h):
    """Normalize EasyStats column labels."""
    h = h.lower().strip()
    h = h.replace("3pt", "3p")
    h = h.replace("fg3", "3p")
    h = h.replace(" ", "")
    return h


def detect_columns(table):
    """Return a list mapping column index → internal stat key."""
    headers = [normalize_header(th.get_text(strip=True)) for th in table.find_all("th")]
    mapping = []

    for h in headers:
        mapping.append(COLUMN_MAP.get(h, None))
    return mapping


# -----------------------------------------------------------
# Parse a single table
# -----------------------------------------------------------

def parse_player_table(table):
    column_map = detect_columns(table)
    players = []

    rows = table.find_all("tr")
    for tr in rows:
        tds = tr.find_all("td")
        if not tds:
            continue

        raw_name = tds[0].get_text(strip=True)
        if raw_name.lower().startswith("total"):
            continue  # skip totals in HTML

        # Extract number + name
        m = re.match(r"#?(\d+)\s+(.*)", raw_name)
        if m:
            number = m.group(1)
            name = m.group(2).strip()
        else:
            number = None
            name = raw_name

        pid = norm_id(f"{number}-{name}")

        # Build stats
        stats = {}
        for i, td in enumerate(tds[1:], start=1):
            key = column_map[i] if i < len(column_map) else None
            val = td.get_text(strip=True)

            if key is None:
                continue

            if key in ("fgm", "fga"):
                # FGM/FGA columns appear separately OR as a combined "FG" column
                if "-" in val:
                    fgm, fga = split_made_attempt(val)
                    stats["fgm"] = fgm
                    stats["fga"] = fga
                else:
                    stats[key] = to_num(val)

            elif key in ("fg3m", "fg3a"):
                if "-" in val:
                    m3, a3 = split_made_attempt(val)
                    stats["fg3m"] = m3
                    stats["fg3a"] = a3
                else:
                    stats[key] = to_num(val)

            elif key in ("ftm", "fta"):
                if "-" in val:
                    ftm, fta = split_made_attempt(val)
                    stats["ftm"] = ftm
                    stats["fta"] = fta
                else:
                    stats[key] = to_num(val)

            elif key.endswith("_pct"):
                stats[key] = to_num(val)  # numeric percent

            else:
                stats[key] = to_num(val)

        # Fill missing
        required = [
            "fgm","fga","fg_pct",
            "fg3m","fg3a","fg3_pct",
            "ftm","fta","ft_pct",
            "oreb","dreb","reb",
            "ast","stl","blk","turnovers","pf",
            "plusminus","pts"
        ]
        for k in required:
            stats.setdefault(k, 0)

        # Skip DNP
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
# Derived building
# -----------------------------------------------------------

def build_player_totals(boxscores):
    out = {}
    for g in boxscores.values():
        season = g["season"]
        gtype = g["type"]
        tid = g["team_id"]

        for p in g["players"]:
            pid = p["player_id"]
            key = (pid, season, gtype)

            if key not in out:
                out[key] = {
                    "player_id": pid,
                    "season": season,
                    "type": gtype,
                    "games": 0,
                    "sum": {k: 0 for k in p["stats"]}
                }

            out[key]["games"] += 1
            for k, v in p["stats"].items():
                out[key]["sum"][k] += v

    # Convert to averages
    result = []
    for (pid, season, gtype), rec in out.items():
        g = rec["games"]
        sums = rec["sum"]
        avg = {k: (v / g if g > 0 else 0) for k, v in sums.items()}

        result.append({
            "player_id": pid,
            "season": season,
            "type": gtype,
            "games": g,
            "totals": sums,
            "averages": avg
        })
    return result


def build_team_leaders(player_totals):
    """Top-3 leaders per stat, per team, per season."""
    by_team = {}

    # We do not know which team a player is on from totals alone,
    # so in YOUR system you will have a players.json mapping.
    # For now: leaders stay empty until you provide players.json.
    return []


def build_team_records(boxscores):
    """Single-game records for tracked stats."""
    # Similar note as above: records depend on team_id mapping.
    return []


# -----------------------------------------------------------
# MAIN
# -----------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("htmlfile")
    parser.add_argument("--date")
    parser.add_argument("--season")
    parser.add_argument("--type", choices=["regular","playoff","preseason"])
    parser.add_argument("--team-id", help="Your team ID, ex: pretty-good")
    parser.add_argument("--team-name", help="Pretty name from players.json")
    parser.add_argument("--score")
    parser.add_argument("--opp", help="Opponent name")
    parser.add_argument("--opp-score")
    args = parser.parse_args()

    html = Path(args.htmlfile).read_text(encoding="utf8")
    soup = BeautifulSoup(html, "lxml")

    # ========== DATE ==========
    if args.date:
        try:
            d = datetime.strptime(args.date, "%d/%m/%Y")
        except:
            d = datetime.now()
    else:
        d = datetime.now()
    date_str = d.strftime("%Y-%m-%d")

    # ========== SEASON / TYPE ==========
    season = args.season or input("Season (e.g. 2025 or 2025 Spring): ").strip()
    if season == "":
        season = "2025"

    gtype = args.type or input("Game type (regular/playoff/preseason): ").strip()
    if gtype == "":
        gtype = "regular"

    # ========== TEAM INFO ==========
    team_id = args.team-id or input("Team ID (ex: pretty-good): ").strip().lower().replace(" ", "-")
    team_name = args.team_name or input("Team name (ex: Pretty Good Basketball Team): ").strip()
    opponent = args.opp or input("Opponent name: ").strip()

    score = int(args.score or input("Team score: "))
    opp_score = int(args.opp_score or input("Opponent score: "))

    # ========== PARSE HTML TABLES ==========
    tables = soup.find_all("table", id="stats")
    if len(tables) == 0:
        print("ERROR: No <table id='stats'> found.")
        return

    # We take the FIRST table for your team.
    players = parse_player_table(tables[0])

    # Compute REB if not given explicitly
    for p in players:
        st = p["stats"]
        st["reb"] = st["oreb"] + st["dreb"]

    # Team totals
    totals = {}
    for p in players:
        for k, v in p["stats"].items():
            totals[k] = totals.get(k, 0) + v

    gid = f"game-{date_str}-{team_id}"

    box = {
        "game_id": gid,
        "date": date_str,
        "season": season,
        "type": gtype,
        "team_id": team_id,
        "team_name": team_name,
        "opponent": opponent,
        "team_score": score,
        "opponent_score": opp_score,
        "players": players,
        "team_totals": totals
    }

    # Write boxscore
    out_file = BOX / f"{gid}.json"
    write_json(out_file, box)
    print("Wrote boxscore:", out_file)

    # ========== update games.json ==========
    games_path = DATA / "games.json"
    games = read_json(games_path, [])
    games.append({
        "id": gid,
        "team_id": team_id,
        "date": date_str,
        "season": season,
        "type": gtype,
        "score": score,
        "opp": opponent,
        "opp_score": opp_score,
        "boxscore_json": str(out_file)
    })
    write_json(games_path, games)

    # ========== DERIVED ==========
    print("Rebuilding derived stats...")

    # load all boxscores for your team only
    all_boxes = {}
    for f in BOX.glob("*.json"):
        data = read_json(f, None)
        if data:
            if data["team_id"] == team_id:
                all_boxes[data["game_id"]] = data

    player_totals = build_player_totals(all_boxes)
    team_leaders = build_team_leaders(player_totals)
    team_records = build_team_records(all_boxes)

    write_json(DER / "player_totals.json", player_totals)
    write_json(DER / "team_leaders.json", team_leaders)
    write_json(DER / "team_records.json", team_records)

    print("Done.")


if __name__ == "__main__":
    main()
