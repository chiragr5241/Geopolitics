#!/usr/bin/env python3
"""
neo4j_migrate.py — prepare the site's data for a move into Neo4j.

Builds the graph IN MEMORY from the canonical files and, by default, only
reports what it would write: node/relationship counts, dangling references,
duplicate keys and values that don't fit their column's type. Nothing is
sent anywhere unless --load is passed.

The mapping is deliberately literal: every relationship below is a reference
that ALREADY exists in the data (an id or name column pointing at another
record). Nothing is inferred — countries, entities, keywords and categories
stay list properties rather than becoming nodes, and links that only exist by
URL coincidence (a story_update whose url is a video's url) are not made.

  Node            key            from
  Story           story_id       watchlist.json (seed/analysis flattened to props)
  StoryUpdate     update_id      story_updates.csv
  FeedItem        feed_id        intel_feed.csv + its spectator_enriched.csv row
                                 (feed_id = hash of build_db's dedup key — the
                                 feed has no id column of its own)
  Incident        incident_id    incidents.csv + incident_details.csv
  Operation       name           operations.csv
  Source          source_id      sources.csv
  Video           video_id       youtube_videos.csv
  Speech          video_id       un_speeches/unga<N>/speeches.csv + summaries.json
                                 + that nation's row of unga<N>.json (cluster, xy)
  SpeechAnalysis  analysis_id    un_speeches/unga<N>.json top level (topics,
                                 positions, axes, weights, friendliness matrix,
                                 the page's aggregated edges) — "unga<N>"
  SpeechCluster   cluster_id     unga<N>.json clusters — "unga<N>-c<id>"
  UNReport        report_id      un_daily/reports.csv
  Image           image_id       imagery.csv
  StoryImage      image_id       story_images.csv
  CrossLinkReview review_id      crosslink_review.csv
  YoutubeReview   review_id      youtube_review.csv

  Relationship                              via
  (StoryUpdate)-[:UPDATE_OF]->(Story)       story_updates.story_id
  (StoryUpdate)-[:FROM_SOURCE]->(Source)    story_updates.source_id
  (StoryUpdate)-[:CROSS_LINKED_FROM]->(StoryUpdate)  story_updates.cross_linked_from
  (Story)-[:CHILD_OF]->(Story)              watchlist parent_id
  (Story)-[:SELECTED_SOURCE]->(Source)      watchlist sources.selected
  (Story)-[:EXCLUDED_SOURCE]->(Source)      watchlist sources.excluded
  (Story)-[:ADDED_SOURCE]->(Source)         watchlist sources.added[].source_id
  (Story)-[:LINKS_SOURCE]->(Source)         watchlist link_sources (names, resolved
                                            with source_registry.resolve)
  (FeedItem)-[:LINKED_TO]->(Story)          intel_feed.linked_story_ids
  (FeedItem)-[:LINKED_OPERATION]->(Operation) intel_feed.linked_operation
  (FeedItem)-[:LINKED_INCIDENT]->(Incident) intel_feed.linked_incident_ids
  (FeedItem)-[:FROM_SOURCE]->(Source)       intel_feed.source, resolved exactly as
                                            the site already does it
                                            (source_registry.resolve_feed_source)
  (Incident)-[:PART_OF]->(Operation)        incidents.operation_name
  (Image)-[:DEPICTS]->(Incident)            imagery.incident_id
  (Video)-[:FROM_SOURCE]->(Source)          youtube_videos.source_id
  (Speech)-[:PART_OF]->(Story)              watchlist analysis {type: un_speeches, session}
  (SpeechAnalysis)-[:ANALYSIS_OF]->(Story)  same
  (SpeechCluster)-[:PART_OF]->(SpeechAnalysis)  unga<N>.json clusters
  (Speech)-[:IN_CLUSTER]->(SpeechCluster)   unga<N>.json nations[].cluster
  (Speech)-[:MENTIONS]->(Speech)            summaries.json mentions (iso2 → that
                                            nation's address in the same session),
                                            and each reply's {from, to} pairs
                                            (via='reply', reply_video_id)
  (CrossLinkReview)-[:REVIEWS]->(Story)     crosslink_review.story_id
  (CrossLinkReview)-[:ABOUT]->(StoryUpdate) crosslink_review.update_id
  (YoutubeReview)-[:REVIEWS]->(Story)       youtube_review.story_id

UNReport has no relationships: a UN beat in story_updates.csv shares only a url
with its report (no id column), and a report's `branch` is a code that
un_story_updates.py maps to a story in code — neither is a reference in the data.

Story, Source, Operation, Incident, Image, StoryImage and Speech carry
`position` (0-based row order in their file): story_images.csv is matched most-specific-first, and the
read API (api/) returns every list in the order the files hold it.

Not migrated (regenerable or staging): database.json, feed.json,
geopolitics.db, data/raw_data/, data/archive/, transcripts. Per-user overlays
live in each viewer's browser (js/user-store.js), not in the repo.

Usage:
  python3 scripts/neo4j_migrate.py                 # dry run: counts + integrity report
  python3 scripts/neo4j_migrate.py --show Story    # print one sample node of a label
  python3 scripts/neo4j_migrate.py --load          # sync to Neo4j (idempotent MERGE;
                                                   #   prunes what the files no longer hold)
  python3 scripts/neo4j_migrate.py --load --wipe   # delete everything in the DB first
  python3 scripts/neo4j_migrate.py --verify        # page-reproduction queries vs the files

--load reads NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD and optionally
NEO4J_DATABASE from the environment or the gitignored .env (the same names
AuraDB puts in its downloaded credentials file). Needs `pip install neo4j`.
"""

