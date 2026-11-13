"""
graph.py — read the Neo4j mirror back into the JSON shapes the site reads.

Every page fetches through js/data.js (the DataLayer). Today that means the
files build_db.py writes — data/feed.json, data/database.json — and
data/un_speeches/unga<N>.json. The functions here rebuild those exact shapes
from the graph that scripts/neo4j_migrate.py loads, so pointing the DataLayer at
the API changes a URL and nothing else:

  bootstrap('feed')  ≙ data/feed.json       (index / feed / tracker pages)
  bootstrap('full')  ≙ data/database.json   (map page)
  speeches(81)       ≙ data/un_speeches/unga81.json

Undoing neo4j_migrate.props():
  - CSV-backed rows go back to all-string columns (the DataLayer stringifies
    anyway): lists re-join with ';', booleans become the casing that file uses
    (operations.csv says 'true', every other file 'TRUE'), numbers print plainly.
  - Nested dicts that props() flattened one level (a story's `seed_*`,
    `analysis_*`; a speech's `concerns_*`, `positions_*`) are re-nested; values
    it stored as JSON strings (mentions, pairs, the analysis blobs) are parsed.
  - Lists come back in file order via the `position` property.

Derived values are computed here the same way build_db.py computes them, by
importing it (operation_color, date_sort_value, badge_colors, the map timeline)
and story_stats.py (each story's update_count / last_update_at).

All queries are reads, sent with read routing.
"""

import gzip
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import build_db      # noqa: E402  (derived incident fields, timeline marks, column lists)
import story_stats   # noqa: E402  (update_count / last_update_at, norm_head)

# ── Connection ────────────────────────────────────────────────────────────── #


def _env():
    """NEO4J_* from the environment, else the repo's gitignored .env."""
    env = {}
    path = os.path.join(ROOT, '.env')
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.update(os.environ)
    return env


ENV = _env()
_driver = None
_driver_lock = threading.Lock()


def driver():
    global _driver
    with _driver_lock:
        if _driver is None:
            from neo4j import GraphDatabase
            missing = [k for k in ('NEO4J_URI', 'NEO4J_USERNAME', 'NEO4J_PASSWORD') if not ENV.get(k)]
            if missing:
                raise RuntimeError(f'missing {", ".join(missing)} (environment or .env)')
            _driver = GraphDatabase.driver(
                ENV['NEO4J_URI'], auth=(ENV['NEO4J_USERNAME'], ENV['NEO4J_PASSWORD']),
                max_connection_pool_size=20,
                # Missing-type notices (e.g. no EXCLUDED_SOURCE edges yet) are
                # expected for optional relationships; keep the log clean.
                notifications_min_severity='OFF')
        return _driver


def close():
    global _driver
    with _driver_lock:
        if _driver is not None:
            _driver.close()
            _driver = None


def q(cypher, **params):
    """Run one read query; return a list of plain dicts."""
    from neo4j import RoutingControl
    records, _, _ = driver().execute_query(
        cypher, params, database_=ENV.get('NEO4J_DATABASE') or None,
        routing_=RoutingControl.READ)
    return [r.data() for r in records]


# ── Column lists (what the files / build_db.py export) ────────────────────── #

TWEET_COLS = build_db.TWEET_DB_COLS
INCIDENT_COLS = build_db.INCIDENT_DB_COLS
STORY_UPDATE_COLS = ['update_id', 'story_id', 'date', 'headline', 'summary',
                     'source_name', 'url', 'status', 'severity', 'origin', 'found_at',
                     'image', 'source_id', 'cross_linked_from']
SOURCE_COLS = ['source_id', 'name', 'aliases', 'category', 'kind', 'domain', 'handle',
               'feed_url', 'query', 'perspective', 'source_country', 'scope', 'status',
               'added_by', 'added_at', 'corrected_from', 'last_ok_at', 'last_items', 'notes']
OPERATION_COLS = ['operation_name', 'color', 'countries', 'period', 'dashed']
IMAGERY_COLS = ['incident_id', 'label', 'url', 'caption', 'source']
STORY_IMAGE_COLS = ['keywords', 'countries', 'label', 'url', 'caption', 'credit']
INTERNAL = {'_load', 'position'}


def cell(v, lower_bool=False):
    """A typed graph value back to its CSV string."""
    if v is None:
        return ''
    if isinstance(v, bool):
        s = 'TRUE' if v else 'FALSE'
        return s.lower() if lower_bool else s
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return ';'.join(cell(x, lower_bool) for x in v)
    return str(v)


