#!/usr/bin/env python3
"""parser_easy_stats_cli_with_derived.py

Usage:
  python3 scripts/parser_easy_stats_cli_with_derived.py path/to/export.html
  [--date YYYY-MM-DD] [--season 2025] [--type regular|playoff|preseason]
  [--away-team "Monstars"] [--home-team "Pretty good"]
  [--away-score 79] [--home-score 84]

If flags are omitted you will be prompted interactively.

This script:
 - Parses an Easy Stats HTML boxscore.
 - Lets you override date, season, game type, teams and scores.
 - Writes data/boxscores/<game-id>.json
 - Appends/updates data/games.json
 - Rebuilds aggregated JSONs in data/derived/:
     * player_totals.json  (per player / team / season / type)
     * team_leaders.json   (leaders per team / season / type)
     * team_records.json   (top 3 single-game records per stat)
"""
import argparse
import json
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from bs4 import BeautifulSoup

DATA_DIR = Path('data')
BOX_DIR = DATA_DIR / 'boxscores'
RAW_DIR = DATA_DIR / 'raw'
for d in (DATA_DIR, BOX_DIR, RAW_DIR):
    d.mkdir(parents=True, exist_ok=True)

# stats we track/aggregate
STAT_CATS = ['pts','reb','ast','stl','blk','turnovers','fgm','fga','fg3m','fg3a','ftm','fta']


# ---------- helpers ----------
def read_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding='utf8'))
    return default

def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding='utf8')

def norm_id(s):
    return re.sub(r'[^a-z0-9\-]+','-', s.lower()).strip('-')

def split_made_attempt(val):
    if not val or str(val).strip() in ('', '-', '--'):
        return (0,0)
    m = re.match(r'^\s*(\d+)\s*-\s*(\d+)\s*$', str(val))
    if m:
        return int(m.group(1)), int(m.group(2))
    m2 = re.match(r'^\s*(\d+)\s*$', str(val))
    if m2:
        v = int(m2.group(1)); return v, v
    return (0,0)

def to_int(val):
    if val is None: return 0
    s = str(val).strip().replace('%','')
    if s in ('', '-', '--'): return 0
    try:
        return int(float(s))
    except:
        return 0

def extract_number_and_name(firstcell):
    s = (firstcell or '').strip()
    # "#37 K. Denzin" / "37 K Denzin"
    m = re.match(r'^#?(\d{1,3})\s+(.+)$', s)
    if m:
        return m.group(1), m.group(2).strip()
    # "K. Denzin #37" / "K. Denzin (37)"
    m2 = re.match(r'^(.+?)\s*\(?#?(\d{1,3})\)?$', s)
    if m2:
        return m2.group(2), m2.group(1).strip()
    # just a name
    return None, s