import csv
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict

import source_registry
from build_db import read_csv, sync_dedup_key

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')

csv.field_size_limit(sys.maxsize)

# AuraDB Free limits at the time of writing — verify before relying on them.
AURA_FREE_NODES = 200_000
AURA_FREE_RELS = 400_000

LABEL_KEYS = {
    'Story': 'story_id',
    'StoryUpdate': 'update_id',
    'FeedItem': 'feed_id',
    'Incident': 'incident_id',
    'Operation': 'name',
    'Source': 'source_id',
    'Video': 'video_id',
    'Speech': 'video_id',
    'SpeechAnalysis': 'analysis_id',
    'SpeechCluster': 'cluster_id',
    'UNReport': 'report_id',
    'Image': 'image_id',
    'StoryImage': 'image_id',
    'CrossLinkReview': 'review_id',
    'YoutubeReview': 'review_id',
}

# ── Property typing ───────────────────────────────────────────────────────── #
# Neo4j properties must be scalars or homogeneous scalar lists: no nulls, no
# maps. Empty strings are dropped; nested dicts are flattened one level and
# anything deeper is stored as a JSON string.

BOOL_COLS = {'is_breaking', 'confirmed', 'is_retaliation', 'is_covert',
             'is_first_use', 'disputed', 'dashed', 'custom'}
INT_COLS = {'severity', 'update_count', 'last_items', 'source_count', 'words',
            'session', 'cluster'}
FLOAT_COLS = {'lat', 'lng', 'origin_lat', 'origin_lng', 'target_lat',
              'target_lng'}
LIST_COLS = {'countries', 'tags', 'aliases', 'keywords', 'categories',
             'linked_story_ids', 'linked_operation', 'linked_incident_ids', 'entities_people',
             'entities_orgs', 'entities_weapons', 'entities_locations'}

anomalies = Counter()          # (label, column) -> values that kept their raw string
anomaly_examples = {}


def _typed(label, col, v):
    if isinstance(v, bool) or isinstance(v, (int, float)):
        return v
    if isinstance(v, list):
        items = [x for x in v if x not in (None, '')]
        if all(isinstance(x, str) for x in items):
            return items
        if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in items):
            return [float(x) for x in items]
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    s = str(v).strip()
    try:
        if col in BOOL_COLS:
            if s.lower() in ('true', '1'):
                return True
            if s.lower() in ('false', '0'):
                return False
            raise ValueError
        if col in INT_COLS:
            return int(float(s))
        if col in FLOAT_COLS:
            return float(s)
    except ValueError:
        anomalies[(label, col)] += 1
        anomaly_examples.setdefault((label, col), s[:60])
        return s
    if col in LIST_COLS:
        return [p.strip() for p in s.split(';') if p.strip()]
    return s


def props(label, row, prefix=''):
    """Turn a flat-or-nested dict into Neo4j-legal properties."""
    out = {}
    for k, v in row.items():
        if v is None or v == '' or v == []:
            continue
        if isinstance(v, dict) and not prefix:
            out.update(props(label, v, prefix=f'{k}_'))
            continue
        t = _typed(label, k, v)
        if t != '' and t != []:
            out[prefix + k] = t
    return out


def short_hash(*parts):
    return hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()[:16]


# ── Graph builder ─────────────────────────────────────────────────────────── #

class Graph:
    def __init__(self):
        self.nodes = defaultdict(dict)       # label -> key -> props
        self.dupes = Counter()               # label -> duplicate key count
        self.dupe_examples = {}
        self.rels = defaultdict(list)        # (type, from_label, to_label) -> [(a, b, props)]
        self.pending = []                    # rels resolved after all nodes exist
        self.dangling = Counter()
        self.dangling_examples = defaultdict(set)

    def node(self, label, p):
        key = p[LABEL_KEYS[label]]
        if key in self.nodes[label]:
            self.dupes[label] += 1
            self.dupe_examples.setdefault(label, key)
        self.nodes[label][key] = p           # later row wins, like MERGE + SET

    def rel(self, rtype, a_label, a, b_label, b, p=None):
        if a and b:
            p = {k: v for k, v in (p or {}).items() if v is not None}
            self.pending.append((rtype, a_label, a, b_label, b, p))

    def resolve(self):
        seen = set()
        for rtype, al, a, bl, b, p in self.pending:
            sig = (rtype, al, bl)
            if a not in self.nodes[al] or b not in self.nodes[bl]:
                self.dangling[sig] += 1
                if len(self.dangling_examples[sig]) < 3:
                    self.dangling_examples[sig].add(b if a in self.nodes[al] else a)
                continue
            ident = (sig, a, b, p.get('rel_key'))
            if ident in seen:                # repeated id in a list column
                continue
            seen.add(ident)
            self.rels[sig].append((a, b, p))
        self.pending = []