def row(p, cols, lower_bool=False):
    return {c: cell(p.get(c), lower_bool) for c in cols}


def tweet_row(p):
    r = row(p, TWEET_COLS)
    r['feed_id'] = p.get('feed_id', '')
    return r


def _json(v, default):
    if v in (None, ''):
        return default
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return default
    return v


# ── Load stamp (cache key) ───────────────────────────────────────────────── #
# neo4j_migrate.py --load stamps every node with the run's `_load`. Sources are
# a few hundred nodes and always present, so the newest stamp among them is a
# cheap "has the data changed" signal. (Phase 2 writers that update single
# nodes should stamp a Source too, or replace this with a Meta node.)

_stamp = {'value': None, 'checked': 0.0}
STAMP_TTL = float(ENV.get('API_STAMP_TTL', '30'))


def load_stamp():
    now = time.monotonic()
    if _stamp['value'] is None or now - _stamp['checked'] > STAMP_TTL:
        res = q('MATCH (s:Source) RETURN max(s._load) AS v')
        _stamp['value'] = (res[0]['v'] if res else None) or 'unknown'
        _stamp['checked'] = now
    return _stamp['value']


class Cache:
    """Serialized (raw, gzip) responses, valid for one load stamp."""

    def __init__(self):
        self._data = {}
        self._locks = {}
        self._guard = threading.Lock()

    def get(self, key, build):
        stamp = load_stamp()
        hit = self._data.get(key)
        if hit and hit[0] == stamp:
            return hit
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:                       # one build per key; others wait for it
            hit = self._data.get(key)
            if hit and hit[0] == stamp:
                return hit
            raw = json.dumps(build(), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            entry = (stamp, raw, gzip.compress(raw, compresslevel=6))
            self._data[key] = entry
            return entry


cache = Cache()

# ── Records ──────────────────────────────────────────────────────────────── #


def _nodes(label, order='n.position'):
    return [r['p'] for r in q(f'MATCH (n:{label}) RETURN properties(n) AS p ORDER BY {order}')]


def sources():
    return [row(p, SOURCE_COLS) for p in _nodes('Source')]


def story_images():
    return [{'id': i + 1, **row(p, STORY_IMAGE_COLS)} for i, p in enumerate(_nodes('StoryImage'))]


def story_updates(story_id=None):
    where = 'WHERE u.story_id = $sid ' if story_id else ''
    rows = q(f'MATCH (u:StoryUpdate) {where}RETURN properties(u) AS p '
             'ORDER BY u.story_id, u.date, u.update_id', sid=story_id)
    return [row(r['p'], STORY_UPDATE_COLS) for r in rows]


def tweets(limit=2000):
    rows = q('MATCH (f:FeedItem) WHERE f.created_at < $top RETURN properties(f) AS p '
             'ORDER BY f.created_at DESC, f.feed_id DESC LIMIT $n', top='￿', n=limit)
    return [tweet_row(r['p']) for r in rows]


STORY_NESTED = ('seed', 'analysis')
STORY_DEFAULTS = {'status': '', 'title': '', 'marked_at': '', 'query_hints': [],
                  'keywords': [], 'last_update_at': '', 'update_count': 0,
                  'resolved_at': None, 'notes': ''}
SEED_DEFAULTS = {'created_at': '', 'tweet_id': '', 'text': '', 'category': '',
                 'countries': [], 'lat': None, 'lng': None}


def _story(p, overlay):
    st = {}
    for k, v in p.items():
        if k in INTERNAL:
            continue
        for pre in STORY_NESTED:
            if k.startswith(pre + '_'):
                st.setdefault(pre, {})[k[len(pre) + 1:]] = v
                break
        else:
            st[k] = v
    for k, v in STORY_DEFAULTS.items():
        st.setdefault(k, list(v) if isinstance(v, list) else v)
    st['seed'] = {**SEED_DEFAULTS, **st.get('seed', {})}
    if overlay:
        st['sources'] = {'selected': overlay.get('selected', []),
                         'excluded': overlay.get('excluded', []),
                         'added': overlay.get('added', [])}
    return st


def _overlays():
    out = {}
    for r in q('MATCH (st:Story)-[r:SELECTED_SOURCE]->(s:Source) '
               'RETURN st.story_id AS sid, s.source_id AS src ORDER BY sid, r.position'):
        out.setdefault(r['sid'], {}).setdefault('selected', []).append(r['src'])
    for r in q('MATCH (st:Story)-[:EXCLUDED_SOURCE]->(s:Source) '
               'RETURN st.story_id AS sid, s.source_id AS src ORDER BY sid, src'):
        out.setdefault(r['sid'], {}).setdefault('excluded', []).append(r['src'])
    for r in q('MATCH (st:Story)-[r:ADDED_SOURCE]->(s:Source) '
               'RETURN st.story_id AS sid, s.source_id AS src, properties(r) AS p ORDER BY sid, src'):
        extra = {k: v for k, v in r['p'].items() if k not in INTERNAL}
        out.setdefault(r['sid'], {}).setdefault('added', []).append({'source_id': r['src'], **extra})
    return out


def story_counts():
    """story_id -> {'count', 'last'} over EVERY beat and linked feed row —
    the same merge + dedup story_stats.py runs over the files."""
    beats = q('MATCH (u:StoryUpdate)-[:UPDATE_OF]->(st:Story) '
              'RETURN st.story_id AS story_id, u.date AS date, u.headline AS headline, '
              'u.summary AS summary, u.found_at AS found_at, u.url AS url')
    linked = q('MATCH (f:FeedItem)-[:LINKED_TO]->(st:Story) '
               'WITH f, collect(st.story_id) AS ids '
               'RETURN f.created_at AS created_at, f.summary AS summary, '
               'f.full_text AS full_text, f.source_url AS source_url, ids')
    for r in linked:
        r['linked_story_ids'] = ';'.join(r.pop('ids'))
    return story_stats.compute(beats, linked)


def stories(counts=None):
    overlays = _overlays()
    out = [_story(p, overlays.get(p['story_id'])) for p in _nodes('Story')]
    story_stats.apply(out, counts if counts is not None else story_counts())
    return out


def operations():
    out = []
    for p in _nodes('Operation'):
        p = dict(p, operation_name=p.get('name'))
        out.append(row(p, OPERATION_COLS, lower_bool=True))
    return out


def imagery():
    return [{'id': i + 1, **row(p, IMAGERY_COLS)} for i, p in enumerate(_nodes('Image'))]


def incidents(ops=None):
    color = {o['operation_name']: o['color'] for o in (ops or operations())}
    out = []
    for p in _nodes('Incident'):
        r = row(p, INCIDENT_COLS)
        r['operation_color'] = color.get(r['operation_name'], '#9e9e9e')
        r['date_sort_value'] = build_db.date_to_sort_value(r['date'])
        r['badge_colors'] = build_db.compute_badge_colors(r)
        out.append(r)
    # build_db: ORDER BY date_sort_value (ties keep file order)
    out.sort(key=lambda r: float(r['date_sort_value'] or 0))
    return out


def timeline():
    """The map's time scale — build_db.export_json()'s `_meta.timeline`."""
    now_val = build_db.value_for_date(datetime.utcnow())
    marks = [{'v': v, 'lbl': lbl} for _, v, lbl in build_db.TIMELINE_MARKS]
    if abs(now_val - marks[-1]['v']) < 0.5:
        marks[-1] = {'v': now_val, 'lbl': 'Now'}
    else:
        marks.append({'v': now_val, 'lbl': 'Now'})
    return {'marks': marks, 'min': build_db.TIMELINE_MARKS[0][1] - 5, 'max': now_val}


# ── Page payloads ────────────────────────────────────────────────────────── #


def bootstrap(scope='feed'):
    """data/feed.json (scope='feed') or data/database.json (scope='full')."""
    data = {
        'story_images': story_images(),
        'tweets': tweets(),
        'watchlist': stories(),
        'story_updates': story_updates(),
        'sources': sources(),
    }
    if scope == 'full':
        ops = operations()
        data.update(incidents=incidents(ops), operations=ops, imagery=imagery())
    inc = data.get('incidents', [])
    counts = {
        'story_images': len(data['story_images']),
        'tweets': len(data['tweets']),
        'watchlist_stories': len(data['watchlist']),
        'watchlist_active': sum(1 for s in data['watchlist'] if s.get('status') == 'active'),
        'story_updates': len(data['story_updates']),
        'sources': len(data['sources']),
    }
    if scope == 'full':
        counts.update(
            incidents_curated=sum(1 for i in inc if i.get('source_type') == 'curated'),
            incidents_enriched=sum(1 for i in inc if i.get('source_type') == 'enriched'),
            incidents_total=len(inc), operations=len(data['operations']),
            imagery=len(data['imagery']))
    stamp = load_stamp()
    data['_meta'] = {
        # "Updated …" on the pages = when this data last reached Neo4j.
        'generated': (stamp[:19] + 'Z') if re.match(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d', stamp)
        else datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'version': 8,
        'timeline': timeline(),
        'counts': counts,
        'source': 'neo4j',
        'loaded_at': load_stamp(),
    }
    return data


def map_payload():
    ops = operations()
    return {'incidents': incidents(ops), 'operations': ops, 'imagery': imagery(),
            '_meta': {'timeline': timeline(), 'loaded_at': load_stamp()}}


# ── Feed paging ───────────────────────────────────────────────────────────── #

_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


def lucene_escape(text):
    return _LUCENE_SPECIAL.sub(r'\\\1', text)


def feed_page(before=None, limit=100, text=None, story=None):
    """Newest-first feed rows older than the cursor `before`
    ("<created_at>|<feed_id>", as returned in `next`)."""
    c_at, c_id = '￿', '￿'
    if before:
        c_at, _, c_id = before.partition('|')
        c_id = c_id or '￿'
    params = dict(c_at=c_at, c_id=c_id, n=limit, sid=story)
    story_filter = 'AND EXISTS { (f)-[:LINKED_TO]->(:Story {story_id: $sid}) } ' if story else ''
    cursor = '(f.created_at < $c_at OR (f.created_at = $c_at AND f.feed_id < $c_id)) '
    if text:
        cypher = ("CALL db.index.fulltext.queryNodes('feed_text', $text) YIELD node AS f "
                  f'WHERE {cursor}{story_filter}')
        params['text'] = lucene_escape(text)
    else:
        cypher = f'MATCH (f:FeedItem) WHERE {cursor}{story_filter}'
    cypher += ('RETURN properties(f) AS p ORDER BY f.created_at DESC, f.feed_id DESC LIMIT $n')
    items = [tweet_row(r['p']) for r in q(cypher, **params)]
    nxt = f"{items[-1]['created_at']}|{items[-1]['feed_id']}" if len(items) == limit else None
    return {'items': items, 'next': nxt}


# ── One story's timeline ─────────────────────────────────────────────────── #


def build_story_entries(story_id, beats, feed_items):
    """Python twin of Util.buildStoryEntries() in js/util.js: curated beats +
    every linked feed row, deduped on date|normHead (and a beat's url),
    newest first. `beats` ascending by date; `feed_items` newest first."""
    norm = story_stats.norm_head
    feed_by_norm = {}
    for it in feed_items:
        fk = (it.get('created_at') or '')[:10] + '|' + norm(it.get('summary') or it.get('full_text'))
        feed_by_norm.setdefault(fk, it)

    seen, beat_urls, entries = set(), set(), []
    for u in beats:
        head = u.get('headline') or u.get('summary') or ''
        k = (u.get('date') or '') + '|' + norm(head)
        if k in seen:
            continue
        seen.add(k)
        if u.get('url'):
            beat_urls.add(u['url'])
        entries.append({
            'date': u.get('date') or '', 'headline': head, 'summary': u.get('summary') or '',
            'origin': u.get('origin') or 'update', 'status': u.get('status') or '',
            'source_name': u.get('source_name') or '', 'url': u.get('url') or '',
            'image': u.get('image') or '',
            'feed': (feed_by_norm.get(k) if not u.get('url') else None),
        })
    for it in feed_items:
        date = (it.get('created_at') or '')[:10]
        head = it.get('summary') or it.get('full_text') or ''
        k = date + '|' + norm(head)
        if k in seen or (it.get('source_url') and it['source_url'] in beat_urls):
            continue
        seen.add(k)
        entries.append({'date': date, 'headline': head, 'summary': '', 'origin': 'feed',
                        'status': '', 'source_name': 'Spectator Index', 'url': '', 'feed': it})
    entries.sort(key=lambda e: e['date'] or '', reverse=True)
    return entries


def story_timeline(story_id):
    found = q('MATCH (st:Story {story_id: $sid}) RETURN properties(st) AS p', sid=story_id)
    if not found:
        return None
    overlays = _overlays()
    story = _story(found[0]['p'], overlays.get(story_id))
    beats = story_updates(story_id)
    feed = [tweet_row(r['p']) for r in q(
        'MATCH (f:FeedItem)-[:LINKED_TO]->(:Story {story_id: $sid}) '
        'RETURN properties(f) AS p ORDER BY f.created_at DESC, f.feed_id DESC', sid=story_id)]
    entries = build_story_entries(story_id, beats, feed)
    story_stats.apply([story], story_stats.compute(beats, feed))
    branches = [_story(r['p'], overlays.get(r['p']['story_id'])) for r in q(
        'MATCH (c:Story)-[:CHILD_OF]->(:Story {story_id: $sid}) '
        'RETURN properties(c) AS p ORDER BY c.position', sid=story_id)]
    return {'story': story, 'branches': branches, 'count': len(entries), 'entries': entries}


# ── UN speeches (speeches.html) ──────────────────────────────────────────── #


def _sub(p, prefix):
    return {k[len(prefix):]: v for k, v in p.items() if k.startswith(prefix)}


def speeches(session):
    aid = f'unga{session}'
    a = q('MATCH (a:SpeechAnalysis {analysis_id: $aid}) RETURN properties(a) AS p', aid=aid)
    if not a:
        return None
    a = a[0]['p']
    sp = [r['p'] for r in q('MATCH (s:Speech {session: $session}) RETURN properties(s) AS p '
                            'ORDER BY s.position', session=int(session))]
    nations = []
    for p in sp:
        if p.get('kind') != 'address' or p.get('cluster') is None:
            continue
        nations.append({
            'video_id': p['video_id'], 'iso2': p.get('iso2', ''), 'country': p.get('country', ''),
            'role': p.get('speaker_role', ''), 'speaker': p.get('speaker', ''),
            'url': p.get('url', ''), 'published': p.get('published', ''),
            'words': int(p.get('words') or 0), 'summary': p.get('summary', ''),
            'primary_concern': p.get('primary_concern', ''),
            'primary_topic': p.get('primary_topic', ''),
            'concerns': _sub(p, 'concerns_'), 'mentions': _json(p.get('mentions'), []),
            'positions': _sub(p, 'positions_'), 'src': p.get('src', 'transcript'),
            'source_url': p.get('source_url', ''), 'cluster': p['cluster'],
            'xy': p.get('xy', []),
        })
    nations.sort(key=lambda x: x['country'])
    replies = [{
        'video_id': p['video_id'], 'title': p.get('country', ''), 'url': p.get('url', ''),
        'summary': p.get('summary', ''), 'pairs': _json(p.get('pairs'), []),
        'src': p.get('src', 'transcript'), 'source_url': p.get('source_url', ''),
    } for p in sp if p.get('kind') == 'reply' and (p.get('summary') or p.get('pairs'))]
    clusters = [{
        'id': r['p']['index'], 'label': r['p'].get('label', ''),
        'top_topics': _json(r['p'].get('top_topics_json'), []),
        'members': r['p'].get('members', []),
    } for r in q('MATCH (c:SpeechCluster)-[:PART_OF]->(:SpeechAnalysis {analysis_id: $aid}) '
                 'RETURN properties(c) AS p ORDER BY c.index', aid=aid)]
    return {
        'session': a.get('session', int(session)),
        'generated_at': a.get('generated_at', ''),
        'topics': _json(a.get('topics_json'), []),
        'positions': _json(a.get('positions_json'), []),
        'weights': _json(a.get('weights_json'), {}),
        'silhouette': a.get('silhouette'),
        'axes': _json(a.get('axes_json'), []),
        'nations': nations,
        'clusters': clusters,
        'edges': _json(a.get('edges_json'), []),
        'replies': replies,
        'friendliness': {'order': a.get('friendliness_order', []),
                         'tri': a.get('friendliness_tri', []),
                         'basis': a.get('friendliness_basis', [])},
        'coverage': _json(a.get('coverage_json'), {}),
    }


# ── UN daily reports ─────────────────────────────────────────────────────── #


def un_reports(branch=None, organ=None, before=None, limit=100):
    rows = q('MATCH (r:UNReport) WHERE r.date < $before '
             'AND ($branch IS NULL OR r.branch = $branch) AND ($organ IS NULL OR r.organ = $organ) '
             'RETURN properties(r) AS p ORDER BY r.date DESC, r.report_id DESC LIMIT $n',
             before=before or '￿', branch=branch, organ=organ, n=limit)
    out = []
    for r in rows:
        p = {k: v for k, v in r['p'].items() if k not in INTERNAL}
        p['id'] = p.pop('report_id', '')
        out.append({k: cell(v) for k, v in p.items()})
    return out
