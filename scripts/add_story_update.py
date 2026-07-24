#!/usr/bin/env python3
"""
Safe, validated append of agent-researched story updates to
data/story_updates.csv. The scheduled-task agent MUST use this instead of
hand-writing CSV rows directly — hand-written CSV mutation is exactly the
failure pattern that let incident promotion silently break for months.

Reads one JSON object, or a JSON array of objects, from stdin. Each object:
    {
      "story_id": "st-20260504-strait-of-hormuz",   (required, must exist in watchlist.json)
      "date": "2026-07-03",                          (required, YYYY-MM-DD)
      "headline": "...",                              (required, <=140 chars)
      "summary": "...",                               (required)
      "source_name": "Reuters",                       (required)
      "url": "https://...",                           (optional but recommended — used for dedup)
      "status": "developing",                         (optional: new|developing|confirmed|disputed|resolution; default "developing")
      "severity": "4",                                (optional)
      "origin": "websearch",                          (optional; default "websearch")
      "image": "https://.../photo.jpg"                (optional — if omitted, the
                                                       source article's og:image
                                                       is scraped from `url`)
    }

Deduplicates on (story_id, url) when url is present, else on
(story_id, date, normalized headline). Never edits story status —
that is exclusively a user action via the tracker UI.

Each update also gets a lead image: an explicit "image" in the payload wins,
otherwise the source article at `url` is fetched and its og:image / twitter:image
is used (best-effort — a miss just leaves the beat imageless, never an error).
Pass --no-fetch to skip that network step (offline runs / tests).

Usage (from project root):
    echo '{"story_id": "...", ...}' | python3 scripts/add_story_update.py
    cat updates.json | python3 scripts/add_story_update.py [--dry-run] [--no-fetch]
    python3 scripts/add_story_update.py --backfill-images [--dry-run]
        (fill the image column on existing beats that have a url but no image)
"""

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.request import urlopen, Request

from story_dedup import build_index, is_fuzzy_dup, note_accepted

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST_JSON = os.path.join(ROOT, 'data', 'watchlist.json')
STORY_UPDATES_CSV = os.path.join(ROOT, 'data', 'story_updates.csv')

STORY_UPDATE_COLUMNS = [
    'story_id', 'update_id', 'date', 'headline', 'summary',
    'source_name', 'url', 'status', 'severity', 'origin', 'found_at', 'image',
]
VALID_STATUS = {'new', 'developing', 'confirmed', 'disputed', 'resolution'}
REQUIRED_FIELDS = ('story_id', 'date', 'headline', 'summary', 'source_name')

UA = ('Mozilla/5.0 (compatible; OSINTDaily/1.0; story-tracker; '
      '+https://github.com/)')

# Meta tags that carry a page's lead image, most-preferred first.
_OG_IMAGE_PATTERNS = [
    r'<meta[^>]+property=["\']og:image(?::url)?["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::url)?["\']',
    r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']',
]


def scrape_og_image(url, timeout=12):
    """Best-effort lead image (og:image / twitter:image) for an article URL.

    Returns '' on ANY problem — a missing image must never fail an update or
    block the routine, so every error is swallowed. Only reads the first chunk
    of the response (the <head> is all we need) and only trusts absolute URLs.
    """
    if not url or not url.startswith(('http://', 'https://')):
        return ''
    try:
        req = Request(url, headers={'User-Agent': UA})
        with urlopen(req, timeout=timeout) as r:
            if 'html' not in (r.headers.get('Content-Type', '') or '').lower():
                return ''
            raw = r.read(300000)  # ~300 KB covers <head> on real news pages
    except Exception:
        return ''
    html = raw.decode('utf-8', 'ignore')
    for pat in _OG_IMAGE_PATTERNS:
        m = re.search(pat, html, re.IGNORECASE)
        if not m:
            continue
        img = m.group(1).strip()
        if img.startswith('//'):
            img = 'https:' + img
        if img.startswith(('http://', 'https://')):
            return img
    return ''


def load_story_ids():
    if not os.path.exists(WATCHLIST_JSON):
        return set()
    with open(WATCHLIST_JSON, encoding='utf-8') as f:
        doc = json.load(f)
    return {s['story_id'] for s in doc.get('stories', [])}


def load_existing():
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


def validate(item):
    missing = [f for f in REQUIRED_FIELDS if not (item.get(f) or '').strip()]
    if missing:
        return f'missing required field(s): {", ".join(missing)}'
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', item['date']):
        return f'date must be YYYY-MM-DD, got: {item["date"]!r}'
    if len(item['headline']) > 140:
        return 'headline must be <=140 chars'
    status = item.get('status', 'developing')
    if status not in VALID_STATUS:
        return f'invalid status {status!r}, must be one of {sorted(VALID_STATUS)}'
    return None


