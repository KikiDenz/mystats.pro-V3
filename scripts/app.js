// ==============================
// mystats.pro SPA
// ==============================
const DATA_PATH = "data";
const app = document.getElementById("app");

const cache = {};

// ---------- generic loaders ----------
async function loadJSON(path) {
  try {
    const res = await fetch(path + `?v=${Date.now()}`); // small cache buster
    if (!res.ok) throw new Error("HTTP " + res.status + " for " + path);
    return await res.json();
  } catch (e) {
    console.error("loadJSON error:", path, e);
    return null;
  }
}

// base JSON (teams, players, games)
async function getData(name) {
  if (cache[name]) return cache[name];
  const data = await loadJSON(`${DATA_PATH}/${name}.json`);
  cache[name] = data || [];
  return cache[name];
}

// derived JSON (player_totals, team_leaders, team_records)
async function getDerived(name) {
  const key = `derived_${name}`;
  if (cache[key]) return cache[key];
  const data = await loadJSON(`${DATA_PATH}/derived/${name}.json`);
  cache[key] = data || [];
  return cache[key];
}

// players index (id -> player object)
async function getPlayersIndex() {
  if (cache.playersIndex) return cache.playersIndex;
  const players = await getData("players");
  const idx = {};
  players.forEach((p) => {
    idx[p.id] = p;
  });
  cache.playersIndex = idx;
  return idx;
}

// simple DOM helpers
const q = (sel, parent = document) => parent.querySelector(sel);
const qAll = (sel, parent = document) =>
  Array.from(parent.querySelectorAll(sel));

function setAccentColor(hex) {
  document.documentElement.style.setProperty(
    "--accent",
    hex || "#0084ff"
  );
}

// small helpers
function teamMatches(metaTeam, teamObj) {
  if (!metaTeam || !teamObj) return false;
  return metaTeam === teamObj.id || metaTeam === teamObj.name;
}

function fmt(num, digits = 1) {
  if (num === undefined || num === null || isNaN(num)) return "0.0";
  return Number(num).toFixed(digits);
}

// ---------- router ----------
async function route() {
  const hash = location.hash.replace(/^#/, "");
  if (!hash || hash === "/") return renderHome();

  const parts = hash.split("/").filter(Boolean);
  if (parts[0] === "team" && parts[1]) return renderTeam(parts[1]);
  if (parts[0] === "player" && parts[1]) return renderPlayer(parts[1]);
  if (parts[0] === "boxscore" && parts[1]) return renderBoxscore(parts[1]);

  // fallback
  return renderHome();
}

window.addEventListener("hashchange", route);

// ==============================
// Home page
// ==============================
async function renderHome() {
  const teams = await getData("teams");
  const players = await getData("players");

  const html = `
    <div class="container">
      <div class="header">
        <img class="logo" src="assets/logo-small.png" alt="mystats.pro">
        <div>
          <div class="title">mystats.pro</div>
          <div class="subtitle">StatMuse-style pages for your basketball runs.</div>
        </div>
      </div>

      <div class="h3-label">Teams</div>
      <div class="tiles">
        ${teams
          .map(
            (t) => `
          <a class="card team-tile row-link" href="#/team/${t.id}">
            <span class="badge" style="background-image:url('${
              t.logo || "assets/team-placeholder.png"
            }');background-size:cover;"></span>
            <div>
              <div style="font-weight:700">${t.name}</div>
              <div class="small-muted">${
                t.season_meta?.current_season || ""
              } ${t.season_meta?.league ? "· " + t.season_meta.league : ""}</div>
            </div>
          </a>
        `
          )
          .join("")}
      </div>

      <div class="h3-label">Players</div>
      <div class="tiles">
        ${players
          .map(
            (p) => `
          <a class="card player-tile row-link" href="#/player/${p.id}">
            <img src="${
              p.images?.portrait || "assets/player-placeholder.png"
            }" alt="${p.display_name}">
            <div>
              <div style="font-weight:700">${p.display_name} ${
              p.number ? `<span class="small-muted">#${p.number}</span>` : ""
            }</div>
              <div class="small-muted">
                ${p.position || ""}${
              (p.position && p.teams?.length) ? " · " : ""
            }${p.teams?.length ? `${p.teams.length} team(s)` : ""}
              </div>
            </div>
          </a>
        `
          )
          .join("")}
      </div>

      <div class="footer">
        Upload new Easy Stats HTML → run parser → push to GitHub → stats auto-update.
      </div>
    </div>
  `;

  app.innerHTML = html;
}

