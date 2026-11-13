# How the site works — every mechanism in one place

OSINT Daily is a static site (no server, no build step) published from `main` via
GitHub Pages. Everything dynamic happens **before** publish: Python scripts, run by
three daily scheduled agent routines, turn raw sources into CSVs and then into two
JSON files the pages read. This document walks the whole chain — sources → data →
stories → pages — and lists the rules that are easy to break.

Last revised 2026-11-03.

---

## 1. The big picture

```
 SOURCES                      CANONICAL DATA (data/)            PUBLISHED JSON         PAGES
 ───────                      ──────────────────────            ──────────────         ─────
 Spectator Index API ─┐
 RSS wires + GDELT ───┼─► raw_data/ ─► spectator_enriched.csv ─► intel_feed.csv ─┐
                      │                (base / deep tiers)        (+ linked_story_ids)
                      │                                           incidents.csv ──┤
 YouTube channels ────────► youtube_videos.csv (hidden) ──────┐                   │
 UN press + UN News ──────► un_daily/reports.csv ─────────────┤                   ├─► build_db.py ─► database.json ─► map.html
 Agent WebSearch ─────────────────────────────────────────────┴─► story_updates.csv┤                  feed.json ─────► index.html
                                                                  watchlist.json ─┤                                  feed.html
                                                                  sources.csv ────┤                                  tracker.html
                                                                  story_images.csv┘                                  speeches.html
 UN YouTube / press ──────► un_speeches/unga81/ ─► unga81.json ─────────────────────────────────────────────────────► speeches.html
```

- **`database.json`** (v8) — everything: incidents, operations, imagery, the newest
  2,000 feed rows, watchlist, story updates, story images, sources, timeline meta.
  The map reads this.
- **`feed.json`** — the same minus the incident data; the news pages read this.
  `build_db.py` writes **both**; a routine that commits one must commit the other
  or a page goes stale.
- Pages fetch these with `js/data.js` (`DataLayer.loadAll()` / `loadFeed()`); paths
  live in `js/config.js` → `DATA_SOURCES`. If `database.json` is missing, the map
  falls back to the individual CSVs.

---

## 2. Pages

| Page | Nav label | Script(s) | What it shows |
|---|---|---|---|
| `index.html` | Tracker | `js/home.js` | Main page. Every **active tracked story** as an image tile in the user's priority order (first = 2×2 lead tile), backfilled with top feed items up to 6 tiles, then the rest-of-news list. |
| `feed.html` | Feed | `js/feed.js`, `js/feed-item.js` | The intel feed (tweets + wires), search, category filters, flag (bookmark) filter, story chips on each card. Nothing is hidden — `noise` only means "skip deep enrichment". |
| `tracker.html` | Timelines | `js/tracker.js` | Story rail (left) + the selected story's timeline (right). Manage panel: add/track/reorder/edit stories, the shared story catalog. |
| `map.html` | Map | `js/app.js`, `css/styles.css` | Leaflet war map of incidents and operations, data-driven timeline scale (`database.json._meta.timeline`). Map-only code; never loads `site.css`. |
| `speeches.html` | (lights up Timelines) | `js/speeches.js` + d3 | UN General Debate analysis: concern clusters, friendliness network, every address. Opened from the UNGA 81 story's analysis callout. |

Shared on every page: `js/nav.js` (top bar, theme toggle, user switcher),
`js/user-store.js` + `js/session.js` (profiles), `js/util.js` (helpers + the timeline
merge), `css/tokens.css` (design tokens; `site.css` and `styles.css` both import it).

**Cache-busting:** every asset is referenced as `file.js?v=N`. Bump `N` in every
HTML file that loads a file you changed, or browsers keep the old copy.

**Colour rule** (`css/tokens.css`): three roles only — `--accent` (the reader's own
state: tracked, selected, links), `--accent2` (conflict/severity, the one alarm
colour), `--flag` (personal bookmark). Neutrals carry everything else. **No colour
ever claims an item is confirmed or unverified** — nothing in the pipeline can
establish that.

---

## 3. Sources → feed

### 3.1 Ingestion

| Source | Script | Output | Notes |
|---|---|---|---|
| Spectator Index tweets | `pull_spectator.py` | `raw_data/spectator_raw.csv` | Private API; token in gitignored `.env` (`SPECTATOR_BEARER_TOKEN`). **The API itself has served nothing newer than 2026-10-07** (upstream, not a local bug); `enrich_status.py` shows it as a soft `raw ingest WARN (spectator Nd)`. |
| RSS wires + GDELT | `pull_wires.py` | `raw_data/wire_raw.csv` (60 h window) | Feed list comes from `sources.csv` (`scope=wire`). GDELT gives non-Western perspectives; it can hang → `--no-gdelt`. AP comes through a `site:apnews.com` Google News query. |
| YouTube channels | `pull_youtube.py` | `youtube_videos.csv` | See §6. Never enters the feed. |
| UN Meetings Coverage + UN News | `pull_un_daily.py` | `un_daily/reports.csv` | See §7. |

