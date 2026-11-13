# Neo4j — the site's data as a graph, and the path to a live site

Status 2026-11-10: **read API built (Phase 1), not yet hosted.** The CSVs/JSON in
`data/` are still the source of truth. The pages read the API in `api/` when it is
reachable (on localhost today) and `database.json` / `feed.json` otherwise. A local Neo4j holds a
full mirror built by `scripts/neo4j_migrate.py`. For how the data itself is produced,
see `MECHANISMS.md`.

---

## 1. The local test server

| | |
|---|---|
| Folder | `~/neo4j-geopolitics` (config, data, logs). Binaries run in place from Neo4j Desktop's download cache (Neo4j 2026.09.0 Enterprise + its bundled Java 21), so nothing was copied or installed. |
| Licence | Enterprise **evaluation**: a 30-day trial from 2026-11-04 (expires ~2026-12-04). Fine for testing, **not for the live site** (§4). |
| Browser | <http://127.0.0.1:7474>: user `neo4j`, password = `NEO4J_PASSWORD` in the gitignored `.env` |
| Bolt | `neo4j://127.0.0.1:7687` (what scripts and a future API use). Listens on localhost only. |
| Neo4j Desktop | Add a *remote connection* to `neo4j://127.0.0.1:7687` to browse it from Desktop. Desktop's own Start/Stop buttons don't control it. |
| Disk | ~100 MB (≈70 MB store + the latest transaction log). Query logging is off (Enterprise logs every query with its full parameters, ~90 MB per load) and only the latest transaction log is kept, because the server can always be rebuilt from the files. |
| Ports | 7474/7687, the defaults, so it can't run at the same time as a Desktop DBMS on those ports. |

```bash
source ~/neo4j-geopolitics/env.sh && "$NEO4J_HOME/bin/neo4j" start
```

```bash
source ~/neo4j-geopolitics/env.sh && "$NEO4J_HOME/bin/neo4j" stop
```

The server does not start again on its own after a reboot.

## 2. Loading and checking

```bash
python3 scripts/neo4j_migrate.py            # dry run: counts, dangling refs, type anomalies
python3 scripts/neo4j_migrate.py --load     # sync files → Neo4j, then compare counts
python3 scripts/neo4j_migrate.py --verify   # page-reproduction queries vs the files
```

- `--load` MERGEs every node and relationship on its key and stamps it with the run
  (`_load`). Afterwards it deletes anything left over from an older run, so the
  database **mirrors** the files. Re-running on unchanged files changes nothing.
  `--wipe` empties the database first; `--no-prune` keeps stale records.
- `--verify` runs the queries a database-backed site would need and checks each answer
  against the same thing computed from the files: every story's merged timeline
  count and last-news day (via `story_stats.compute`), story chips on feed rows,
  the UN story's `link_sources` rule, the newest 2,000 feed rows, the UN branches and
  their beat counts, incidents per operation, speech clusters/friendliness/mentions,
  UN reports per organ, and per-story source selections.

First load, 2026-11-04: **44,741 nodes / 50,910 relationships**, exactly the dry
run's numbers for every label and relationship type; all 15 verify checks passed.

### The model, briefly

Only references that literally exist in the data become relationships (id columns,
id lists, `parent_id`, `link_sources` names resolved by the source registry).
Countries, keywords, categories and entities stay list properties. The script's
docstring has the full table; the main paths are:

```
(StoryUpdate)-[:UPDATE_OF]->(Story)<-[:LINKED_TO]-(FeedItem)-[:FROM_SOURCE]->(Source)
(Story)-[:CHILD_OF]->(Story)                       branches (parent_id)
(Story)-[:SELECTED_SOURCE|EXCLUDED_SOURCE|ADDED_SOURCE|LINKS_SOURCE]->(Source)
(Incident)-[:PART_OF]->(Operation)<-[:LINKED_OPERATION]-(FeedItem)
(Speech)-[:PART_OF]->(Story)<-[:ANALYSIS_OF]-(SpeechAnalysis)<-[:PART_OF]-(SpeechCluster)<-[:IN_CLUSTER]-(Speech)
(Speech)-[:MENTIONS {via, stance, note}]->(Speech)
(UNReport)   (Video)-[:FROM_SOURCE]->(Source)   (StoryImage)   review logs
```

Example: one story's raw timeline (the API would apply the dedup rule from
`MECHANISMS.md` §4.3):

```cypher
MATCH (st:Story {story_id: 'st-20261103-united-nations'})
CALL (st) {
  MATCH (u:StoryUpdate)-[:UPDATE_OF]->(st) RETURN u.date AS day, u.headline AS head, 'beat' AS kind
  UNION ALL
  MATCH (f:FeedItem)-[:LINKED_TO]->(st) RETURN left(f.created_at, 10) AS day, coalesce(f.summary, f.full_text) AS head, 'feed' AS kind
}
RETURN day, kind, head ORDER BY day DESC LIMIT 50
```

