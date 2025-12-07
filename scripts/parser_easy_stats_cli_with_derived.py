#!/usr/bin/env python3
"""
mystats.pro – FINAL PARSER (header-aware, EasyStats)

- Reads EasyStats HTML export
- Finds the full boxscore table (with FG / 3PT / FT M-A)
- Maps headers by name (fg, 3pt, ft, oreb, dreb, fouls, stl, to, blk, asst, pts)
- Normalizes names like '#11 J. Todd' -> 'J. Todd'
- Matches 'J. Todd' -> full name from players.json using initial+last
- Computes FG%, 3P%, FT% from M-A
- Computes REB = OREB + DREB
- Skips players only if ALL stats == 0 (DNP)
- Builds:
    - boxscores/*.json
    - data/games.json
    - data/derived/player_totals.json
    - data/derived/team_leaders.json
    - data/derived/team_records.json
"""

import argparse
import json
import re
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

# -------------------------------------------------------------------
# Directories
# -------------------------------------------------------------------

DATA = Path("data")
BOX = DATA / "boxscores"
DER = DATA / "derived"

for d in (DATA, BOX, DER):
    d.mkdir(parents=True, exist_ok=True)


# -------------------------------------------------------------------
# Basic utils
# -------------------------------------------------------------------

def read_json(path: Path, default):
    if not path.exists() or path.stat().st_size == 0:
        return default
    try:
        return json.loads(path.read_text(encoding="utf8"))
    except Exception:
        return default


def write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf8")