// ==============================
// Team page
// ==============================
async function renderTeam(teamIdParam) {
  const teams = await getData("teams");
  const players = await getData("players");
  const games = await getData("games");

  // teamIdParam is t.id from home tiles. Also allow matching by name.
  let team =
    teams.find((t) => t.id === teamIdParam) ||
    teams.find((t) => t.name === teamIdParam);

  if (!team) {
    app.innerHTML = `<div class="container"><div class="card">Team not found.</div></div>`;
    return;
  }

  setAccentColor(team.color || "#0084ff");

  // all games this team played in
  const teamGames = games
    .filter(
      (g) =>
        teamMatches(g.home_team, team) ||
        teamMatches(g.away_team, team)
    )
    .sort((a, b) => new Date(b.date) - new Date(a.date));

  const last5 = teamGames.slice(0, 5);

  const html = `
    <div class="container">
      <div class="header header--team">
        <img class="logo" src="${
          team.logo || "assets/team-placeholder.png"
        }" alt="${team.name}">
        <div class="header-main">
          <div class="header-top-row">
            <div class="title">${team.name}</div>
            ${
              team.season_meta?.league
                ? `<span class="chip chip-light">${team.season_meta.league}</span>`
                : ""
            }
          </div>
          <div class="subtitle">
            ${team.season_meta?.current_season || ""}
          </div>
        </div>
      </div>

      <div class="tabs">
        <div class="tab active" data-tab="overview">Overview</div>
        <div class="tab" data-tab="roster">Roster</div>
        <div class="tab" data-tab="games">Games</div>
        <div class="tab" data-tab="leaders">Team Leaders</div>
        <div class="tab" data-tab="records">Records</div>
      </div>

      <div id="team-tab-content" class="section"></div>
    </div>
  `;

  app.innerHTML = html;

  const tabs = qAll(".tab");
  tabs.forEach((t) =>
    t.addEventListener("click", () => {
      tabs.forEach((x) => x.classList.toggle("active", x === t));
      loadTeamTab(t.dataset.tab);
    })
  );

  loadTeamTab("overview");

  async function loadTeamTab(tabName) {
    const container = q("#team-tab-content");
    if (!container) return;

    if (tabName === "overview") {
      container.innerHTML = `
        <div class="card">
          <div class="small-muted">Last 5 games</div>
          <div class="list" style="margin-top:6px">
          ${last5
            .map((g) => {
              const isHome = teamMatches(g.home_team, team);
              const oppName = isHome ? g.away_team : g.home_team;
              const score = `${g.home_score ?? "-"} – ${g.away_score ?? "-"}`;
              const result =
                typeof g.home_score === "number" &&
                typeof g.away_score === "number"
                  ? (isHome
                      ? g.home_score > g.away_score
                      : g.away_score > g.home_score)
                    ? "W"
                    : "L"
                  : "";
              const badge =
                result === "W"
                  ? '<span class="badge-win">W</span>'
                  : result === "L"
                  ? '<span class="badge-loss">L</span>'
                  : "";
              return `
              <a class="row-link" href="#/boxscore/${g.id}">
                <div class="card" style="margin-bottom:6px">
                  <div style="display:flex;justify-content:space-between;align-items:center;">
                    <div>
                      <div style="font-weight:600">${g.date}</div>
                      <div class="small-muted">${isHome ? "vs" : "@"} ${oppName}</div>
                    </div>
                    <div style="text-align:right">
                      <div>${score}</div>
                      <div>${badge}</div>
                    </div>
                  </div>
                </div>
              </a>`;
            })
            .join("")}
          </div>
        </div>
      `;

      // leaders summary using derived
      const teamLeaders = await getDerived("team_leaders");
      const keys = [team.id, team.name];
      const season = team.season_meta?.current_season;
      let group =
        teamLeaders.find(
          (g) =>
            keys.includes(g.team_id) &&
            (!season || g.season ==if (group) {
        const ptsLead = group.leaders_per_game.pts?.[0];
        const rebLead = group.leaders_per_game.reb?.[0];
        const astLead = group.leaders_per_game.ast?.[0];
        const playersIndex = await getPlayersIndex();

        const label = (pid) =>
          playersIndex[pid]?.display_name || pid || "—";
        const avatar = (pid) =>
          playersIndex[pid]?.images?.portrait ||
          "assets/player-placeholder.png";

        const leadersHtml = `
          <div class="section">
            <div class="h3-label">Per-Game Leaders${
              group.season ? " – " + group.season : ""
            }</div>
            <div class="tiles">
              ${
                ptsLead
                  ? `
              <div class="card card--bright leader-card">
                <div class="small">PPG</div>
                <div class="leader-card-value">${fmt(ptsLead.value)}</div>
                <img class="leader-card-avatar" src="${avatar(
                  ptsLead.player_id
                )}" alt="${label(ptsLead.player_id)}">
                <div class="small-muted">${label(ptsLead.player_id)}</div>
              </div>`
                  : ""
              }
              ${
                rebLead
                  ? `
              <div class="card card--bright leader-card">
                <div class="small">RPG</div>
                <div class="leader-card-value">${fmt(rebLead.value)}</div>
                <img class="leader-card-avatar" src="${avatar(
                  rebLead.player_id
                )}" alt="${label(rebLead.player_id)}">
                <div class="small-muted">${label(rebLead.player_id)}</div>
              </div>`
                  : ""
              }
              ${
                astLead
                  ? `
              <div class="card card--bright leader-card">
                <div class="small">APG</div>
                <div class="leader-card-value">${fmt(astLead.value)}</div>
                <img class="leader-card-avatar" src="${avatar(
                  astLead.player_id
                )}" alt="${label(astLead.player_id)}">
                <div class="small-muted">${label(astLead.player_id)}</div>
              </div>`
                  : ""
              }
            </div>
          </div>
        `;

        container.insertAdjacentHTML("beforeend", leadersHtml);
      }
