#!/usr/bin/env python3
"""
parity_check.py — does the API serve what the static files would?

Rebuilds feed.json / database.json from the CURRENT files with build_db.py
(into a temp dir — data/ is not touched), then compares them, section by
section, with what api/graph.py assembles from Neo4j. Also compares
speeches(81) with data/un_speeches/unga81.json.

Equivalences that are not differences:
  - '' vs a missing key vs None
  - TRUE / true / 1 (booleans are re-cased per file)
  - 32 vs 32.0 (numbers compare numerically)
  - 'A; B' vs 'A;B' vs ';A;B' (the pages split ';' lists, trim, drop empties)

One known difference is EXPECTED and reported as such: build_db.py's SQLite
`tweets` table keys on created_at alone, so the files silently drop feed rows
that share a timestamp with another (wire pulls stamp whole batches alike).
The graph keeps them, so the API's newest-2000 window holds those extra rows
and reaches slightly less far back.

Run after `scripts/neo4j_migrate.py --load` on the same files:

    api/.venv/bin/python api/parity_check.py
"""

import json
import os
import re
import sys
from collections import Counter
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import graph  # noqa: E402
import build_db  # noqa: E402  (graph put scripts/ on sys.path)

BOOLS = {'true': 'TRUE', '1': 'TRUE', 'false': 'FALSE', '0': 'FALSE'}


def norm(v):
    if v is None or v == '' or v == [] or v == {}:
        return None
    if isinstance(v, bool):
        return 'TRUE' if v else 'FALSE'
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    if isinstance(v, str):
        s = re.sub(r';+', ';', re.sub(r'\s*;\s*', ';', v.strip())).strip(';') if ';' in v else v.strip()
        if s.lower() in BOOLS:
            return BOOLS[s.lower()]
        try:
            return round(float(s), 6)
        except ValueError:
            return s
    if isinstance(v, list):
        return [norm(x) for x in v]
    if isinstance(v, dict):
        out = {k: norm(x) for k, x in v.items()}
        return {k: x for k, x in out.items() if x is not None}
    return v


def diff_rows(name, got, want, key, ignore=()):
    """Compare two lists of dicts matched on `key`; print a summary."""
    g = {key(r): r for r in got}
    w = {key(r): r for r in want}
    only_g, only_w = set(g) - set(w), set(w) - set(g)
    field_diffs = {}
    for k in set(g) & set(w):
        a, b = norm(g[k]), norm(w[k])
        for f in set(a) | set(b):
            if f in ignore:
                continue
            if a.get(f) != b.get(f):
                field_diffs.setdefault(f, []).append((k, a.get(f), b.get(f)))
    order_ok = [key(r) for r in got if key(r) in w] == [key(r) for r in want if key(r) in g]
    ok = not only_g and not only_w and not field_diffs
    print(f'  [{"ok" if ok else "DIFF"}] {name}: api {len(got)} / files {len(want)}'
          f'{"" if order_ok else "  (order differs)"}')
    for label, s in (('only in api', only_g), ('only in files', only_w)):
        if s:
            print(f'         {label}: {len(s)}  e.g. {[x[:90] for x in sorted(map(str, s))[:2]]}')
    for f, rows in sorted(field_diffs.items(), key=lambda kv: -len(kv[1])):
        k, a, b = rows[0]
        print(f'         field {f!r}: {len(rows)} rows differ  e.g. {str(k)[:50]}: '
              f'api={str(a)[:70]!r} files={str(b)[:70]!r}')
    return ok


def reference():
    tmp = tempfile.mkdtemp(prefix='parity-')
    build_db.DB_PATH = os.path.join(tmp, 'geopolitics.db')
    build_db.OUT_PATH = os.path.join(tmp, 'database.json')
    build_db.FEED_PATH = os.path.join(tmp, 'feed.json')
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        build_db.build()
    return (json.load(open(build_db.FEED_PATH, encoding='utf-8')),
            json.load(open(build_db.OUT_PATH, encoding='utf-8')))