### 3.2 Two-tier enrichment (`spectator-deep-enrichment` routine)

1. **Base tier** — `base_enrich.py` (+ `enrich_lib.py`): deterministic, no network,
   writes a row for **every** raw item into `spectator_enriched.csv` (keyword
   category, ISO-2 countries, severity, noise flag, keyword-matched image). The
   raw→enriched backlog is therefore always zero.
2. `sync_enriched_to_intel.py` **upserts** into `intel_feed.csv` (dedup key:
   normalised `created_at` + whitespace-collapsed text; timestamp alone collides).
3. `promote_incidents.py` turns significant feed events into `incidents.csv` rows
   (`ma-YYYYMMDD-slug` ids, grouped per event) — this is what feeds the map.
4. **Deep tier** — `select_deep_batch.py 8` picks at most 8 rows (tracked-story
   matches first, noise excluded); the agent researches them with WebSearch;
   `apply_deep_enrichment.py` upserts and flips `tier` base → deep. A deep backlog
   is a soft warning, never a publish blocker.
5. `link_stories.py` writes `linked_story_ids` onto every feed row (§4.4).
6. `build_db.py`, then `enrich_status.py` (base coverage = hard gate, deep backlog
   = warning; raw ingest is hard only when **every** raw source — Spectator and
   wires — is stale, one quiet source is a warning), then commit + push.

### 3.3 The source registry (`data/sources.csv`, `source_registry.py`, `js/sources.js`)

Every outlet is an entity: id, name, aliases, kind (`rss|gdelt|social|web|youtube`),
**scope** (`wire` = auto-pulled · `research` = only WebSearched by the agent, never
fetched · `video` = YouTube archive), status.

- Names typed by users or agents are resolved exact → normalised → fuzzy. Python
  and `js/sources.js` use the **same** similarity metric (2·LCS/(la+lb)); change one,
  change both.
- `not_found` means **no such outlet exists**. A real outlet that simply had no
  news is never flagged — that is `last_ok_at` / `last_items`.
- Per-story source selection is an overlay (`story.sources = {selected, excluded,
  added}`); absent = every active source. Deselecting a source stops it feeding
  that story from the next run on.
- `un-press` ("UN Meetings Coverage") is `scope=research` on purpose so
  `pull_wires.py` never pulls it — `pull_un_daily.py` owns it.

---

## 4. Stories (the tracker)

### 4.1 Catalog + per-user overlay (`data/watchlist.json`, `js/watchlist.js`)

- **Catalog** = `data/watchlist.json`, shared, pipeline-owned. The Python scripts
  read and write only this.
- **User doc** (browser localStorage via `js/user-store.js`, key
  `geo.u.<userId>.<name>`): `{follows: [story_id…], own: […], overrides: {…}}`.
  `follows` order **is** the user's priority. Overrides (title, image, status,
  keywords, sources, parent_id…) personalise a catalog story without changing it
  for anyone else.
- A brand-new profile follows every active catalog story. Stories published
  later are **not** auto-followed; they appear under "Story catalog" in the Manage
  panel (or via a parent/branch link, §4.2).
- "Export watchlist.json" + `import_watchlist.py` publishes a user's list into the
  catalog. Only a user action ever changes a story's `status`.

### 4.2 Branches (`parent_id`)

A story can branch from another: the child carries `parent_id: <parent story_id>`.

- **Tracker (main page, `home.js`)**: a branch does **not** get a tile of its own when
  its parent is an active tracked story. It rides inside its top ancestor's tile as
  a translucent one-line row (⑂ title · update count) that links to the branch's
  timeline (up to 3 on the lead tile, 2 elsewhere, then "+N more"). The tile is a
  `<div>` with a stretched `.story-tile-link` so branch rows can be links of their
  own. A branch whose parent you don't follow keeps its own tile.
- **Timelines rail** (`railRows()` in `tracker.js`): a followed branch is its own card,
  indented directly under its followed parent (⑂, dashed edge). A branch whose
  parent you don't follow stays top-level.
- **Parent header** lists its branches as cards (`branchesHtml()`), including catalog
  branches you don't follow yet ("Track branch +").