v>
                <div class="small-muted">${label(astLead?.player_id)}</div>
              </div>
            </div>
          </div>
        `
        );
      }
    } else if (tabName === "roster") {
      const rosterPlayers = players.filter((p) =>
        (p.teams || []).includes(team.id)
      );
      container.innerHTML = `
        <div class="h3-label">Roster</div>
        <div class="tiles">
          ${rosterPlayers
            .map(
              (p) => `
            <a href="#/player/${p.id}" class="card player-tile row-link">
              <img src="${
                p.images?.portrait || "assets/player-placeholder.png"
              }" alt="${p.display_name}">
              <div>
                <div style="font-weight:700">${p.display_name} ${
                p.number ? `<span class="small-muted">#${p.number}</span>` : ""
              }</div>
                <div class="small-muted">${p.position || ""}</div>
              </div>
            </a>
          `
            )
            .join("")}
        </div>
      `;
    } else if (tabName === "games") {
      container.innerHTML = `
        <div class="filter-row">
          <select id="games-season"><option value="all">All seasons</option></select>
          <select id="games-type">
            <option value="all">All</option>
            <option value="regular">Regular</option>
            <option value="playoff">Playoff</option>
            <option value="preseason">Preseason</option>
          </select>
        </div>
        <div id="games-table" class="scroll-x"></div>
      `;

      const seasonSelect = q("#games-season");
      const seasons = Array.from(
        new Set(teamGames.map((g) => g.season).filter(Boolean))
      )
        .sort()
        .reverse();
      seasons.forEach((s) =>
        seasonSelect.insertAdjacentHTML(
          "beforeend",
          `<option value="${s}">${s}</option>`
        )
      );

      seasonSelect.addEventListener("change", updateTable);
      q("#games-type").addEventListener("change", updateTable);

      updateTable();

      function updateTable() {
        const seasonVal = seasonSelect.value;
        const typeVal = q("#games-type").value;

        const filtered = teamGames.filter(
          (g) =>
            (seasonVal === "all" || g.season === seasonVal) &&
            (typeVal === "all" || g.type === typeVal)
        );

        q("#games-table").innerHTML = `
          <table class="table card">
            <thead>
              <tr><th>Date</th><th>Opponent</th><th>Score</th><th>Type</th></tr>
            </thead>
            <tbody>
              ${filtered
                .map((g) => {
                  const isHome = teamMatches(g.home_team, team);
                  const opp = isHome ? g.away_team : g.home_team;
                  const score = `${g.home_score ?? "-"} – ${
                    g.away_score ?? "-"
                  }`;
                  return `
                    <tr>
                      <td><a href="#/boxscore/${g.id}">${g.date}</a></td>
                      <td>${opp || ""}</td>
                      <td>${score}</td>
                      <td>${g.type || ""}</td>
                    </tr>
                  `;
                })
                .join("")}
            </tbody>
          </table>
        `;
      }
    } else if (tabName === "leaders") {
      const leadersAll = await getDerived("team_leaders");
      const keys = [team.id, team.name];
      const season = team.season_meta?.current_season;
      const playersIndex = await getPlayersIndex();

      const group = leadersAll.find(
        (g) =>
          keys.includes(g.team_id) &&
          (!season || g.season === season) &&
          g.type === "regular"
      );

      if (!group) {
        container.innerHTML =
          '<div class="card small-muted">No leader data available for this team.</div>';
        return;
      }

      const label = (pid) =>
        playersIndex[pid]?.display_name || pid || "—";

      const statNames = Object.keys(group.leaders_per_game);

      container.innerHTML = `
        <div class="h3-label">Team Leaders${
          group.season ? " – " + group.season : ""
        } (per game)</div>
        ${statNames
          .map((stat) => {
            const arr = group.leaders_per_game[stat].slice(0, 10);
            return `
              <div class="card">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                  <strong>${stat.toUpperCase()}</strong>
                  <span class="small-muted">${arr.length} players</span>
                </div>
                <div class="list" style="margin-top:6px">
                  ${arr
                    .map(
                      (row, i) => `
                        <div style="display:flex;justify-content:space-between;">
                          <div>${i + 1}. ${label(row.player_id)}</div>
                          <div class="small-muted">${fmt(row.value)}</div>
                        </div>
                      `
                    )
                    .join("")}
                </div>
              </div>
            `;
          })
          .join("")}
      `;
    } else if (tabName === "records") {
      const recordsAll = await getDerived("team_records");
      const keys = [team.id, team.name];
      const season = team.season_meta?.current_season;
      const playersIndex = await getPlayersIndex();

      const recGroup = recordsAll.find(
        (r) =>
          keys.includes(r.team_id) &&
          (!season || r.season === season) &&
          r.type === "regular"
      );

      if (!recGroup) {
        container.innerHTML =
          '<div class="card small-muted">No single-game records for this team yet.</div>';
        return;
      }

      const rows = Object.entries(recGroup.records)
        .map(([stat, arr]) => {
          return `
          <div class="card">
            <strong>${stat.toUpperCase()}</strong>
            ${arr
              .map(
                (r, i) => `
              <div style="margin-top:6px">
                <div><strong>${i + 1}.</strong> ${
                  playersIndex[r.player_id]?.display_name || r.player_id
                } – ${r.value}</div>
                <div class="small-muted">${r.date}</div>
              </div>
            `
              )
              .join("")}
          </div>
        `;
        })
        .join("");

      container.innerHTML = `
        <div class="h3-label">Single-Game Records${
          recGroup.season ? " – " + recGroup.season : ""
        }</div>
        ${rows}
      `;
    }
  }
}