def build():
    g = Graph()

    # Sources
    source_rows = source_registry.load_sources()
    for i, r in enumerate(source_rows):
        g.node('Source', props('Source', {**r, 'position': i}))

    # Stories
    watchlist = json.load(open(os.path.join(DATA, 'watchlist.json'), encoding='utf-8'))
    for pos, st in enumerate(watchlist['stories']):
        st = dict(st)
        overlay = st.pop('sources', None) or {}
        g.node('Story', props('Story', {**st, 'position': pos}))
        sid_ = st['story_id']
        g.rel('CHILD_OF', 'Story', sid_, 'Story', st.get('parent_id'))
        for i, sid in enumerate(overlay.get('selected') or []):
            g.rel('SELECTED_SOURCE', 'Story', sid_, 'Source', sid, {'position': i})
        for sid in overlay.get('excluded') or []:
            g.rel('EXCLUDED_SOURCE', 'Story', sid_, 'Source', sid)
        for a in overlay.get('added') or []:
            g.rel('ADDED_SOURCE', 'Story', sid_, 'Source', a.get('source_id'),
                  props('ADDED_SOURCE', {k: v for k, v in a.items() if k != 'source_id'}))
        for name in st.get('link_sources') or []:
            res = source_registry.resolve(name, source_rows)
            if res.ok:
                g.rel('LINKS_SOURCE', 'Story', sid_, 'Source', res['source_id'],
                      {'name': name, 'match': res['status']})
            else:
                g.dangling[('LINKS_SOURCE', 'Story', 'Source')] += 1
                g.dangling_examples[('LINKS_SOURCE', 'Story', 'Source')].add(name)

        analysis = st.get('analysis') or {}
        if analysis.get('type') == 'un_speeches' and analysis.get('session'):
            sdir = os.path.join(DATA, 'un_speeches', f"unga{analysis['session']}")
            summaries_path = os.path.join(sdir, 'summaries.json')
            summaries = (json.load(open(summaries_path, encoding='utf-8'))
                         if os.path.exists(summaries_path) else {})
            out_path = os.path.join(DATA, 'un_speeches', f"unga{analysis['session']}.json")
            out = json.load(open(out_path, encoding='utf-8')) if os.path.exists(out_path) else {}
            nations = {n['video_id']: n for n in out.get('nations', [])}
            speeches = read_csv(os.path.join(sdir, 'speeches.csv'))
            address_of = {r['iso2']: r['video_id'] for r in speeches
                          if r.get('kind') == 'address' and r.get('iso2')}
            for pos, r in enumerate(speeches):
                summary = summaries.get(r['video_id'], {})
                n = nations.get(r['video_id'], {})
                merged = {**r, **summary,
                          **{k: n[k] for k in ('cluster', 'xy', 'source_url') if n.get(k) not in (None, '')},
                          'session': analysis['session'], 'position': pos}
                g.node('Speech', props('Speech', merged))
                g.rel('PART_OF', 'Speech', r['video_id'], 'Story', sid_)
                for i, m in enumerate(summary.get('mentions') or []):
                    g.rel('MENTIONS', 'Speech', r['video_id'], 'Speech', address_of.get(m.get('iso2')),
                          {'rel_key': f"speech:{i}", 'via': 'speech', 'to_iso2': m.get('iso2'),
                           'stance': m.get('stance'), 'note': m.get('note') or ''})
                    if m.get('iso2') not in address_of:
                        g.dangling[('MENTIONS', 'Speech', 'Speech')] += 1
                        g.dangling_examples[('MENTIONS', 'Speech', 'Speech')].add(m.get('iso2'))

            if out:
                aid = f"unga{analysis['session']}"
                fr = out.get('friendliness') or {}
                g.node('SpeechAnalysis', {
                    'analysis_id': aid,
                    **props('SpeechAnalysis', {k: out[k] for k in ('session', 'generated_at', 'silhouette')
                                               if k in out}),
                    **{f'{k}_json': json.dumps(out[k], ensure_ascii=False)
                       for k in ('topics', 'positions', 'weights', 'axes', 'edges', 'coverage')
                       if k in out},
                    'friendliness_order': fr.get('order', []),
                    'friendliness_tri': [float(x) for x in fr.get('tri', [])],
                    'friendliness_basis': fr.get('basis', []),
                })
                g.rel('ANALYSIS_OF', 'SpeechAnalysis', aid, 'Story', sid_)
                for c in out.get('clusters', []):
                    cid = f"{aid}-c{c['id']}"
                    g.node('SpeechCluster', {
                        'cluster_id': cid, 'index': c['id'], 'label': c.get('label', ''),
                        'members': c.get('members', []),
                        'top_topics_json': json.dumps(c.get('top_topics', []), ensure_ascii=False)})
                    g.rel('PART_OF', 'SpeechCluster', cid, 'SpeechAnalysis', aid)
                for vid, n in nations.items():
                    if n.get('cluster') is not None:
                        g.rel('IN_CLUSTER', 'Speech', vid, 'SpeechCluster', f"{aid}-c{n['cluster']}")
                for rp in out.get('replies', []):
                    for i, pr in enumerate(rp.get('pairs') or []):
                        a, b = address_of.get(pr.get('from')), address_of.get(pr.get('to'))
                        if not (a and b):
                            g.dangling[('MENTIONS', 'Speech', 'Speech')] += 1
                            g.dangling_examples[('MENTIONS', 'Speech', 'Speech')].add(
                                f"{pr.get('from')}->{pr.get('to')}")
                            continue
                        g.rel('MENTIONS', 'Speech', a, 'Speech', b,
                              {'rel_key': f"reply:{rp['video_id']}:{i}", 'via': 'reply',
                               'reply_video_id': rp['video_id'], 'to_iso2': pr.get('to'),
                               'stance': pr.get('stance'), 'note': pr.get('note') or ''})

    # Story updates
    for r in read_csv(os.path.join(DATA, 'story_updates.csv')):
        g.node('StoryUpdate', props('StoryUpdate', r))
        g.rel('UPDATE_OF', 'StoryUpdate', r['update_id'], 'Story', r['story_id'])
        g.rel('FROM_SOURCE', 'StoryUpdate', r['update_id'], 'Source', r.get('source_id'))
        g.rel('CROSS_LINKED_FROM', 'StoryUpdate', r['update_id'],
              'StoryUpdate', r.get('cross_linked_from'))

    # Operations + incidents (+ their 1:1 overflow detail) + imagery
    for i, r in enumerate(read_csv(os.path.join(DATA, 'operations.csv'))):
        r = dict(r, position=i)
        r['name'] = r.pop('operation_name')
        g.node('Operation', props('Operation', r))

    details = {r['incident_id']: r for r in read_csv(os.path.join(DATA, 'incident_details.csv'))}
    for i, r in enumerate(read_csv(os.path.join(DATA, 'incidents.csv'))):
        merged = {**r, **{k: v for k, v in details.get(r['incident_id'], {}).items() if v},
                  'position': i}
        g.node('Incident', props('Incident', merged))
        g.rel('PART_OF', 'Incident', r['incident_id'], 'Operation', r.get('operation_name'))

    for i, r in enumerate(read_csv(os.path.join(DATA, 'imagery.csv'))):
        iid = short_hash(r['incident_id'], r['url'])
        g.node('Image', props('Image', {'image_id': iid, **r, 'position': i}))
        g.rel('DEPICTS', 'Image', iid, 'Incident', r['incident_id'])

    for i, r in enumerate(read_csv(os.path.join(DATA, 'story_images.csv'))):
        g.node('StoryImage', props('StoryImage', {'image_id': short_hash(r['url']), **r, 'position': i}))

    # Feed items, joined with their enriched row the same way build_db does
    enriched = {sync_dedup_key(r.get('pub_date'), r.get('original_text')): r
                for r in read_csv(os.path.join(DATA, 'spectator_enriched.csv'))}
    matched_enriched = set()
    resolved = {}
    for r in read_csv(os.path.join(DATA, 'intel_feed.csv')):
        key = sync_dedup_key(r.get('created_at'), r.get('full_text'))
        fid = short_hash(*key)
        e = enriched.get(key)
        row = {'feed_id': fid, **r}
        if e:
            matched_enriched.add(key)
            row.update({
                'enriched_id': e.get('id', ''), 'tweet_id': e.get('tweet_id', ''),
                'context': e.get('context', ''), 'implications': e.get('implications', ''),
                'sources_json': e.get('sources_json', ''),
                'confirmation_status': e.get('confirmation_status', ''),
                'source_count': e.get('source_count', ''), 'tier': e.get('tier', ''),
                'enriched_at': e.get('enriched_at', ''),
            })
            if e.get('images'):
                row['images'] = e['images']
        g.node('FeedItem', props('FeedItem', row))

        for sid in props('FeedItem', {'linked_story_ids': r.get('linked_story_ids')}).get('linked_story_ids', []):
            g.rel('LINKED_TO', 'FeedItem', fid, 'Story', sid)
        for iid in props('FeedItem', {'linked_incident_ids': r.get('linked_incident_ids')}).get('linked_incident_ids', []):
            g.rel('LINKED_INCIDENT', 'FeedItem', fid, 'Incident', iid)
        for op in props('FeedItem', {'linked_operation': r.get('linked_operation')}).get('linked_operation', []):
            g.rel('LINKED_OPERATION', 'FeedItem', fid, 'Operation', op)

        src = (r.get('source') or '').strip()
        if src not in resolved:
            resolved[src] = source_registry.resolve_feed_source(r, source_rows)
        res = resolved[src]
        if res.ok:
            g.rel('FROM_SOURCE', 'FeedItem', fid, 'Source', res['source_id'],
                  {'match': res['status']})
        else:
            g.dangling[('FROM_SOURCE', 'FeedItem', 'Source')] += 1
            ex = g.dangling_examples[('FROM_SOURCE', 'FeedItem', 'Source')]
            if len(ex) < 3:
                ex.add(src)
    g.unmatched_enriched = len(enriched) - len(matched_enriched)
    g.feed_source_matches = Counter(res['status'] for res in resolved.values())

    # Videos
    for r in read_csv(os.path.join(DATA, 'youtube_videos.csv')):
        g.node('Video', props('Video', r))
        g.rel('FROM_SOURCE', 'Video', r['video_id'], 'Source', r.get('source_id'))

    # UN daily reporting archive
    for r in read_csv(os.path.join(DATA, 'un_daily', 'reports.csv')):
        r = dict(r)
        r['report_id'] = r.pop('id')
        g.node('UNReport', props('UNReport', r))

    # Review logs
    for r in read_csv(os.path.join(DATA, 'crosslink_review.csv')):
        rid = short_hash('crosslink', *(r.get(k, '') for k in ('story_id', 'update_id', 'url', 'reviewed_at')))
        g.node('CrossLinkReview', props('CrossLinkReview', {'review_id': rid, **r}))
        g.rel('REVIEWS', 'CrossLinkReview', rid, 'Story', r.get('story_id'))
        g.rel('ABOUT', 'CrossLinkReview', rid, 'StoryUpdate', r.get('update_id'))
    for r in read_csv(os.path.join(DATA, 'youtube_review.csv')):
        rid = short_hash('youtube', *(r.get(k, '') for k in ('story_id', 'url', 'reviewed_at')))
        g.node('YoutubeReview', props('YoutubeReview', {'review_id': rid, **r}))
        g.rel('REVIEWS', 'YoutubeReview', rid, 'Story', r.get('story_id'))

    g.resolve()
    return g


