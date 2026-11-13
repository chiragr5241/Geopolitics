#!/usr/bin/env python3
"""
A tracked story's real update count and last-pulled date, computed from the
data rather than from counters that scripts are supposed to bump.

The counters in watchlist.json (`update_count`, `last_update_at`) drifted
because only SOME writers bumped them:
  - update_stories.py / add_story_update.py bump them,
  - link_youtube.py appends video beats and never did,
  - link_stories.py tags feed tweets onto stories and never did,
and the story-tracker routine (the only one that commits watchlist.json) can be
disabled for weeks while the other two keep adding coverage. The main page also
counted live over database.json, which only ships the newest 2000 tweets, so a
story's count SHRANK as its linked tweets aged out of that window (US-Iran:
~200 shown vs ~1000 real).

So the count is derived here from the two records of what actually happened:
  - data/story_updates.csv  — curated beats (WebSearch, YouTube, intel matches)
  - data/intel_feed.csv     — every feed row, via its `linked_story_ids`
merged and deduped EXACTLY like js/util.js buildStoryEntries() (key =
date|normHead(headline)), so the number equals the timeline the site would
render if it had every tweet.

`last_update_at` becomes the newest day anything landed on the story (a beat's
found_at, else its date; a tweet's created_at), never earlier than what the
story already claims — it is also update_stories.py's forward-scan cursor and
the story-tracker's "oldest first" queue key, so it must only move forward.

build_db.py applies this to the stories it exports (so every routine publishes
correct numbers, whether or not it commits watchlist.json). The CLI persists it
to watchlist.json:

    python3 scripts/story_stats.py [--dry-run]
    (also reachable as: python3 scripts/add_story_update.py --recount)
"""

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data')
WATCHLIST_JSON = os.path.join(DATA_DIR, 'watchlist.json')
STORY_UPDATES_CSV = os.path.join(DATA_DIR, 'story_updates.csv')
INTEL_FEED_CSV = os.path.join(DATA_DIR, 'intel_feed.csv')

csv.field_size_limit(sys.maxsize)


def norm_head(s):
    """Mirror of normHead() in js/util.js — keep the two in lockstep."""
    s = re.sub(r'[^a-z0-9 ]', ' ', str(s or '').lower())
    return re.sub(r'\s+', ' ', s).strip()[:70]


def compute(story_updates, feed_rows):
    """story_id -> {'count': int, 'last': 'YYYY-MM-DD' or ''}.

    story_updates / feed_rows are iterables of dicts (CSV rows or database
    rows). Curated beats are keyed first so a tweet duplicating a beat is the
    one dropped, as on the site.
    """
    seen = {}    # story_id -> set of dedup keys
    last = {}    # story_id -> newest day
    beat_urls = {}   # story_id -> urls its beats already cover

    def add(sid, key, day):
        keys = seen.setdefault(sid, set())
        if key in keys:
            return
        keys.add(key)
        if day > last.get(sid, ''):
            last[sid] = day

    for u in story_updates:
        sid = u.get('story_id')
        if not sid:
            continue
        key = (u.get('date') or '') + '|' + norm_head(u.get('headline') or u.get('summary'))
        day = (u.get('found_at') or '')[:10] or (u.get('date') or '')[:10]
        add(sid, key, day)
        if u.get('url'):
            beat_urls.setdefault(sid, set()).add(u['url'])

    for r in feed_rows:
        ids = [s for s in str(r.get('linked_story_ids') or '').split(';') if s]
        if not ids:
            continue
        day = (r.get('created_at') or '')[:10]
        key = day + '|' + norm_head(r.get('summary') or r.get('full_text'))
        url = r.get('source_url') or ''
        for sid in ids:
            # Same article as a beat, even when deep enrichment rewrote its
            # summary so the headline key no longer matches.
            if url and url in beat_urls.get(sid, ()):
                continue
            add(sid, key, day)

    return {sid: {'count': len(keys), 'last': last.get(sid, '')}
            for sid, keys in seen.items()}


def apply(stories, stats):
    """Write stats onto story dicts in place. Returns [(sid, before, after)]."""
    changed = []
    for s in stories:
        sid = s.get('story_id')
        st = stats.get(sid, {'count': 0, 'last': ''})
        before = (s.get('update_count'), s.get('last_update_at'))
        s['update_count'] = st['count']
        if st['last'] and st['last'] > (s.get('last_update_at') or ''):
            s['last_update_at'] = st['last']
        after = (s['update_count'], s.get('last_update_at'))
        if before != after:
            changed.append((sid, before, after))
    return changed


def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def compute_from_files():
    return compute(_read_csv(STORY_UPDATES_CSV), _read_csv(INTEL_FEED_CSV))


def recount(dry_run=False):
    """Persist the computed stats to watchlist.json."""
    if not os.path.exists(WATCHLIST_JSON):
        print('Nothing to recount.')
        return
    with open(WATCHLIST_JSON, encoding='utf-8') as f:
        doc = json.load(f)
    changed = apply(doc.get('stories', []), compute_from_files())
    for sid, before, after in changed:
        print(f'  {sid}: count {before[0]} -> {after[0]}, '
              f'last_update_at {before[1]} -> {after[1]}')
    if dry_run:
        print(f'Dry run — {len(changed)} story(ies) would change.')
        return
    if changed:
        doc['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(WATCHLIST_JSON, 'w', encoding='utf-8') as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
            f.write('\n')
    print(f'Recounted {len(changed)} story(ies).')


if __name__ == '__main__':
    recount(dry_run='--dry-run' in sys.argv)