Known gaps, all deliberate: `UNReport` has no edges, because a UN beat shares only a
URL with its report and you ruled out URL-based links. A YouTube beat likewise
has no edge to its `Video`. Mentions of 3 nations with no address (AF, MM, TW) are
skipped. Per-user overlays (follows, priority, overrides) live in each browser's
localStorage and are not in the repo, so they're not in the graph.

---

## 3. Moving to a live, database-backed site

The order is chosen so the site never breaks: the files stay the source of truth
until Neo4j has proved itself, and at every step the pages keep the `DataLayer`
contract (`js/data.js`), which is the only place they fetch data.

### Phase 0: mirror (now)

Add `python3 scripts/neo4j_migrate.py --load` after `build_db.py` in each of the
three routines (and the UN pull). Neo4j then tracks the files daily; `--verify`
becomes a check that fails loudly when they drift.

### Phase 1: a read API (pages read Neo4j) — built 2026-11-10

`api/` is a read-only FastAPI service over Neo4j. Every page asks it first and
falls back to the static files on its own, so the site never depends on it.

| Endpoint | Serves |
|---|---|
| `GET /api/bootstrap?scope=feed\|full` | the exact shapes of `feed.json` / `database.json`. This is what the DataLayer loads. |
| `GET /api/feed?before=&limit=&q=&story=` | the paged feed, newest first, past the 2,000-row cap. `q` uses the `feed_text` full-text index; pass `next` back as `before`. |
| `GET /api/stories` | the catalog, with `update_count` / `last_update_at` computed in the query (`story_stats`). |
| `GET /api/stories/{id}/timeline` | beats plus EVERY linked feed row, deduped on the server (a Python twin of `Util.buildStoryEntries()`), plus branches from `CHILD_OF`. |
| `GET /api/map` | incidents / operations / imagery / the map timeline |
| `GET /api/speeches/{session}` | `un_speeches/unga<N>.json`, reassembled from `SpeechAnalysis` + `Speech` + `SpeechCluster` |
| `GET /api/sources`, `/api/un/reports` | the source registry; UN reports, filterable by `branch` / `organ` |
| `GET /api/health`, `/api/docs` | liveness and the data's load stamp; interactive docs |

Each heavy payload is built once per data load and kept in memory (≈0.5 s to
build, ≈20 ms after). The cache key and `ETag` come from the newest `_load` stamp,
so a re-load invalidates it within 30 s and an unchanged page revalidates with a 304.
Derived fields (badge colours, `date_sort_value`, the map timeline, story counters)
come from importing `build_db.py` / `story_stats.py`, so they cannot drift from the static build.

**Frontend.** `js/api.js` picks the API: `http://127.0.0.1:8787` on localhost,
`PRODUCTION_BASE` elsewhere (empty until the API is hosted, so the live site keeps
using the static files). `js/data.js` (`loadFeed` / `loadAll`) and `js/speeches.js`
try the API first. If the call fails, times out or returns a 5xx, they load the
static file, log one warning, and skip the API for that tab for 5 minutes. Per-browser
overrides: `?api=off`, `?api=prod`, `?api=local`, `?api=auto`. `?api=<url>` works on
localhost only, so a link can't point a live-site visitor at another server.
`Api.feedPage()` and `Api.storyTimeline()` are ready for the pages to adopt next.

**Run it locally** (Neo4j running and loaded):

```bash
api/.venv/bin/uvicorn main:app --app-dir api --port 8787 --reload
```

or start the `api` entry in `.claude/launch.json`. To set up the virtualenv:
`uv venv api/.venv --python 3.12 && VIRTUAL_ENV=api/.venv uv pip install -r api/requirements.txt`.

**Check it serves what the files would:**

```bash
api/.venv/bin/python api/parity_check.py
```

It rebuilds `feed.json` / `database.json` from the current files into a temp dir
(`data/` is untouched) and diffs every section with the API's version, plus
`unga81.json`. On 2026-11-10 every section matched, rows and order. The one
expected difference: `build_db.py`'s SQLite `tweets` table keys on `created_at`
alone, so the static files **silently drop 2,729 of 25,719 feed rows** that share
a timestamp (wire pulls stamp whole batches alike), 205 of them inside the newest
2,000. The graph keeps them, so the API shows them.

### Phase 2: routines write to Neo4j (files become exports)