# ── Reporting ─────────────────────────────────────────────────────────────── #

def report(g):
    n_nodes = sum(len(v) for v in g.nodes.values())
    n_rels = sum(len(v) for v in g.rels.values())
    n_props = sum(len(p) for v in g.nodes.values() for p in v.values())

    print('NODES')
    for label in LABEL_KEYS:
        dup = f'   ({g.dupes[label]} duplicate key rows collapsed, e.g. {g.dupe_examples[label]})' if g.dupes[label] else ''
        print(f'  {label:<16} {len(g.nodes[label]):>7,}{dup}')
    print(f'  {"TOTAL":<16} {n_nodes:>7,}   ({n_props:,} properties)')

    print('\nRELATIONSHIPS')
    for (t, a, b), rows in sorted(g.rels.items(), key=lambda kv: -len(kv[1])):
        print(f'  ({a})-[:{t}]->({b})'.ljust(52) + f'{len(rows):>7,}')
    print(f'  {"TOTAL":<50}{n_rels:>7,}')

    if g.dangling:
        print('\nDANGLING REFERENCES (skipped — target record does not exist)')
        for (t, a, b), n in g.dangling.most_common():
            ex = ', '.join(repr(x) for x in sorted(g.dangling_examples[(t, a, b)]))
            print(f'  ({a})-[:{t}]->({b})'.ljust(52) + f'{n:>7,}   e.g. {ex}')

    if anomalies:
        print('\nTYPE ANOMALIES (value kept as raw string)')
        for (label, col), n in anomalies.most_common():
            print(f'  {label}.{col:<22} {n:>5}   e.g. {anomaly_examples[(label, col)]!r}')

    print('\nNOTES')
    print(f'  feed source names resolved: {dict(g.feed_source_matches)} (distinct names)')
    print(f'  spectator_enriched rows with no feed row: {g.unmatched_enriched}')
    fits = n_nodes <= AURA_FREE_NODES and n_rels <= AURA_FREE_RELS
    print(f'  AuraDB Free ({AURA_FREE_NODES:,} nodes / {AURA_FREE_RELS:,} rels): '
          f'{"fits" if fits else "DOES NOT FIT"} — '
          f'{n_nodes / AURA_FREE_NODES:.0%} of nodes, {n_rels / AURA_FREE_RELS:.0%} of relationships')