// ==============================
// Player page
// ==============================
async function renderPlayer(playerId) {
  const players = await getData("players");
  const teams = await getData("teams");

  const player = players.find((p) => p.id === playerId);
  if (!player) {
    app.innerHTML = `<div class="container"><div class="card">Player not found.</div></div>`;
    return;
  }

  const primaryTeam =
    (player.teams || [])
      .map((tid) => teams.find((t) => t.id === tid || t.name === tid))
      .find(Boolean) || teams[0];

  setAccentColor(primaryTeam?.color || "#0084ff");

  const html = `
    <div class="container">
      <div class="header header--team">
        <img class="logo" src="${
          player.images?.portrait || "assets/player-placeholder.png"
        }" alt="${player.display_name}">
        <div class="header-main">
          <div class="header-top-row">
            <div class="title">${player.display_name} ${
    player.number ? `<span class="small-muted">#${player.number}</span>` : ""
  }</div>
            ${
              primaryTeam
                ? `<span class="chip chip-light">${primaryTeam.name}</span>`
                : ""
            }
          </div>
          <div class="subtitle">
            ${(player.position || "") +
              (player.height_cm ? ` · ${player.height_cm} cm` : "")}
          </div>
        </div>
      </div>

      <div class="tabs">
        <div class="tab active" data-tab="overview">Overview</div>
        <div class="tab" data-tab="stats">Stats</div>
        <div class="tab" data-tab="games">Games</div>
        <div class="tab" data-tab="leader-rank">Team Leader Rankings</div>
        <div class="tab" data-tab="records">Records Held</div>
      </div>

      <div id="player-tab-content" class="section"></div>
    </div>
  `;

  app.innerHTML = html;

  const tabs = qAll(".tab");
  tabs.forEach((t) =>
    t.addEventListener("click", () => {
      tabs.forEach((x) => x.classList.toggle("active", x === t));
      loadPlayerTab(t.dataset.tab);
    })
  );

  loadPlayerTab("overview");

  async function loadPlayerTab(tabName) {
    const container = q("#player-tab-content");
    if (!container) return;

    if (tabName === "overview") {
      const totals = await getDerived("player_totals");
      const entries = totals.filter((e) => e.player_id === playerId);

      const regular = entries.filter((e) => e.type === "regular");
      const latest =
        regular.sort((a, b) => ("" + b.season).localeCompare("" + a.season))[0] ||
        entries[0];

      const avg = latest?.averages || {};

      container.innerHTML = `
        <div class="card card--bright">
          <div class="small">Current season${
            latest ? ` – ${latest.season} (${latest.type})` : ""
          }</div>
          <div style="margin-top:4px;font-size:1.6rem;font-weight:700">${fmt(
            avg.pts
          )} PPG</div>
          <div class="small-muted">
            ${fmt(avg.reb)} RPG • ${fmt(avg.ast)} APG
          </div>
          <div class="small-muted" style="margin-top:4px">
            Games: ${latest?.games || 0}
          </div>
        </div>
      `;
    } else if (tabName === "stats") {
      const totals = await getDerived("player_totals");
      const rows = totals.filter((e) => e.player_id === playerId);

      if (!rows.length) {
        container.innerHTML =
          '<div class="card small-muted">No season stats yet.</div>';
        return;
      }

      container.innerHTML = `
        <div class="h3-label">Season Averages</div>
        <div class="list">
          ${rows
            .map(
              (rec) => `
            <div class="card">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <div><strong>${rec.season}</strong> · ${rec.type}</div>
                <div class="small-muted">${rec.games} games</div>
              </div>
              <div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:8px;">
                <span class="stat-pill">PTS ${fmt(rec.averages.pts)}</span>
                <span class="stat-pill">REB ${fmt(rec.averages.reb)}</span>
                <span class="stat-pill">AST ${fmt(rec.averages.ast)}</span>
                <span class="stat-pill">STL ${fmt(rec.averages.stl)}</span>
                <span class="stat-pill">BLK ${fmt(rec.averages.blk)}</span>
              </div>
            </div>
          `
            )
            .join("")}
        </div>
      `;
    } else if (tabName === "games") {
      const logs = await loadPlayerGameLogs(playerId);
      const seasons = Array.from(new Set(logs.map((l) => l.season))).sort(
        (a, b) => ("" + b).localeCompare("" + a)
      );

      container.innerHTML = `
        <div class="filter-row">
          <select id="player-games-season">
            <option value="all">All seasons</option>
            ${seasons
              .map((s) => `<option value="${s}">${s}</option>`)
              .join("")}
          </select>
          <select id="player-games-type">
            <option value="all">All</option>
            <option value="regular">Regular</option>
            <option value="playoff">Playoff</option>
            <option value="preseason">Preseason</option>
          </select>
        </div>
        <div id="player-games-table" class="scroll-x"></div>
      `;

      q("#player-games-season").addEventListener("change", update);
      q("#player-games-type").addEventListener("change", update);
      update();

      function update() {
        const sVal = q("#player-games-season").value;
        const tVal = q("#player-games-type").value;

        const filtered = logs.filter(
          (g) =>
            (sVal === "all" || g.season === sVal) &&
            (tVal === "all" || g.type === tVal)
        );

        q("#player-games-table").innerHTML = `
          <table class="table card">
            <thead>
              <tr><th>Date</th><th>Team</th><th>Opp</th><th>PTS</th><th>REB</th><th>AST</th></tr>
            </thead>
            <tbody>
              ${filtered
                .map(
                  (r) => `
                <tr>
                  <td><a href="#/boxscore/${r.game_id}">${r.date}</a></td>
                  <td>${r.team}</td>
                  <td>${r.opp}</td>
                  <td>${r.stats.pts || 0}</td>
                  <td>${r.stats.reb || 0}</td>
                  <td>${r.stats.ast || 0}</td>
                </tr>
              `
                )
                .join("")}
            </tbody>
          </table>
        `;
      }
    } else if (tabName === "leader-rank") {
      const teamLeaders = await getDerived("team_leaders");
      const playersIndex = await getPlayersIndex();

      const myTeams = player.teams || [];
      let html = `<div class="h3-label">Team Leader Rankings</div>`;

      myTeams.forEach((tid) => {
        const groups = teamLeaders.filter(
          (g) => g.team_id === tid && g.type === "regular"
        );
        if (!groups.length) return;
        const group = groups.sort((a, b) =>
          ("" + b.season).localeCompare("" + a.season)
        )[0];

        html += `<div class="card">
          <div><strong>${tid}</strong> ${
          group.season ? `<span class="small-muted">(${group.season})</span>` : ""
        }</div>`;

        Object.entries(group.leaders_per_game).forEach(([stat, arr]) => {
          const idx = arr.findIndex((row) => row.player_id === playerId);
          html += `
            <div style="display:flex;justify-content:space-between;margin-top:4px;">
              <div>${stat.toUpperCase()}</div>
              <div class="small-muted">${
                idx >= 0 ? "#" + (idx + 1) : "—"
              }</div>
            </div>`;
        });

        html += `</div>`;
      });

      container.innerHTML =
        html ||
        '<div class="card small-muted">No leader rankings for this player yet.</div>';
    } else if (tabName === "records") {
      const teamRecords = await getDerived("team_records");
      let html = `<div class="h3-label">Records Held</div>`;

      teamRecords.forEach((rec) => {
        Object.entries(rec.records).forEach(([stat, arr]) => {
          const mine = arr.filter((r) => r.player_id === playerId);
          if (!mine.length) return;

          html += `
            <div class="card">
              <div><strong>${stat.toUpperCase()}</strong> <span class="small-muted">· ${rec.team_id} · ${rec.season}</span></div>
              ${mine
                .map(
                  (r) => `
                <div style="margin-top:6px">
                  <div><strong>${r.value}</strong></div>
                  <div class="small-muted">${r.date}</div>
                </div>
              `
                )
                .join("")}
            </div>
          `;
        });
      });

      container.innerHTML =
        html ||
        '<div class="card small-muted">This player does not hold any records yet.</div>';
    }
  }
}

// ==============================
// Boxscore page
// ==============================
async function renderBoxscore(gameId) {
  const games = await getData("games");
  const game = games.find((g) => g.id === gameId);
  if (!game) {
    app.innerHTML = `<div class="container"><div class="card">Game not found.</div></div>`;
    return;
  }

  const box =
    (game.boxscore_json &&
      (await loadJSON(
        typeof game.boxscore_json === "string"
          ? game.boxscore_json
          : game.boxscore_json.path
      ))) ||
    (await loadJSON(`${DATA_PATH}/boxscores/${gameId}.json`));

  if (!box) {
    app.innerHTML = `<div class="container"><div class="card small-muted">Boxscore JSON not found – run the parser for this game.</div></div>`;
    return;
  }

  setAccentColor("#0084ff");

  const homeTeamName = box.home_team;
  const awayTeamName = box.away_team;

  function renderTeamBlock(teamName) {
    const teamData = box.teams[teamName] || {};
    const players = teamData.players || [];
    return `
      <div>
        <div class="card" style="margin-top:10px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
            <div style="font-weight:600">${teamName}</div>
            <div class="small-muted">PTS ${teamData.team_totals?.pts ?? ""}</div>
          </div>
          <div class="scroll-x">
              <table class="table">
                <thead>
                  <tr>
                    <th>#</th><th>Player</th><th>PTS</th><th>REB</th><th>AST</th>
                    <th>FG</th><th>3PT</th><th>FT</th>
                  </tr>
                </thead>
                <tbody>
                  ${players
                    .map((p) => {
                      const s = p.stats || {};
                      const fg = `${s.fgm || 0}/${s.fga || 0}`;
                      const th = `${s.fg3m || 0}/${s.fg3a || 0}`;
                      const ft = `${s.ftm || 0}/${s.fta || 0}`;
                      return `
                      <tr>
                        <td>${p.number || ""}</td>
                        <td><a href="#/player/${p.player_id}">${p.name || p.player_id}</a></td>
                        <td>${s.pts ?? ""}</td>
                        <td>${s.reb ?? s.oreb + (s.dreb || 0) || ""}</td>
                        <td>${s.ast ?? ""}</td>
                        <td>${fg}</td>
                        <td>${th}</td>
                        <td>${ft}</td>
                      </tr>
                    `;
                    })
                    .join("")}
                </tbody>
              </table>
            </div>
        </div>
      </div>
    `;
  }

  app.innerHTML = `
    <div class="container">
      <div class="header">
        <div>
          <div class="title">${awayTeamName} ${box.away_score ?? ""} @ ${homeTeamName} ${box.home_score ?? ""}</div>
          <div class="subtitle">${box.date || game.date} · ${game.type || ""} · ${game.venue || ""}</div>
        </div>
      </div>
      <div class="section">
        ${renderTeamBlock(homeTeamName)}
        ${renderTeamBlock(awayTeamName)}
      </div>
    </div>
  `;
}

// ==============================
// Stats helpers that still scan boxscores
// ==============================
async function loadPlayerGameLogs(playerId) {
  const games = await getData("games");
  const logs = [];

  for (const g of games) {
    const box =
      (g.boxscore_json &&
        (await loadJSON(
          typeof g.boxscore_json === "string"
            ? g.boxscore_json
            : g.boxscore_json.path
        ))) ||
      (await loadJSON(`${DATA_PATH}/boxscores/${g.id}.json`));

    if (!box || !box.teams) continue;

    for (const teamId of Object.keys(box.teams)) {
      const teamBlock = box.teams[teamId];
      for (const p of teamBlock.players || []) {
        if (p.player_id === playerId) {
          const stats = Object.assign({}, p.stats);
          if (stats.reb === undefined) {
            stats.reb = (stats.oreb || 0) + (stats.dreb || 0);
          }
          logs.push({
            game_id: g.id,
            date: box.date || g.date,
            season: g.season,
            type: g.type,
            team: teamId,
            opp: teamId === g.home_team ? g.away_team : g.home_team,
            stats
          });
        }
      }
    }
  }

  return logs.sort((a, b) => new Date(b.date) - new Date(a.date));
}

// ==============================
// boot
// ==============================
route();