def backfill_images(dry_run=False, limit=None):
    """Fill the `image` column on already-recorded beats that have a source
    `url` but no image yet — the routine now scrapes og:image on insert, but
    older rows (and any live miss) predate that. Idempotent: only ever fills
    empties, never overwrites. Rewrites the CSV in place.
    """
    if not os.path.exists(STORY_UPDATES_CSV):
        print('No story_updates.csv — nothing to backfill.')
        return
    with open(STORY_UPDATES_CSV, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    todo = [r for r in rows if (r.get('url') or '').strip() and not (r.get('image') or '').strip()]
    if limit:
        todo = todo[:limit]
    print(f'Backfilling images for {len(todo)} beat(s) with a url but no image.')

    filled = 0
    for r in todo:
        img = scrape_og_image(r['url'].strip())
        if img:
            r['image'] = img
            filled += 1
            print(f'  + [{r["story_id"]}] {r["headline"][:60]} -> {img[:70]}')
        else:
            print(f'  · [{r["story_id"]}] {r["headline"][:60]} -> (no og:image)')

    print(f'Filled {filled} of {len(todo)}.')
    if not filled or dry_run:
        if dry_run:
            print('Dry run — no changes written.')
        return

    with open(STORY_UPDATES_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=STORY_UPDATE_COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in STORY_UPDATE_COLUMNS})
    print(f'Rewrote story_updates.csv with {filled} new image(s).')


def main():
    dry_run = '--dry-run' in sys.argv
    no_fetch = '--no-fetch' in sys.argv  # skip og:image scraping (offline/tests)

    if '--backfill-images' in sys.argv:
        backfill_images(dry_run=dry_run)
        return

    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit('No input on stdin. Pipe a JSON object or array of objects.')

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f'Invalid JSON on stdin: {e}')

    items = payload if isinstance(payload, list) else [payload]
    known_story_ids = load_story_ids()
    existing_rows, existing_keys = load_existing()
    fuzzy_index = build_index(existing_rows)

    accepted, rejected = [], []
    now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    for item in items:
        err = validate(item)
        if err:
            rejected.append((item.get('story_id', '?'), err))
            continue
        if known_story_ids and item['story_id'] not in known_story_ids:
            rejected.append((item['story_id'], 'unknown story_id (not in watchlist.json)'))
            continue

        url = (item.get('url') or '').strip()
        headline = ' '.join(item['headline'].split())
        key = (item['story_id'], 'url', url) if url else (item['story_id'], 'text', item['date'], headline)
        if key in existing_keys:
            rejected.append((item['story_id'], 'duplicate (already recorded)'))
            continue
        # Fuzzy: same event scraped with different wording / from another source.
        if is_fuzzy_dup(item['story_id'], item['date'], headline, fuzzy_index):
            rejected.append((item['story_id'], 'duplicate (near-match of an existing beat)'))
            continue
        existing_keys.add(key)
        note_accepted(item['story_id'], item['date'], headline, fuzzy_index)

        # Lead image: an explicit one in the payload wins; otherwise scrape the
        # source article's og:image (unless --no-fetch). Best-effort, '' on miss.
        image = (item.get('image') or '').strip()
        if not image and url and not no_fetch:
            image = scrape_og_image(url)

        update_id_num = next_update_id(existing_rows + accepted, item['story_id'])
        accepted.append({
            'story_id': item['story_id'],
            'update_id': f'{item["story_id"]}-u{update_id_num:03d}',
            'date': item['date'],
            'headline': headline,
            'summary': ' '.join(item['summary'].split()),
            'source_name': item['source_name'],
            'url': url,
            'status': item.get('status', 'developing'),
            'severity': str(item.get('severity', '')),
            'origin': item.get('origin', 'websearch'),
            'found_at': now_iso,
            'image': image,
        })

    print(f'Accepted: {len(accepted)}')
    for sid, err in rejected:
        print(f'  REJECTED [{sid}]: {err}')

    if not accepted:
        return
    if dry_run:
        print('Dry run — no changes written.')
        return

    write_header = not os.path.exists(STORY_UPDATES_CSV)
    with open(STORY_UPDATES_CSV, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=STORY_UPDATE_COLUMNS, quoting=csv.QUOTE_ALL)
        if write_header:
            w.writeheader()
        w.writerows(accepted)

    print(f'Appended {len(accepted)} rows to story_updates.csv.')


if __name__ == '__main__':
    main()