The pipeline already funnels every write through a few sanctioned scripts
(`MECHANISMS.md` §9.1). Each of them gets a Neo4j write through one shared module
(`scripts/graph_store.py`, using the same keys as `LABEL_KEYS`):

| Writer | Writes |
|---|---|
| `sync_enriched_to_intel.py`, `apply_deep_enrichment.py` | `FeedItem` (store `feed_id` as a real column) |
| `link_stories.py` | `LINKED_TO` edges |
| `promote_incidents.py` | `Incident`, `PART_OF` |
| `add_story_update.py` (and the scripts that call it) | `StoryUpdate`, `UPDATE_OF`, `FROM_SOURCE` |
| `source_registry.py --upsert` | `Source` |
| `import_watchlist.py` | `Story`, `CHILD_OF`, source edges |
| `pull_un_daily.py` | `UNReport` |
| `pull_youtube.py`, `link_youtube.py` | `Video` |

1. **Dual-write.** Each writer writes its CSV *and* Neo4j. `--verify` runs nightly; any
   drift is a bug in a writer.
2. **Flip.** Neo4j becomes the source of truth. The CSVs/JSON become a nightly export
   committed to git as history and backup. `build_db.py` reads Neo4j instead of
   CSVs, or retires once every page uses the API.
3. **Gains.** Each write is a transaction rather than a whole-file rewrite, which ends
   the lost-update race between overlapping routines on `story_updates.csv`.
   Counters are computed in queries, so they can't drift. The beat writers can
   record `report_id` / `video_id`, so UN and YouTube beats get real edges to their
   `UNReport` / `Video`.
4. **Users, last.** Once there are accounts: `(:User)-[:FOLLOWS {rank}]->(:Story)`
   plus override properties replace the localStorage user doc, and mark-important /
   track / reorder become authenticated `POST`s to the API.

Routines get a separate write user; the API's user stays read-only. (Community
Edition has a single admin user, so there the split is enforced at the API layer.)

---

## 4. Hosting it 24/7

The pages stay on GitHub Pages. The API needs its own host with **HTTPS**,
because an https page can't call an http API. Once it's up, set
`PRODUCTION_BASE` in `js/api.js` to its origin, bump `api.js?v=` in the five
pages, and push. The API already allows `https://chiragr5241.github.io` (CORS);
add other origins with `API_CORS_ORIGINS`.

Licensing decides where Neo4j runs. The local Enterprise **evaluation** licence
(expires ~2026-12-04) is not for production. Everything here works on Community
Edition.

### Option A: one small server (cheapest; ~$5–10/month)

A VPS with ≥ 2 GB RAM (e.g. Hetzner CX22, DigitalOcean, Lightsail) runs
`docker-compose.yml`: Neo4j 5.26 Community, the API and Caddy, which gets
the TLS certificate.

1. Point a DNS name (e.g. `api.yourdomain.com`) at the server.
2. On the server: install Docker, clone the repo, and create `.env` with
   `NEO4J_PASSWORD`, `API_DOMAIN` (and optionally `API_CORS_ORIGINS`).
3. `docker compose up -d --build`
4. Load the data from your machine through an SSH tunnel. Bolt is published on
   the server's localhost only:

   ```bash
   ssh -N -L 17687:localhost:7687 you@server &
   NEO4J_URI=bolt://127.0.0.1:17687 NEO4J_USERNAME=neo4j NEO4J_PASSWORD=… python3 scripts/neo4j_migrate.py --load
   ```

   The routines do the same after `build_db.py` (Phase 0).
5. Check `https://api.yourdomain.com/api/health`.

Backups and updates are yours: `docker compose exec neo4j neo4j-admin database dump`
needs the database stopped on Community. While the files are the source of truth,
re-running `--load` is the backup.

### Option B: managed (least to operate)

- **Neo4j AuraDB** for the database. The data uses ~24% of the Free tier's node
  limit, but Free instances pause when idle, so a 24/7 site wants a paid tier.
  Aura's `neo4j+s://` URI works from the routines directly, with no tunnel.
- **The API** as a container on Fly.io, Render, Railway or Cloud Run, built from
  `api/Dockerfile` (build context = repo root; `PORT` is honoured). Set
  `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` (and `NEO4J_DATABASE` if not
  `neo4j`) as secrets. Platforms that sleep idle services add a cold start, which
  the page's 12 s timeout absorbs by falling back to the static files.

Give the API a **read-only** database user where the edition allows it (Aura /
Enterprise). Community has one admin user, but the API only ever sends reads
(read routing, no write queries).

### Moving the data

Rebuilding the database on a new server takes one command while the files are the
source of truth: point `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` at it and
run `neo4j_migrate.py --load`. After Phase 2's flip, move it with
`neo4j-admin database dump` / `load` instead.
