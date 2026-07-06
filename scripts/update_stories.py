#!/usr/bin/env python3
"""
Deterministically match new intel_feed rows against active watchlist
stories and append matches to data/story_updates.csv.

For each active story in data/watchlist.json, scans intel_feed rows newer
than the story's last_update_at. A row matches when it shares at least one
country with the story AND either hits >=2 of the story's keywords, or hits
1 keyword and its lat/lng falls within ~2 degrees of the story's seed
location. Deterministic, no API key, idempotent (dedup by story_id+url or
story_id+date+headline via add_story_update.py's append logic).

Usage (from project root):
    python3 scripts/update_stories.py [--dry-run]
"""

import csv
import json
import math
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTEL_CSV = os.path.join(ROOT, 'data', 'intel_feed.csv')
WATCHLIST_JSON = os.path.join(ROOT, 'data', 'watchlist.json')
STORY_UPDATES_CSV = os.path.join(ROOT, 'data', 'story_updates.csv')

STORY_UPDATE_COLUMNS = [
    'story_id', 'update_id', 'date', 'headline', 'summary',
    'source_name', 'url', 'status', 'severity', 'origin', 'found_at',
]


def parse_dt(value):
    value = (value or '').strip()
    if not value:
        return None
    norm = re.sub(r'\.\d+Z?$', '', value.replace('T', ' ')).rstrip('Z')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(norm[:19].strip(), fmt)
        except ValueError:
            continue
    return None


def haversine_deg(lat1, lng1, lat2, lng2):
    return math.hypot(lat1 - lat2, lng1 - lng2)


def load_watchlist():
    if not os.path.exists(WATCHLIST_JSON):
        return {'version': 1, 'updated_at': '', 'stories': []}
    with open(WATCHLIST_JSON, encoding='utf-8') as f:
        return json.load(f)


def save_watchlist(doc):
    doc['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(WATCHLIST_JSON, 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write('\n')


def load_existing_updates():
    if not os.path.exists(STORY_UPDATES_CSV):
        return [], set()
    with open(STORY_UPDATES_CSV, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    keys = set()
    for r in rows:
        if r.get('url'):
            keys.add((r['story_id'], 'url', r['url']))
        else:
            keys.add((r['story_id'], 'text', r['date'], ' '.join((r.get('headline') or '').split())))
    return rows, keys


def next_update_id(existing_rows, story_id):
    nums = []
    for r in existing_rows:
        if r['story_id'] != story_id:
            continue
        m = re.search(r'-u(\d+)$', r.get('update_id', ''))
        if m:
            nums.append(int(m.group(1)))
    return max(nums, default=0) + 1


def main():
    dry_run = '--dry-run' in sys.argv

    watchlist = load_watchlist()
    active_stories = [s for s in watchlist.get('stories', []) if s.get('status') == 'active']
    if not active_stories:
        print('No active stories in watchlist.json — nothing to update.')
        return

    if not os.path.exists(INTEL_CSV):
        print(f'{INTEL_CSV} not found.')
        return
    with open(INTEL_CSV, newline='', encoding='utf-8') as f:
        intel_rows = list(csv.DictReader(f))

    existing_rows, existing_keys = load_existing_updates()
    now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    new_updates = []
    story_hit_counts = {}

    for story in active_stories:
        story_id = story['story_id']
        last_update = parse_dt(story.get('last_update_at')) or parse_dt(story.get('marked_at')) or datetime.min
        countries = {c.upper() for c in story.get('seed', {}).get('countries', [])}
        keywords = [k.lower() for k in story.get('keywords', [])]
        seed_lat = story.get('seed', {}).get('lat')
        seed_lng = story.get('seed', {}).get('lng')

        for row in intel_rows:
            dt = parse_dt(row.get('created_at'))
            if not dt or dt <= last_update:
                continue
            row_countries = {c.strip().upper() for c in (row.get('countries') or '').split(';') if c.strip()}
            if countries and not (countries & row_countries):
                continue
            haystack = ' '.join([
                row.get('full_text', ''), row.get('summary', ''),
                row.get('entities_locations', ''), row.get('entities_orgs', ''),
            ]).lower()
            hits = sum(1 for kw in keywords if kw and kw in haystack)
            if hits >= 2:
                pass
            elif hits >= 1 and seed_lat is not None and seed_lng is not None and row.get('lat') and row.get('lng'):
                try:
                    if haversine_deg(float(seed_lat), float(seed_lng), float(row['lat']), float(row['lng'])) > 2.0:
                        continue
                except ValueError:
                    continue
            else:
                continue

            headline = ' '.join((row.get('summary') or row.get('full_text') or '').split())[:140]
            date_str = dt.strftime('%Y-%m-%d')
            key = (story_id, 'text', date_str, headline)
            if key in existing_keys:
                continue
            existing_keys.add(key)

            update_id_num = next_update_id(existing_rows + new_updates, story_id)
            new_updates.append({
                'story_id': story_id,
                'update_id': f'{story_id}-u{update_id_num:03d}',
                'date': date_str,
                'headline': headline,
                'summary': ' '.join((row.get('summary') or '').split()),
                'source_name': 'Spectator Index',
                'url': '',
                'status': 'developing',
                'severity': row.get('severity', ''),
                'origin': 'intel_feed',
                'found_at': now_iso,
            })
            story_hit_counts[story_id] = story_hit_counts.get(story_id, 0) + 1

    print(f'Active stories: {len(active_stories)}')
    print(f'New updates found: {len(new_updates)}')
    for sid, count in story_hit_counts.items():
        print(f'  {sid}: +{count}')

    if not new_updates:
        print('No new matches.')
        return
    if dry_run:
        print('Dry run — no changes written.')
        return

    write_header = not os.path.exists(STORY_UPDATES_CSV)
    with open(STORY_UPDATES_CSV, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=STORY_UPDATE_COLUMNS, quoting=csv.QUOTE_ALL)
        if write_header:
            w.writeheader()
        w.writerows(new_updates)

    for story in active_stories:
        if story['story_id'] in story_hit_counts:
            story['last_update_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            story['update_count'] = story.get('update_count', 0) + story_hit_counts[story['story_id']]
    save_watchlist(watchlist)

    print(f'Appended {len(new_updates)} rows to story_updates.csv and updated watchlist.json.')
    print('Next: python3 scripts/build_db.py')


if __name__ == '__main__':
    main()