- **Branch header** links back: "⑂ Branch of …" (`parentLinkHtml()`). Following a
  parent from there places it just above the branch in your priority order.
- **Sub-track** on a timeline card creates a child story from that feed item
  (`addSubTrack`) — the same `parent_id` mechanism.

Current tree:

```
United Nations: daily reporting          st-20261103-united-nations
└─ UNGA 81: the 81st General Assembly    st-20260922-unga81-general-debate  (+ speech analysis)
```

### 4.3 What a story timeline is made of

`Util.buildStoryEntries()` (js/util.js) merges, newest first, with the seed pinned
at the bottom:

1. **Beats** — rows of `data/story_updates.csv` for that story. Writers:
   - `update_stories.py` (7a): deterministic matches of new feed rows (forward-scan
     only, from `last_update_at`).
   - Agent WebSearch (7b) → `add_story_update.py`, the **only** sanctioned writer:
     validates, resolves `source_name` against the registry, rejects deselected
     sources, dedups on (story_id, url) and fuzzy headline (`story_dedup.py`,
     ≥60 % shared significant words same day), scrapes the article's own
     og:image.
   - `link_youtube.py` (videos, `origin=youtube`), `cross_link_updates.py`
     (copies tagged `cross_linked_from`), `un_story_updates.py` (UN reports).
2. **Every linked feed row** (`linked_story_ids` contains the story) — this is what
   makes timelines retroactive.

Dedup: a feed row is dropped if it has the same `date|normHead(headline)` as a
beat **or the same URL** as a beat (deep enrichment rewrites summaries, so the
headline key alone misses those). `scripts/story_stats.py` mirrors this exactly to
compute `update_count` / `last_update_at`; `build_db.py` applies it every run. **Keep
`normHead`/`norm_head` and the URL rule in lockstep.** Counters are derived, never
bumped by hand.

Beat images are the source article's real image or nothing — never a
keyword-matched stock photo. (Story **hero** images are different: keyword-matched
from `story_images.csv` or set explicitly by `add_story_image.py`.)

### 4.4 Matching a feed row to a story (`link_stories.py`, `update_stories.py`)

A row matches a story when:

- it shares ≥1 country with `seed.countries` (**an empty country list is no gate at
  all**), AND
- it hits ≥2 of the story's `keywords`, or 1 keyword and lies within ~2° of the
  seed's lat/lng.

**`link_sources`** overrides this: a story with `link_sources: ["UN News"]` links
every row from those sources and nothing else, and `update_stories.py` skips it
(its beats come from its own writer). Use it for a story fed by a dedicated
pipeline whose keywords are too generic to match safely.

Keyword traps: never list two synonyms of one place ("nyc" + "new york city" —
the ≥2 rule counts one signal twice); do include the subject's forms wires write
("mamdani" + "zohran mamdani"). A story with **empty keywords never matches** —
`enrich_story_meta.py` (story-tracker Step 0b) fills them.

### 4.5 Status and staleness

`active | resolved | archived` are user-set. The rail's "stale" is computed:
no linked feed row or beat in 14 days (`lastNewsAt`), not the bookkeeping date.

### 4.6 Analysis callout

A story with `analysis: {type, url}` shows a card above its timeline linking to a
dedicated page (`ANALYSIS_COPY` in `tracker.js`). Used by UNGA 81 → `speeches.html`.

---

## 5. Scheduled routines (agent sessions, local time)

| Task | When | Owns | Commits |
|---|---|---|---|
| `spectator-deep-enrichment` | 06:30 daily | Tweets + wires → feed + incidents (§3.2) | raw, enriched, intel_feed, incidents, database.json, feed.json |
| `spectator-story-tracker` | 07:15 daily | Story timelines: 0b metadata, 7a matches, 1b source verification, 7b WebSearch, 2e cross-links, images, recount | story_updates, watchlist, story_images, crosslink_review, database.json, feed.json |
| `youtube-video-tracker` | 07:50 daily | Video archive → story beats (§6) | youtube_videos, story_updates, sources, database.json, feed.json |

Every routine starts with `git pull --rebase`, mutates CSVs **only through scripts**,
and never force-pushes. Routines touching `story_updates.csv` must not overlap —
two did once and one lost its writes (verify a write survived before trusting a
success message).

The **UN daily pull is not scheduled yet** (§7.3).

---

## 6. YouTube video archive

185 channels are `scope=video` sources. `pull_youtube.py` fetches each channel's
feed into `youtube_videos.csv`; `enrich_youtube.py` rewrites titles from the
description; `link_youtube.py` scores the **whole archive** against every story on
every run (retroactive), and `review_youtube_links.py` has the agent judge each
proposal. Videos **never** enter `intel_feed.csv` — they reach the site only as
`origin=youtube` beats. Channel ids need two checks (canonical id + the channel's
own title), or videos get filed under the wrong channel.