# ---------- parse a team stats table ----------
def parse_table_players(table):
    header_cells = [th.get_text(strip=True).lower() for th in table.find_all('th')]
    players = []
    for tr in table.find_all('tr'):
        tds = tr.find_all('td')
        if not tds:
            continue
        cells = [td.get_text(strip=True) for td in tds]
        firstcell = cells[0] if cells else ''
        # skip totals rows
        if re.search(r'(team\s*totals|totals)', firstcell, re.I):
            continue
        if firstcell.strip() == '':
            continue

        number, name = extract_number_and_name(firstcell)
        pid = norm_id((number + '-' + name) if number else name)

        # align headers and data
        if len(header_cells) == len(cells):
            shift = 0
        elif len(header_cells) == len(cells) - 1:
            shift = 1
        else:
            shift = 1

        stats = {}
        for i, h in enumerate(header_cells):
            ci = i + shift
            if ci >= len(cells):
                break
            val = cells[ci]
            key = h.strip()
            if key in ('fg',):
                fgm,fga = split_made_attempt(val); stats['fgm']=fgm; stats['fga']=fga
            elif key in ('3pt','3ptfg','3ptm','3pt%m','3pt%'):
                m3,a3 = split_made_attempt(val); stats['fg3m']=m3; stats['fg3a']=a3
            elif key in ('ft',):
                ftm,fta = split_made_attempt(val); stats['ftm']=ftm; stats['fta']=fta
            elif key in ('fg%','ft%'):
                # ignore % columns
                continue
            elif key in ('oreb','orb','off'):
                stats['oreb'] = to_int(val)
            elif key in ('dreb','drb','def'):
                stats['dreb'] = to_int(val)
            elif key in ('fouls','foul'):
                stats['fouls'] = to_int(val)
            elif key in ('stl','st'):
                stats['stl'] = to_int(val)
            elif key in ('to','tos','turnover','turnovers'):
                stats['turnovers'] = to_int(val)
            elif key in ('blk','b'):
                stats['blk'] = to_int(val)
            elif key in ('asst','ast','assts'):
                stats['ast'] = to_int(val)
            elif key in ('pts','points'):
                stats['pts'] = to_int(val)
            else:
                stats[key] = to_int(val)

        # ensure all STAT_CATS present
        for k in STAT_CATS:
            if k == 'reb':
                stats.setdefault('reb', stats.get('oreb',0)+stats.get('dreb',0))
            else:
                stats.setdefault(k, 0)

        players.append({
            'player_id': pid,
            'name': name,
            'number': number,
            'stats': stats
        })
    return players


# ---------- parse the Easy Stats HTML (rough defaults) ----------
def parse_easy_stats_html(html_path):
    p = Path(html_path)
    soup = BeautifulSoup(p.read_text(encoding='utf8'), 'lxml')

    # best-effort date
    date_node = soup.select_one('#game-date') or soup.find(
        lambda t: t.name in ('div','span') and 'game-date' in (t.get('id') or '')
    )
    date_text = date_node.get_text(strip=True) if date_node else ''
    parsed_date = None
    for fmt in ('%d %b %Y', '%d %B %Y', '%Y-%m-%d'):
        try:
            parsed_date = datetime.strptime(date_text, fmt).strftime('%Y-%m-%d')
            break
        except:
            continue
    if not parsed_date:
        parsed_date = datetime.now().strftime('%Y-%m-%d')

    # team names (left = away, right = home in your export)
    away_name = None
    home_name = None
    tn_left = (soup.select_one('#team-names-container .left')
               or soup.select_one('.team-left')
               or soup.select_one('.teamName.left'))
    tn_right = (soup.select_one('#team-names-container .right')
                or soup.select_one('.team-right')
                or soup.select_one('.teamName.right'))
    if tn_left:
        away_name = tn_left.get_text(strip=True)
    if tn_right:
        home_name = tn_right.get_text(strip=True)

    # scores (in case you want them as defaults)
    def parse_score(sel):
        n = soup.select_one(sel)
        if n:
            txt = n.get_text(strip=True)
            if re.match(r'^\d+$', txt):
                return int(txt)
        return None

    score_left = parse_score('#team-score-left .title') or parse_score('.score-left .title') or None
    score_right = parse_score('#team-score-right .title') or parse_score('.score-right .title') or None

    # tables with player stats
    tables = soup.find_all('table', id='stats')
    if not tables:
        tables = [t for t in soup.find_all('table')
                  if any('pts' in th.get_text(strip=True).lower()
                         for th in t.find_all('th'))]

    teams_obj = {}
    for idx, table in enumerate(tables):
        teamname = away_name if idx == 0 and away_name else home_name if idx == 1 and home_name else f"team-{idx+1}"
        teams_obj[teamname] = {
            'players': parse_table_players(table),
            'team_totals': {}
        }

    return {
        'date': parsed_date,
        'away_name': away_name,
        'home_name': home_name,
        'away_score': score_left,
        'home_score': score_right,
        'teams_obj': teams_obj,
        'raw_html_path': str(p)
    }


def build_game_id(date_str, away, home):
    return f"game-{date_str}-{norm_id(away or 'away')}-v-{norm_id(home or 'home')}"