def norm_id(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def to_num(x):
    if x is None:
        return 0
    x = x.strip()
    if x in ("", "-", "–"):
        return 0
    try:
        return float(x)
    except Exception:
        return 0


def split_made_attempt(s: str):
    """
    '10-16' -> (10,16)
    """
    s = s.strip()
    m = re.match(r"^(\d+)\s*-\s*(\d+)$", s)
    if not m:
        return 0, 0
    return int(m.group(1)), int(m.group(2))


def stats_all_zero(stats: dict) -> bool:
    """
    DNP rule: only skip if *all* stats are zero.
    """
    return all(v == 0 for v in stats.values())


# -------------------------------------------------------------------
# players.json → index
# -------------------------------------------------------------------

def load_players_index():
    arr = read_json(DATA / "players.json", [])
    index = {}
    for p in arr:
        pid = p["id"]
        name = p.get("name", p.get("display_name", pid))
        teams = p.get("teams", [])
        index[pid] = {"name": name, "teams": teams}
    return index


# -------------------------------------------------------------------
# Name handling
# -------------------------------------------------------------------

def normalize_abbrev_name(name: str) -> str:
    """
    Strip jersey numbers:
      '#11 J. Todd' -> 'J. Todd'
      '11 J. Todd'  -> 'J. Todd'
    """
    name = name.strip()
    name = re.sub(r"^#?\d+\s+", "", name)
    return name


def match_player_name(abbrev: str, players_index):
    """
    Map 'J. Todd' -> player_id in players.json using:
      1) exact name match
      2) initial + last name
      3) unique last name
    """
    abbrev = abbrev.lower().strip()
    parts = abbrev.split()
    if len(parts) != 2:
        return None

    first_part, last_name = parts
    initial = first_part.replace(".", "")
    last_name = last_name.replace(".", "")

    # 1) exact match
    for pid, pdata in players_index.items():
        if pdata["name"].lower() == abbrev:
            return pid

    # 2) initial + last
    for pid, pdata in players_index.items():
        full = pdata["name"].lower().split()
        if len(full) >= 2 and full[-1] == last_name and full[0].startswith(initial):
            return pid

    # 3) unique last
    candidates = []
    for pid, pdata in players_index.items():
        full = pdata["name"].lower().split()
        if full and full[-1] == last_name:
            candidates.append(pid)
    if len(candidates) == 1:
        return candidates[0]

    return None


# -------------------------------------------------------------------
# Select the full M-A table
# -------------------------------------------------------------------

def select_full_stats_table(all_tables):
    """
    EasyStats export usually has a summary table and a full stats table.
    We pick the table that contains values like '10-16', '5-12', etc.
    """
    for table in all_tables:
        for td in table.find_all("td"):
            txt = td.get_text(strip=True)
            if re.match(r"^\d+\s*-\s*\d+$", txt):
                return table
    return all_tables[0] if all_tables else None


# -------------------------------------------------------------------
# Header normalisation + mapping
# -------------------------------------------------------------------

def norm_header(h: str) -> str:
    """
    Normalise a header cell to a simple key:

      'FG%'    -> 'fgpct'
      '3PT'    -> '3pt'
      '3pt%'   -> '3ptpct'
      'Asst'   -> 'ast'
      'Fouls'  -> 'fouls'
    """
    h = h.lower().strip()

    h = h.replace("%", "pct")
    h = h.replace("asst", "ast")
    h = h.replace("assist", "ast")
    h = h.replace("t/o", "to")
    h = h.replace("3 pt", "3pt")
    h = h.replace("3-pt", "3pt")

    # remove non-alphanumerics
    h = re.sub(r"[^a-z0-9]+", "", h)
    return h


HEADER_MAP = {
    "fg": "fg",                # '10-16'
    "fgpct": "fg_pct_src",     # we ignore; compute ourselves

    "3pt": "fg3",              # '5-12'
    "3ptpct": "fg3_pct_src",   # ignore

    "ft": "ft",                # '1-3'
    "ftpct": "ft_pct_src",     # ignore

    "oreb": "oreb",
    "dreb": "dreb",
    "reb": "reb",              # overridden with oreb+dreb

    "ast": "ast",
    "stl": "stl",
    "blk": "blk",

    "to": "turnovers",
    "turnovers": "turnovers",

    # fouls
    "foul": "pf",
    "fouls": "pf",
    "pf": "pf",

    "pts": "pts",
}


# -------------------------------------------------------------------
# Parse full player table
# -------------------------------------------------------------------

def parse_player_table(table, players_index):
    players = []
    if table is None:
        return players

    # Find header row (first tr with any th)
    header_tr = None
    for tr in table.find_all("tr"):
        if tr.find("th"):
            header_tr = tr
            break
    if header_tr is None:
        return players

    header_cells = header_tr.find_all("th")
    header_keys = []
    for th in header_cells:
        key = HEADER_MAP.get(norm_header(th.get_text(strip=True)), None)
        header_keys.append(key)

    # Data rows = trs after header_tr that contain td cells
    for tr in header_tr.find_all_next("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue

        raw_name = tds[0].get_text(strip=True)
        if not raw_name:
            continue

        name = normalize_abbrev_name(raw_name)
        matched_pid = match_player_name(name, players_index)
        pid = matched_pid or norm_id(name)

        # Initialise stats
        stats = {
            "fgm": 0, "fga": 0,
            "fg3m": 0, "fg3a": 0,
            "ftm": 0, "fta": 0,
            "oreb": 0, "dreb": 0,
            "reb": 0,
            "ast": 0, "stl": 0,
            "blk": 0, "turnovers": 0,
            "pf": 0, "pts": 0,
            "fg_pct": 0, "fg3_pct": 0, "ft_pct": 0,
        }

        # Loop through columns with header keys
        for i, td in enumerate(tds):
            val = td.get_text(strip=True)
            key = header_keys[i] if i < len(header_keys) else None
            if key is None:
                continue

            if key == "fg":
                fgm, fga = split_made_attempt(val)
                stats["fgm"], stats["fga"] = fgm, fga
            elif key == "fg3":
                m3, a3 = split_made_attempt(val)
                stats["fg3m"], stats["fg3a"] = m3, a3
            elif key == "ft":
                ftm, fta = split_made_attempt(val)
                stats["ftm"], stats["fta"] = ftm, fta
            elif key in ("fg_pct_src", "fg3_pct_src", "ft_pct_src"):
                # ignore HTML percentages – we compute from M-A
                continue
            else:
                stats[key] = to_num(val)

        # REB = OREB + DREB (override HTML REB)
        stats["reb"] = stats["oreb"] + stats["dreb"]

        # Percentages
        stats["fg_pct"] = (stats["fgm"] / stats["fga"] * 100) if stats["fga"] > 0 else 0
        stats["fg3_pct"] = (stats["fg3m"] / stats["fg3a"] * 100) if stats["fg3a"] > 0 else 0
        stats["ft_pct"] = (stats["ftm"] / stats["fta"] * 100) if stats["fta"] > 0 else 0

        # DNP skip rule
        if stats_all_zero(stats):
            continue

        players.append({
            "player_id": pid,
            "name": name,
            "stats": stats
        })

    return players


# -------------------------------------------------------------------
# Derived stats
# -------------------------------------------------------------------

LEADER_STATS = [
    "pts", "fgm", "fga", "fg_pct",
    "fg3m", "fg3a", "fg3_pct",
    "ftm", "fta", "ft_pct",
    "oreb", "dreb", "reb",
    "ast", "stl", "blk", "turnovers", "pf"
]


def build_player_totals(boxscores):
    agg = {}
    for g in boxscores.values():
        season = g["season"]
        gtype = g["type"]
        for p in g["players"]:
            pid = p["player_id"]
            st = p["stats"]
            key = (pid, season, gtype)
            if key not in agg:
                agg[key] = {
                    "player_id": pid,
                    "season": season,
                    "type": gtype,
                    "games": 0,
                    "sum": {k: 0 for k in st}
                }
            agg[key]["games"] += 1
            for k, v in st.items():
                agg[key]["sum"][k] += v

    out = []
    for (pid, season, gtype), rec in agg.items():
        games = rec["games"]
        sums = rec["sum"]
        av = {k: (v / games if games else 0) for k, v in sums.items()}
        out.append({
            "player_id": pid,
            "season": season,
            "type": gtype,
            "games": games,
            "totals": sums,
            "averages": av
        })
    return out


def build_team_leaders(player_totals, players_index):
    grouped = {}
    for rec in player_totals:
        pid = rec["player_id"]
        season = rec["season"]
        gtype = rec["type"]
        av = rec["averages"]
        teams = players_index.get(pid, {}).get("teams", [])
        for tid in teams:
            key = (tid, season, gtype)
            if key not in grouped:
                grouped[key] = {s: [] for s in LEADER_STATS}
            for stat in LEADER_STATS:
                grouped[key][stat].append({
                    "player_id": pid,
                    "value": av.get(stat, 0)
                })

    results = []
    for (tid, season, gtype), stat_map in grouped.items():
        for stat, arr in stat_map.items():
            ranked = sorted(arr, key=lambda x: x["value"], reverse=True)
            results.append({
                "team_id": tid,
                "season": season,
                "type": gtype,
                "stat": stat,
                "leaders": ranked[:10]
            })
    return results


def build_team_records(boxscores):
    out = {}
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
                if key not in out:
                    out[key] = []
                out[key].append({"player_id": pid, "value": val, "date": date})

    results = []
    for (tid, season, stat), arr in out.items():
        ranked = sorted(arr, key=lambda x: x["value"], reverse=True)
        results.append({
            "team_id": tid,
            "season": season,
            "stat": stat,
            "records": ranked[:10]
        })
    return results


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("htmlfile")
    parser.add_argument("--date")
    parser.add_argument("--season")
    parser.add_argument("--type")
    parser.add_argument("--team-id")
    parser.add_argument("--team-name")
    parser.add_argument("--score")
    parser.add_argument("--opp")
    parser.add_argument("--opp-score")
    args = parser.parse_args()

    players_index = load_players_index()

    # Date
    if args.date:
        try:
            d = datetime.strptime(args.date, "%d/%m/%Y")
        except Exception:
            d = datetime.now()
    else:
        d = datetime.now()
    date_str = d.strftime("%Y-%m-%d")

    season = args.season or input("Season: ").strip() or "2025"
    gtype = args.type or input("Game type (regular/playoff): ").strip() or "regular"

    team_id = (args.team_id or input("Team ID: ").strip()).lower().replace(" ", "-")
    team_name = args.team_name or input("Team Name: ").strip()
    opponent = args.opp or input("Opponent: ").strip()
    score = int(args.score or input("Team Score: "))
    opp_score = int(args.opp_score or input("Opponent Score: "))

    html = Path(args.htmlfile).read_text(encoding="utf8")
    soup = BeautifulSoup(html, "lxml")
    all_tables = soup.find_all("table")
    full_table = select_full_stats_table(all_tables)
    players = parse_player_table(full_table, players_index)

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
        "team_totals": totals,
    }

    out_path = BOX / f"{gid}.json"
    write_json(out_path, box)
    print(f"✓ Boxscore written: {out_path}")

    # Update games.json
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
        "boxscore_json": str(out_path),
    })
    write_json(DATA / "games.json", games)

    # Derived from all boxscores for this team
    boxscores = {}
    for f in BOX.glob("*.json"):
        g = read_json(f, None)
        if g and g["team_id"] == team_id:
            boxscores[g["game_id"]] = g

    player_totals = build_player_totals(boxscores)
    team_leaders = build_team_leaders(player_totals, players_index)
    team_records = build_team_records(boxscores)

    write_json(DER / "player_totals.json", player_totals)
    write_json(DER / "team_leaders.json", team_leaders)
    write_json(DER / "team_records.json", team_records)

    print("✓ Derived stats updated.")
    print("✓ DONE.")


if __name__ == "__main__":
    main()