def show(g, label):
    if label not in LABEL_KEYS:
        sys.exit(f'unknown label {label!r}; one of {", ".join(LABEL_KEYS)}')
    key, p = next(iter(g.nodes[label].items()))
    print(json.dumps(p, indent=2, ensure_ascii=False)[:4000])
    for (t, a, b), rows in g.rels.items():
        for x, y, _ in rows:
            if a == label and x == key:
                print(f'  -[:{t}]-> ({b} {y})')
            elif b == label and y == key:
                print(f'  <-[:{t}]- ({a} {x})')


# ── Loading ───────────────────────────────────────────────────────────────── #

def _env():
    env = {}
    path = os.path.join(ROOT, '.env')
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith('NEO4J_')})
    return env


def _batches(items, size=1000):
    for i in range(0, len(items), size):
        yield items[i:i + size]


# Secondary indexes the page queries (and a future API) filter or sort on.
INDEXES = [
    ('StoryUpdate', 'story_id'), ('StoryUpdate', 'date'),
    ('FeedItem', 'created_at'), ('Incident', 'date'), ('Incident', 'operation_name'),
    ('UNReport', 'date'), ('UNReport', 'branch'), ('Video', 'published_at'),
    ('Speech', 'iso2'), ('Story', 'status'), ('Source', 'scope'),
]
FULLTEXT = {'feed_text': ('FeedItem', ['full_text', 'summary'])}