# ---------- rebuild ALL derived stats from games + boxscores ----------
def rebuild_derived_stats():
    games_path = DATA_DIR / 'games.json'
    games = read_json(games_path, [])

    player_index = {}  # (player_id, team_id, season, type) -> {totals, games,...}
    records_index = defaultdict(list)  # (team_id, season, type, stat) -> list[record]

    for g in games:
        gid   = g.get('id')
        season = g.get('season')
        gtype  = g.get('type', 'regular')
        box_path_str = g.get('boxscore_json') or str(BOX_DIR / f"{gid}.json")
        box_path = Path(box_path_str)
        if not box_path.exists():
            continue
        bs = read_json(box_path, None)
        if not bs:
            continue

        date = bs.get('date') or g.get('date')
        home_team = bs.get('home_team')
        away_team = bs.get('away_team')

        for team_id in (home_team, away_team):
            if not team_id:
                continue
            team = bs.get('teams', {}).get(team_id)
            if not team:
                continue
            for p in team.get('players', []):
                pid = p.get('player_id')
                if not pid:
                    continue
                stats = dict(p.get('stats', {}))
                if 'reb' not in stats:
                    stats['reb'] = stats.get('oreb', 0) + stats.get('dreb', 0)

                key = (pid, team_id, season, gtype)
                rec = player_index.get(key)
                if not rec:
                    rec = {
                        'player_id': pid,
                        'team_id': team_id,
                        'season': season,
                        'type': gtype,
                        'games': 0,
                        'totals': {k: 0 for k in STAT_CATS}
                    }
                    player_index[key] = rec

                rec['games'] += 1
                for k in STAT_CATS:
                    v = stats.get(k, 0)
                    if isinstance(v, (int, float)):
                        rec['totals'][k] += v

                # single-game records tracking
                for k in STAT_CATS:
                    v = stats.get(k)
                    if not isinstance(v, (int, float)):
                        continue
                    idx_key = (team_id, season, gtype, k)
                    records_index[idx_key].append({
                        'player_id': pid,
                        'game_id': gid,
                        'date': date,
                        'team_id': team_id,
                        'season': season,
                        'type': gtype,
                        'stat': k,
                        'value': v
                    })

    # player_totals list
    player_totals = []
    for rec in player_index.values():
        games_n = max(1, rec['games'])
        avgs = {k: rec['totals'][k] / games_n for k in rec['totals']}
        player_totals.append({
            'player_id': rec['player_id'],
            'team_id': rec['team_id'],
            'season': rec['season'],
            'type': rec['type'],
            'games': rec['games'],
            'totals': rec['totals'],
            'averages': avgs
        })

    # team leaders per (team, season, type)
    leaders_by_group = {}
    for rec in player_totals:
        gkey = (rec['team_id'], rec['season'], rec['type'])
        group = leaders_by_group.setdefault(
            gkey,
            {
                'team_id': rec['team_id'],
                'season': rec['season'],
                'type': rec['type'],
                'leaders_per_game': {k: [] for k in STAT_CATS}
            }
        )
        for k in STAT_CATS:
            group['leaders_per_game'][k].append({
                'player_id': rec['player_id'],
                'value': rec['averages'][k],
                'games': rec['games']
            })
    team_leaders = []
    for group in leaders_by_group.values():
        for k in STAT_CATS:
            group['leaders_per_game'][k].sort(key=lambda x: x['value'], reverse=True)
        team_leaders.append(group)

    # team records – top 3 per stat
    team_records_map = {}
    for (team_id, season, gtype, stat), lst in records_index.items():
        lst_sorted = sorted(lst, key=lambda x: x['value'], reverse=True)
        key = (team_id, season, gtype)
        obj = team_records_map.setdefault(
            key,
            {'team_id': team_id, 'season': season, 'type': gtype, 'records': {}}
        )
        obj['records'][stat] = lst_sorted[:3]
    team_records = list(team_records_map.values())

    derived_dir = DATA_DIR / 'derived'
    derived_dir.mkdir(exist_ok=True)
    write_json(derived_dir / 'player_totals.json', player_totals)
    write_json(derived_dir / 'team_leaders.json', team_leaders)
    write_json(derived_dir / 'team_records.json', team_records)
    print('Rebuilt derived stats in data/derived/')


