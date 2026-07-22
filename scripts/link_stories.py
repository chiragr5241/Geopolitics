#!/usr/bin/env python3
"""
Cross-link intel_feed rows to watchlist stories (the backbone of the story TAG).

Writes a `linked_story_ids` column onto data/intel_feed.csv: for every tweet, the
semicolon-joined ids of the stories it belongs to. This is what lets the frontend
tag a feed item / timeline entry with its story, and lets a story's tracker page
pull in ALL of its matching feed items retroactively (not just ones newer than
its last update).

Matching mirrors update_stories.py: a row matches a story when it shares >=1
country AND either hits >=2 of the story's keywords, or hits 1 keyword and its
lat/lng is within ~2 degrees of the story's seed location.

Links are recomputed from scratch every run against EVERY story currently in
watchlist.json, regardless of status:
  - a story that was DELETED from the watchlist simply stops matching -> its tag
    disappears everywhere (this is the "if the tracker is removed, remove the
    tag" behaviour);
  - archived / resolved stories still match -> their tag stays, and the frontend
    greys it out based on the story's status.

Deterministic, no API key, idempotent.

Usage (from project root):
    python3 scripts/link_stories.py [--dry-run]
"""

import csv
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTEL_CSV = os.path.join(ROOT, 'data', 'intel_feed.csv')
WATCHLIST_JSON = os.path.join(ROOT, 'data', 'watchlist.json')

LINK_COL = 'linked_story_ids'


def load_stories():
    if not os.path.exists(WATCHLIST_JSON):
        return []
    with open(WATCHLIST_JSON, encoding='utf-8') as f:
        doc = json.load(f)
    stories = []
    for s in doc.get('stories', []):
        seed = s.get('seed', {}) or {}
        stories.append({
            'story_id': s['story_id'],
            'countries': {c.upper() for c in seed.get('countries', [])},
            'keywords': [k.lower() for k in s.get('keywords', []) if k],
            'lat': seed.get('lat'),
            'lng': seed.get('lng'),
        })
    return stories


def matches(row, story):
    row_countries = {c.strip().upper()
                     for c in (row.get('countries') or '').split(';') if c.strip()}
    if story['countries'] and not (story['countries'] & row_countries):
        return False
    haystack = ' '.join([
        row.get('full_text', ''), row.get('summary', ''),
        row.get('entities_locations', ''), row.get('entities_orgs', ''),
    ]).lower()
    hits = sum(1 for kw in story['keywords'] if kw in haystack)
    if hits >= 2:
        return True
    if hits >= 1 and story['lat'] is not None and story['lng'] is not None \
            and row.get('lat') and row.get('lng'):
        try:
            if math.hypot(float(story['lat']) - float(row['lat']),
                          float(story['lng']) - float(row['lng'])) <= 2.0:
                return True
        except ValueError:
            return False
    return False


def main():
    dry_run = '--dry-run' in sys.argv
    stories = load_stories()

    with open(INTEL_CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if LINK_COL not in fieldnames:
        fieldnames.append(LINK_COL)

    changed = 0
    per_story = {}
    for row in rows:
        linked = [s['story_id'] for s in stories if matches(row, s)]
        for sid in linked:
            per_story[sid] = per_story.get(sid, 0) + 1
        new_val = ';'.join(linked)
        if (row.get(LINK_COL) or '') != new_val:
            changed += 1
        row[LINK_COL] = new_val

    linked_rows = sum(1 for r in rows if r.get(LINK_COL))
    print(f'link_stories: {len(rows)} intel rows, {linked_rows} linked to a story '
          f'({changed} changed)')
    for sid in sorted(per_story):
        print(f'  {sid}: {per_story[sid]}')

    if dry_run:
        print('Dry run — no changes written.')
        return

    tmp = INTEL_CSV + '.tmp'
    with open(tmp, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        for row in rows:
            w.writerow(row)
    os.replace(tmp, INTEL_CSV)
    print(f'  wrote {LINK_COL} -> data/intel_feed.csv')


if __name__ == '__main__':
    main()