def main():
    print('building reference JSON from the files…')
    ref_feed, ref_full = reference()
    print('assembling the same from Neo4j…')
    api_full = graph.bootstrap('full')
    api_feed = graph.bootstrap('feed')
    ok = True

    print('feed.json / database.json')
    ok &= set(api_feed) == set(ref_feed) and set(api_full) == set(ref_full)
    print(f'  [{"ok" if set(api_feed) == set(ref_feed) else "DIFF"}] feed keys {sorted(api_feed)}')
    ok &= diff_rows('watchlist', api_feed['watchlist'], ref_feed['watchlist'],
                    key=lambda r: r['story_id'])
    ok &= diff_rows('story_updates', api_feed['story_updates'], ref_feed['story_updates'],
                    key=lambda r: r['update_id'])
    ok &= diff_rows('sources', api_feed['sources'], ref_feed['sources'], key=lambda r: r['source_id'])
    ok &= diff_rows('story_images', api_feed['story_images'], ref_feed['story_images'],
                    key=lambda r: r['url'])
    # SQLite's tweets table keys on created_at alone and drops rows that share
    # a timestamp; the graph keeps them. So compare on (created_at, full_text).
    tkey = lambda r: (r['created_at'], r['full_text'])  # noqa: E731
    if not diff_rows('tweets (newest 2000)', api_feed['tweets'], ref_feed['tweets'],
                     key=tkey, ignore={'feed_id'}):
        shared = Counter(r['created_at'] for r in graph.tweets(limit=10**6))
        ref_keys = {tkey(r) for r in ref_feed['tweets']}
        api_keys = {tkey(r) for r in api_feed['tweets']}
        extra = [r for r in api_feed['tweets'] if tkey(r) not in ref_keys]
        pushed = [r for r in ref_feed['tweets'] if tkey(r) not in api_keys]
        oldest = min(r['created_at'] for r in api_feed['tweets'])
        expected = (all(shared[r['created_at']] > 1 for r in extra)
                    and all(r['created_at'] <= oldest for r in pushed))
        print(f'         -> {"EXPECTED" if expected else "UNEXPECTED"}: {len(extra)} rows the files drop '
              f'(timestamp shared with another row), {len(pushed)} older rows pushed out of the window')
        ok &= expected
    ok &= diff_rows('incidents', api_full['incidents'], ref_full['incidents'],
                    key=lambda r: r['incident_id'])
    ok &= diff_rows('operations', api_full['operations'], ref_full['operations'],
                    key=lambda r: r['operation_name'])
    ok &= diff_rows('imagery', api_full['imagery'], ref_full['imagery'],
                    key=lambda r: (r['incident_id'], r['url']))
    m_api, m_ref = api_full['_meta'], ref_full['_meta']
    same_counts = {k: v for k, v in m_ref['counts'].items() if m_api['counts'].get(k) != v}
    print(f'  [{"ok" if not same_counts else "DIFF"}] _meta.counts'
          f'{"" if not same_counts else f" files={same_counts} api=" + str({k: m_api["counts"].get(k) for k in same_counts})}')
    ok &= not same_counts

    print('speeches (unga81.json)')
    want = json.load(open(os.path.join(graph.ROOT, 'data', 'un_speeches', 'unga81.json'), encoding='utf-8'))
    got = graph.speeches(81)
    top = [k for k in want if k not in ('nations', 'replies', 'clusters') and norm(got.get(k)) != norm(want[k])]
    print(f'  [{"ok" if not top else "DIFF"}] top-level fields{"" if not top else ": " + ", ".join(top)}')
    ok &= not top
    ok &= diff_rows('nations', got['nations'], want['nations'], key=lambda r: r['video_id'])
    ok &= diff_rows('replies', got['replies'], want['replies'], key=lambda r: r['video_id'])
    ok &= diff_rows('clusters', got['clusters'], want['clusters'], key=lambda r: r['id'])

    graph.close()
    print('\nall sections match' if ok else '\nsome sections differ (see above)')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