# ---------- CLI entry ----------
def main():
    ap = argparse.ArgumentParser(description='Parse Easy Stats HTML and rebuild derived stats.')
    ap.add_argument('html', help='path to exported HTML boxscore')
    ap.add_argument('--date', help='game date YYYY-MM-DD')
    ap.add_argument('--season', help='season label, e.g. 2025 or 2025-26')
    ap.add_argument('--type', choices=['regular','playoff','preseason'], help='game type')
    ap.add_argument('--away-team', help='away team name')
    ap.add_argument('--home-team', help='home team name')
    ap.add_argument('--away-score', type=int, help='away team score')
    ap.add_argument('--home-score', type=int, help='home team score')
    args = ap.parse_args()

    parsed = parse_easy_stats_html(args.html)

    def prompt(default, text):
        if default:
            s = input(f"{text} [{default}]: ").strip()
            return s or default
        else:
            s = input(f"{text}: ").strip()
            return s

    # date
    date_val = args.date or prompt(parsed['date'], 'Game date (YYYY-MM-DD)')
    try:
        datetime.strptime(date_val, '%Y-%m-%d')
    except Exception:
        print('Invalid date format; using parsed date', parsed['date'])
        date_val = parsed['date']

    # season (label, not parsed) – default current year from date
    current_year = datetime.strptime(date_val, '%Y-%m-%d').year
    season_default = args.season or str(current_year)
    season_val = prompt(season_default, 'Season label (e.g. 2025 or 2025-26)')

    # type (regular / playoff / preseason)
    type_default = args.type or 'regular'
    type_input = prompt(type_default, 'Game type (regular/playoff/preseason)')
    type_val = type_input.lower()
    if type_val not in ('regular','playoff','preseason'):
        print('Unknown type; defaulting to regular')
        type_val = 'regular'

    # teams & scores
    away_team_val = args.away_team or prompt(parsed.get('away_name') or 'Away', 'Away team name')
    home_team_val = args.home_team or prompt(parsed.get('home_name') or 'Home', 'Home team name')

    away_score_val = args.away_score
    if away_score_val is None:
        away_score_val = int(prompt(parsed.get('away_score') or '0', 'Away team score'))
    home_score_val = args.home_score
    if home_score_val is None:
        home_score_val = int(prompt(parsed.get('home_score') or '0', 'Home team score'))

    # build game id & boxscore JSON
    gid = build_game_id(date_val, away_team_val, home_team_val)
    box = {
        'game_id': gid,
        'date': date_val,
        'home_team': home_team_val,
        'away_team': away_team_val,
        'home_score': home_score_val,
        'away_score': away_score_val,
        'teams': parsed['teams_obj']
    }

    # save raw + boxscore
    raw_dest = RAW_DIR / Path(args.html).name
    raw_dest.write_text(Path(args.html).read_text(encoding='utf8'), encoding='utf8')
    box_path = BOX_DIR / f'{gid}.json'
    write_json(box_path, box)
    print('Wrote boxscore JSON:', box_path)

    # update games.json (with season & type)
    games_path = DATA_DIR / 'games.json'
    games = read_json(games_path, [])
    existing = next((g for g in games if g.get('id') == gid), None)
    game_meta = {
        'id': gid,
        'date': date_val,
        'season': season_val,
        'type': type_val,
        'home_team': home_team_val,
        'away_team': away_team_val,
        'home_score': home_score_val,
        'away_score': away_score_val,
        'boxscore_json': str(box_path),
        'venue': ''
    }
    if existing:
        existing.update(game_meta)
        print('Updated existing game in data/games.json')
    else:
        games.append(game_meta)
        print('Appended new game to data/games.json')
    write_json(games_path, games)

    # rebuild ALL derived stats after adding this game
    rebuild_derived_stats()

if __name__ == '__main__':
    main()
