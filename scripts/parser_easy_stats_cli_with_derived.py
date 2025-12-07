#!/usr/bin/env python3
"""
============================================================
mystats.pro – Full Parser (FINAL VERSION)
Option C: Only your team in the boxscore
Rebounds R2: OREB + DREB + REB stored
Leaders ranked by per-game averages
Records stored as single-game highs
Supports all stats except +/-
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
    """DNP if all numeric stats zero."""
    return all((v == 0 for v in stats.values()))


# -----------------------------------------------------------
# Dynamic stat column mapping
# -----------------------------------------------------------

COLUMN_MAP = {
    # Shooting
    "fgm": "fgm",
    "fga": "fga",
    "fg%": "fg_pct",

    "3pm": "fg3m",
    "3pa": "fg3a",
    "3p%": "fg3_pct",

    "ftm": "ftm",
    "fta": "fta",
    "ft%": "ft_pct",

    # Rebounds
    "oreb": "oreb",
    "dreb": "dreb",
    "reb": "reb",

    # Other stats
    "ast": "ast",
    "stl": "stl",
    "blk": "blk",
    "to": "turnovers",
    "pf": "pf",
    "pts": "pts",
}


def normalize_header(h):
    """Normalize EasyStats column text."""
    h = h.lower().strip()
    h = h.replace("3pt", "3p")
    h = h.replace("fg3", "3p")
    h = h.replace(" ", "")
    return h


def detect_columns(table):
    headers = [normalize_header(th.get_text(strip=True)) for th in table.find_all("th")]
    return [COLUMN_MAP.get(h, None) for h in headers]


# -----------------------------------------------------------
# Parse a table into player rows
# -----------------------------------------------------------

def parse_player_table(table):
    column_map = detect_columns(table)
    players = []

    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue

        raw_name = tds[0].get_text(strip=True)
        if raw_name.lower().startswith("total"):
            continue

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
            stat_key = column_map[i] if i < len(column_map) else None
            val = td.get_text(strip=True)

            if stat_key is None:
                continue

            # parse M-A form
            if stat_key in ("fgm", "fga"):
                if "-" in val:
                    fgm, fga = split_made_attempt(val)
                    stats["fgm"], stats["fga"] = fgm, fga
                else:
                    stats[stat_key] = to_num(val)

            elif stat_key in ("fg3m", "fg3a"):
                if "-" in val:
                    m3, a3 = split_made_attempt(val)
                    stats["fg3m"], stats["fg3a"] = m3, a3
                else:
                    stats[stat_key] = to_num(val)

            elif stat_key in ("ftm", "fta"):
                if "-" in val:
                    ftm, fta = split_made_attempt(val)
                    stats["ftm"], stats["fta"] = ftm, fta
                else:
                    stats[stat_key] = to_num(val)

            elif stat_key.endswith("_pct"):
                stats[stat_key] = to_num(val)

            else:
                stats[stat_key] = to_num(val)

        # Fill missing stats
        required = [
            "fgm", "fga", "fg_pct",
            "fg3m", "fg3a", "fg3_pct",
            "ftm", "fta", "ft_pct",
            "oreb", "dreb", "reb",
            "ast", "stl", "blk", "turnovers", "pf",
            "pts"
        ]
        for r in required:
            stats.setdefault(r, 0)

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
# Load players.json → map pid → team_ids
# -----------------------------------------------------------

def load_players_index():
    path = DATA / "players.json"
    arr = read_json(path, [])
    index = {}

    for p in arr:
        pid = p["id"]
        index[pid] = {
            "teams": p.get("teams", []),
            "name": p.get("display_name", p.get("name", pid)),
        }

    return index


# -----------------------------------------------------------
# Derived: player totals + averages
# -----------------------------------------------------------

def build_player_totals(boxscores, players_index):
    results = {}

    for g in boxscores.values():
        season = g["season"]
        gtype = g["type"]

        for p in g["players"]:
            pid = p["player_id"]
            st = p["stats"]
            key = (pid, season, gtype)

            if key not in results:
                results[key] = {
                    "player_id": pid,
                    "season": season,
                    "type": gtype,
                    "games": 0,
                    "sum": {k: 0 for k in st}
                }

            results[key]["games"] += 1
            for k, v in st.items():
                results[key]["sum"][k] += v

    # Convert to averages
    output = []
    for (pid, season, gtype), rec in results.items():
        g = rec["games"]
        sums = rec["sum"]
        avg = {k: (v / g if g > 0 else 0) for k, v in sums.items()}

        output.append({
            "player_id": pid,
            "season": season,
            "type": gtype,
            "games": g,
            "totals": sums,
            "averages": avg
        })

    return output


# -----------------------------------------------------------
# Derived: per-game team leaders
# -----------------------------------------------------------

LEADER_STATS = [
    "pts", "fgm", "fga", "fg_pct",
    "fg3m", "fg3a", "fg3_pct",
    "ftm", "fta", "ft_pct",
    "oreb", "dreb", "reb",
    "ast", "stl", "blk", "turnovers", "pf"
]


def build_team_leaders(player_totals, players_index):
    leaders_by_team = {}

    # Group totals by team+season
    for rec in player_totals:
        pid = rec["player_id"]
        season = rec["season"]
        gtype = rec["type"]

        # Find the player's teams
        teams = players_index.get(pid, {}).get("teams", [])
        for tid in teams:
            key = (tid, season, gtype)
            if key not in leaders_by_team:
                leaders_by_team[key] = {s: [] for s in LEADER_STATS}

            for stat in LEADER_STATS:
                value = rec["averages"].get(stat, 0)
                leaders_by_team[key][stat].append({
                    "player_id": pid,
                    "value": value
                })

    # Sort and trim leaders
    final_output = []
    for (tid, season, gtype), stat_dict in leaders_by_team.items():
        for stat, arr in stat_dict.items():
            ranked = sorted(arr, key=lambda x: x["value"], reverse=True)
            final_output.append({
                "team_id": tid,
                "season": season,
                "type": gtype,
                "stat": stat,
                "leaders": ranked[:10]
            })

    return final_output


# -----------------------------------------------------------
# Derived: single-game team records
# -----------------------------------------------------------

def build_team_records(boxscores, players_index):
    records = {}

    for g in boxscores.values():
        tid = g["team_id"]
        season = g["season"]
        date = g["date"]

        for p in g["players"]:
            pid = p["player_id"]
            st = p["stats"]

            for stat in LEADER_STATS:
                val = st.get(stat, 0)
                if val == 0:
                    continue

                key = (tid, season, stat)
                if key not in records:
                    records[key] = []

                records[key].append({
                    "player_id": pid,
                    "value": val,
                    "date": date
                })

    # sort each record list
    output = []
    for (tid, season, stat), arr in records.items():
        ranked = sorted(arr, key=lambda x: x["value"], reverse=True)
        output.append({
            "team_id": tid,
            "season": season,
            "stat": stat,
            "records": ranked[:10]
        })

    return output


# -----------------------------------------------------------
# MAIN
# -----------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("htmlfile")
    parser.add_argument("--date")
    parser.add_argument("--season")
    parser.add_argument("--type", choices=["regular", "playoff", "preseason"])
    parser.add_argument("--team-id")
    parser.add_argument("--team-name")
    parser.add_argument("--score")
    parser.add_argument("--opp")
    parser.add_argument("--opp-score")
    args = parser.parse_args()

    html = Path(args.htmlfile).read_text(encoding="utf8")
    soup = BeautifulSoup(html, "lxml")

    # ----- DATE -----
    if args.date:
        try:
            d = datetime.strptime(args.date, "%d/%m/%Y")
        except:
            d = datetime.now()
    else:
        d = datetime.now()
    date_str = d.strftime("%Y-%m-%d")

    # ----- SEASON / TYPE -----
    season = args.season or input("Season: ").strip()
    if not season:
        season = "2025"

    gtype = args.type or input("Game type (regular/playoff): ").strip()
    if not gtype:
        gtype = "regular"

    # ----- TEAM INFO -----
    team_id = args.team_id or input("Team ID (example: pretty-good): ").strip().lower().replace(" ", "-")
    team_name = args.team_name or input("Team Name: ").strip()
    opponent = args.opp or input("Opponent Name: ").strip()

    score = int(args.score or input("Team Score: "))
    opp_score = int(args.opp_score or input("Opponent Score: "))

    # ----- PARSE HTML -----
    tables = soup.find_all("table", id="stats")
    if not tables:
        print("ERROR: No table with id='stats'")
        return

    # Take first table as your team's stats
    players = parse_player_table(tables[0])

    # Compute REB (R2)
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

    # Write boxscore file
    out_file = BOX / f"{gid}.json"
    write_json(out_file, box)
    print("Wrote boxscore:", out_file)

    # ----- Update games.json -----
    games = read_json(DATA / "games.json", [])
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
    write_json(DATA / "games.json", games)

    # ----- Build derived -----
    print("Building derived stats...")

    players_index = load_players_index()

    # load all boxscores for this team
    all_boxes = {
        g["game_id"]: g
        for f in BOX.glob("*.json")
        for g in [read_json(f, None)]
        if g and g["team_id"] == team_id
    }

    player_totals = build_player_totals(all_boxes, players_index)
    team_leaders = build_team_leaders(player_totals, players_index)
    team_records = build_team_records(all_boxes, players_index)

    write_json(DER / "player_totals.json", player_totals)
    write_json(DER / "team_leaders.json", team_leaders)
    write_json(DER / "team_records.json", team_records)

    print("Done.")


if __name__ == "__main__":
    main()