def connect():
    try:
        from neo4j import GraphDatabase
    except ImportError:
        sys.exit('pip install neo4j')
    env = _env()
    missing = [k for k in ('NEO4J_URI', 'NEO4J_USERNAME', 'NEO4J_PASSWORD') if not env.get(k)]
    if missing:
        sys.exit(f'missing {", ".join(missing)} (set in environment or .env)')
    driver = GraphDatabase.driver(env['NEO4J_URI'], auth=(env['NEO4J_USERNAME'], env['NEO4J_PASSWORD']))
    driver.verify_connectivity()
    return driver, env.get('NEO4J_DATABASE') or None


def db_counts(s):
    nodes = {label: s.run(f'MATCH (n:{label}) RETURN count(n) AS c').single()['c']
             for label in LABEL_KEYS}
    rels = {}
    for rec in s.run('MATCH (a)-[r]->(b) RETURN type(r) AS t, labels(a)[0] AS a, '
                     'labels(b)[0] AS b, count(r) AS c'):
        rels[(rec['t'], rec['a'], rec['b'])] = rec['c']
    return nodes, rels


def load(g, wipe=False, prune=True):
    """Sync the graph into Neo4j.

    Every node and relationship is MERGEd on its key and stamped with this
    run's `_load`; with prune (the default) anything of a known label or
    relationship type not stamped by this run — rows that left the files — is
    deleted afterwards, so re-running against unchanged files is a no-op and
    the database always mirrors the files.
    """
    from datetime import datetime, timezone
    run = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    driver, database = connect()
    with driver.session(database=database) as s:
        if wipe:
            print('wiping database…')
            s.run('MATCH (n) CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS').consume()

        for label, key in LABEL_KEYS.items():
            s.run(f'CREATE CONSTRAINT {label.lower()}_key IF NOT EXISTS '
                  f'FOR (n:{label}) REQUIRE n.{key} IS UNIQUE').consume()
        for label, prop in INDEXES:
            s.run(f'CREATE INDEX {label.lower()}_{prop} IF NOT EXISTS '
                  f'FOR (n:{label}) ON (n.{prop})').consume()
        for name, (label, fields) in FULLTEXT.items():
            on = ', '.join(f'n.{f}' for f in fields)
            s.run(f'CREATE FULLTEXT INDEX {name} IF NOT EXISTS FOR (n:{label}) ON EACH [{on}]').consume()
        s.run('CALL db.awaitIndexes(300)').consume()

        print('NODES')
        for label, key in LABEL_KEYS.items():
            rows = list(g.nodes[label].values())
            for batch in _batches(rows):
                s.execute_write(lambda tx, b=batch: tx.run(
                    f'UNWIND $rows AS row MERGE (n:{label} {{{key}: row.{key}}}) '
                    f'SET n = row, n._load = $run',
                    rows=b, run=run).consume())
            print(f'  {label:<16} {len(rows):>7,}')

        print('RELATIONSHIPS')
        for (t, a, b), rows in g.rels.items():
            payload = [{'a': x, 'b': y, 'p': p} for x, y, p in rows]
            # rel_key tells apart several edges of one type between one pair
            # (two mentions of the same nation); MERGE on it when present.
            keyed = any('rel_key' in p for _, _, p in rows)
            pattern = f'[r:{t} {{rel_key: row.p.rel_key}}]' if keyed else f'[r:{t}]'
            for batch in _batches(payload):
                s.execute_write(lambda tx, bt=batch: tx.run(
                    f'UNWIND $rows AS row '
                    f'MATCH (a:{a} {{{LABEL_KEYS[a]}: row.a}}) '
                    f'MATCH (b:{b} {{{LABEL_KEYS[b]}: row.b}}) '
                    f'MERGE (a)-{pattern}->(b) SET r = row.p, r._load = $run',
                    rows=bt, run=run).consume())
            print(f'  ({a})-[:{t}]->({b})'.ljust(52) + f'{len(rows):>7,}')

        if prune:
            pruned = 0
            for (t, a, b) in g.rels:
                pruned += s.run(
                    f'MATCH (:{a})-[r:{t}]->(:{b}) WHERE coalesce(r._load, "") <> $run '
                    f'CALL (r) {{ DELETE r }} IN TRANSACTIONS OF 5000 ROWS RETURN count(*) AS c',
                    run=run).single()['c']
            for label in LABEL_KEYS:
                pruned += s.run(
                    f'MATCH (n:{label}) WHERE coalesce(n._load, "") <> $run '
                    f'CALL (n) {{ DETACH DELETE n }} IN TRANSACTIONS OF 5000 ROWS RETURN count(*) AS c',
                    run=run).single()['c']
            print(f'pruned {pruned:,} stale nodes/relationships')

        nodes, rels = db_counts(s)
    driver.close()

    print('\nCOUNTS (database vs files)')
    bad = 0
    for label in LABEL_KEYS:
        want, got = len(g.nodes[label]), nodes.get(label, 0)
        bad += want != got
        print(f'  {label:<16} {got:>7,} / {want:>7,}  {"ok" if want == got else "MISMATCH"}')
    for sig, rows in sorted(g.rels.items(), key=lambda kv: -len(kv[1])):
        want, got = len(rows), rels.get(sig, 0)
        bad += want != got
        t, a, b = sig
        print(f'  ({a})-[:{t}]->({b})'.ljust(52) + f'{got:>7,} / {want:>7,}  {"ok" if want == got else "MISMATCH"}')
    extra = set(rels) - set(g.rels)
    for sig in extra:
        bad += 1
        print(f'  unexpected relationship in database: {sig} x{rels[sig]}')
    print(f'  TOTAL {sum(nodes.values()):,} nodes, {sum(rels.values()):,} relationships'
          f' — {"all match" if not bad else f"{bad} mismatches"}')
    return bad