---

## 7. United Nations

### 7.1 Daily reporting → the UN story

```
press.un.org RSS (official record) ─┐
UN News RSS (5 feeds) ──────────────┼─► pull_un_daily.py ─► data/un_daily/reports.csv ─► un_story_updates.py ─► story_updates.csv
intel_feed UN News rows (backfill) ─┘        (id-keyed, never drops a row)                 (via add_story_update.py --no-fetch)
```

- **Classification:** a press release's document symbol says which organ produced
  it — `ga` plenary, `gadis/gaef/gashc/gaspd/gaab/gal` the six Main Committees,
  `sc` Security Council, `sgsm/sga/sgt` Secretary-General, `db` noon briefing,
  `hr` human rights… UN News stories get a branch from their **headline first**,
  then the lede ("…, Ruto tells General Assembly" is a General Debate speech, not a
  Council meeting).
- **Routing** (`un_story_updates.py`): every report → the UN story; General
  Assembly reports from UNGA 81's opening (2026-09-08) are **also** written to the
  UNGA 81 branch. The beat's `origin` tag is the organ ("Security Council", "Sixth
  Committee", "Noon briefing", "UN News").
- **Feed link:** the UN story has `link_sources: ["UN News"]`, so every UN News
  card on the Feed carries the "United Nations" chip and nothing else does.
- **To add a branch** (say, a Security Council story): create the child story with
  `parent_id: st-20261103-united-nations`, then add it to `BRANCHES` in
  `un_story_updates.py`.

### 7.2 Limits

- press.un.org's RSS holds only its **10 most recent releases**. Official coverage
  is only as complete as the pull is frequent; the archive starts 2026-11-03.
- press.un.org HTML pages answer automated clients with 406. We use the RSS only
  and never imitate a browser to get past that.
- UN News dates stories by day only (every item reads 12:00 UTC).

### 7.3 Scheduling (pending approval)

Proposed: a light task 4×/day that runs `pull_un_daily.py` and commits only
`reports.csv`, plus a `un_story_updates.py` step inside `spectator-story-tracker`
(so only one routine writes `story_updates.csv`). Until then run by hand:

```bash
python3 scripts/pull_un_daily.py && python3 scripts/un_story_updates.py && python3 scripts/link_stories.py && python3 scripts/build_db.py
```

### 7.4 The General Debate analysis (`speeches.html`)

`pull_un_speeches.py` lists the UN channel's General Debate uploads (flag emoji →
ISO-2) and fetches transcripts (English interpretation track; YouTube IP-blocks
after ~26 fast fetches — space ≥30 s). Per-speech summaries are written by the
agent from transcripts or press.un.org coverage and merged by
`add_un_summaries.py`; `analyze_un_speeches.py` clusters concerns (k-means,
cosine) and scores friendliness (direct statements + position alignment + a capped
concern-similarity nudge) into `data/un_speeches/unga81.json`. 194 addresses: 35
from transcripts, 159 from UN coverage.

---

## 8. The map

`incidents.csv` (24 cols) + `incident_details.csv` (curated overflow) +
`operations.csv` + `imagery.csv` → `build_db.py` (computes `operation_color`,
`date_sort_value`, `badge_colors`) → `database.json` → `js/app.js`. New incidents,
operations or imagery need only a CSV row, no JS. `confirmed` is still a column
but nothing renders it.

---

## 9. Rules that are easy to break

1. Mutate CSVs only through their scripts (`add_story_update.py`,
   `source_registry.py --upsert`, `apply_deep_enrichment.py`…). Hand-written CSV
   rows silently shift columns.
2. `build_db.py` writes `database.json` **and** `feed.json`; commit both.
3. Python ↔ JS twins must stay identical: `norm_head`/`normHead` + URL dedup
   (story counts), the source-name similarity metric.
4. Empty `seed.countries` is not a filter; empty `keywords` never matches.
5. Videos never go into `intel_feed.csv`.
6. Beat images: the article's own image or none.
7. Story `status` changes only by a user, never a routine.
8. Bump `?v=` on every page that loads a changed asset.
9. Locally, `python3 -m http.server` lets the browser cache `feed.json`; force a
   reload when checking fresh data.
10. The in-app preview browser doesn't fire IntersectionObserver /
    requestAnimationFrame, so lazy timeline cards look blank there — verify via the
    DOM, not screenshots.