# ── Verification: does the graph reproduce what the pages show? ───────────── #

def verify(g):
    """Run the queries a database-backed site would run, and check each answer
    against the same thing computed from the files (what the pages show now)."""
    import story_stats
    driver, database = connect()
    fails = 0

    def check(name, got, want, detail=''):
        nonlocal fails
        ok = got == want
        fails += not ok
        print(f'  [{"ok" if ok else "FAIL"}] {name}{(" — " + detail) if detail else ""}')
        if not ok:
            print(f'         database: {str(got)[:300]}\n         files:    {str(want)[:300]}')

    watchlist = json.load(open(os.path.join(DATA, 'watchlist.json'), encoding='utf-8'))['stories']
    feed_rows = read_csv(os.path.join(DATA, 'intel_feed.csv'))
    updates = read_csv(os.path.join(DATA, 'story_updates.csv'))
    UN, UNGA = 'st-20261103-united-nations', 'st-20260922-unga81-general-debate'

    with driver.session(database=database) as s:
        q = lambda cypher, **kw: [r.data() for r in s.run(cypher, **kw)]

        print('Timelines page (tracker.html) — merged timeline per story')
        beats = q('MATCH (u:StoryUpdate)-[:UPDATE_OF]->(st:Story) '
                  'RETURN st.story_id AS story_id, u.date AS date, u.headline AS headline, '
                  'u.summary AS summary, u.found_at AS found_at, u.url AS url')
        linked = q('MATCH (f:FeedItem)-[:LINKED_TO]->(st:Story) '
                   'WITH f, collect(st.story_id) AS ids '
                   'RETURN f.created_at AS created_at, f.summary AS summary, '
                   'f.full_text AS full_text, f.source_url AS source_url, ids')
        for r in linked:
            r['linked_story_ids'] = ';'.join(r.pop('ids'))
        got = story_stats.compute(beats, linked)
        want = story_stats.compute(updates, feed_rows)
        check('every story: merged entry count + last news day', got, want,
              f'{len(want)} stories, {sum(v["count"] for v in want.values()):,} timeline entries')

        top = q('MATCH (st:Story {story_id: $sid}) '
                'CALL (st) { MATCH (u:StoryUpdate)-[:UPDATE_OF]->(st) '
                "  RETURN u.date AS day, u.headline AS head, 'beat' AS kind "
                '  UNION ALL MATCH (f:FeedItem)-[:LINKED_TO]->(st) '
                "  RETURN left(f.created_at, 10) AS day, coalesce(f.summary, f.full_text) AS head, 'feed' AS kind } "
                'RETURN day, kind, head ORDER BY day DESC LIMIT 5', sid=UN)
        print(f'    newest entries of the UN story (before dedup):')
        for r in top:
            print(f'      {r["day"]}  {r["kind"]:<4}  {(r["head"] or "")[:80]}')

        print('Feed page (feed.html) — story chips')
        got = {r['sid']: r['c'] for r in q('MATCH (f:FeedItem)-[:LINKED_TO]->(st:Story) '
                                           'RETURN st.story_id AS sid, count(f) AS c')}
        want = Counter(sid for r in feed_rows for sid in set(filter(None, (r.get('linked_story_ids') or '').split(';'))))
        check('feed rows carrying each story chip', got, dict(want))
        got = q('MATCH (f:FeedItem)-[:LINKED_TO]->(:Story {story_id: $sid}) '
                'MATCH (f)-[:FROM_SOURCE]->(src:Source) RETURN DISTINCT src.name AS n', sid=UN)
        check('UN story chip only on UN News rows (link_sources)', sorted(r['n'] for r in got), ['UN News'])

        print('Feed page — newest rows (database.json "tweets")')
        db_json = json.load(open(os.path.join(DATA, 'database.json'), encoding='utf-8'))
        n = len(db_json['tweets'])
        got = q('MATCH (f:FeedItem) RETURN f.created_at AS c ORDER BY c DESC LIMIT $n', n=n)
        want = sorted((r['created_at'] for r in feed_rows), reverse=True)[:n]
        check(f'newest {n} feed timestamps', [r['c'] for r in got], want)
        stale = sorted(t['created_at'] for t in db_json['tweets'])[-1] < want[0]
        print(f'    (database.json on disk: newest {max(t["created_at"] for t in db_json["tweets"])}'
              f'{" — older than intel_feed.csv, rebuild pending" if stale else ""})')

        print('Branches (parent_id)')
        got = sorted(r['c'] for r in q('MATCH (c:Story)-[:CHILD_OF]->(:Story {story_id: $sid}) '
                                       'RETURN c.story_id AS c', sid=UN))
        want = sorted(st['story_id'] for st in watchlist if st.get('parent_id') == UN)
        check('branches of the UN story', got, want, ', '.join(got))
        got = q('MATCH (b:Story)-[:CHILD_OF]->(p:Story) '
                'OPTIONAL MATCH (u:StoryUpdate)-[:UPDATE_OF]->(b) '
                'RETURN p.story_id AS parent, b.story_id AS branch, count(u) AS beats')
        want_beats = Counter(u['story_id'] for u in updates)
        check('branch beat counts',
              {r['branch']: r['beats'] for r in got},
              {st['story_id']: want_beats[st['story_id']] for st in watchlist if st.get('parent_id')})

        print('Map page (map.html) — incidents per operation')
        incidents = read_csv(os.path.join(DATA, 'incidents.csv'))
        got = {r['op']: r['c'] for r in q('MATCH (i:Incident)-[:PART_OF]->(o:Operation) '
                                          'RETURN o.name AS op, count(i) AS c')}
        want = Counter()
        seen = set()
        for r in incidents:                     # duplicate ids collapse, like MERGE
            if r['incident_id'] in seen:
                continue
            seen.add(r['incident_id'])
            if r.get('operation_name'):
                want[r['operation_name']] += 1
        check('incidents per operation', got, dict(want), f'{len(want)} operations')
        got = q('MATCH (i:Incident) RETURN count(i) AS c')[0]['c']
        check('incidents (database.json "incidents")', got, len(db_json['incidents']))

        print('Speeches page (speeches.html)')
        out = json.load(open(os.path.join(DATA, 'un_speeches', 'unga81.json'), encoding='utf-8'))
        got = {r['label']: sorted(r['m']) for r in q(
            'MATCH (sp:Speech)-[:IN_CLUSTER]->(c:SpeechCluster)-[:PART_OF]->(:SpeechAnalysis {analysis_id: "unga81"}) '
            'RETURN c.label AS label, collect(sp.iso2) AS m')}
        check('cluster membership', got, {c['label']: sorted(c['members']) for c in out['clusters']})
        a = q('MATCH (a:SpeechAnalysis {analysis_id: "unga81"})-[:ANALYSIS_OF]->(st:Story) '
              'RETURN st.story_id AS sid, a.edges_json AS edges, a.friendliness_order AS o, '
              'size(a.friendliness_tri) AS tri')[0]
        check('analysis hangs off the UNGA 81 story', a['sid'], UNGA)
        check('friendliness matrix + network edges intact',
              (json.loads(a['edges']), a['o'], a['tri']),
              (out['edges'], out['friendliness']['order'], len(out['friendliness']['tri'])))
        got = q('MATCH (x:Speech)-[m:MENTIONS {via: "speech"}]->(y:Speech) '
                'WHERE x.iso2 = "AE" RETURN y.iso2 AS to, m.stance AS stance ORDER BY to')
        want = sorted((m['iso2'], m['stance']) for n in out['nations'] if n['iso2'] == 'AE'
                      for m in n['mentions'])
        check('UAE address mentions', [(r['to'], r['stance']) for r in got], want)

        print('UN daily reporting archive')
        reports = read_csv(os.path.join(DATA, 'un_daily', 'reports.csv'))
        got = {r['o']: r['c'] for r in q('MATCH (r:UNReport) RETURN r.organ AS o, count(r) AS c')}
        check('reports per organ', got, dict(Counter(r['organ'] for r in reports)))

        print('Sources')
        got = {r['sid']: r['c'] for r in q('MATCH (st:Story)-[:SELECTED_SOURCE]->(:Source) '
                                           'RETURN st.story_id AS sid, count(*) AS c')}
        want = {st['story_id']: len(set(st['sources']['selected'])) for st in watchlist
                if (st.get('sources') or {}).get('selected')}
        check('per-story source selections', got, want)

    driver.close()
    print(f'\n{"all checks passed" if not fails else f"{fails} checks FAILED"}')
    return fails


def main():
    args = sys.argv[1:]
    g = build()
    if '--show' in args:
        show(g, args[args.index('--show') + 1])
    elif '--load' in args:
        sys.exit(1 if load(g, wipe='--wipe' in args, prune='--no-prune' not in args) else 0)
    elif '--verify' in args:
        sys.exit(1 if verify(g) else 0)
    else:
        report(g)


if __name__ == '__main__':
    main()
