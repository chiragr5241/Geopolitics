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
      "source_name": "Reuters",                       (required — resolved
                                                       against data/sources.csv:
                                                       a misspelling is corrected
                                                       and reported, an unknown
                                                       name is kept but flagged,
                                                       and a source the story
                                                       deselected is rejected)
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
    python3 scripts/add_story_update.py --recount [--dry-run]
        (rebuild every story's update_count / last_update_at from
         story_updates.csv — repairs stories whose only channel is WebSearch)

    python3 scripts/add_story_update.py --backfill-sources [--dry-run]
        (resolve existing beats' source_name to a registry source_id and
         canonicalise the spelling; also migrates a pre-source_id CSV)
"""

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.request import urlopen, Request

from story_dedup import build_index, is_fuzzy_dup, note_accepted
from source_registry import (load_sources, resolve, story_sources,
                             record_fetch, save_sources)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST_JSON = os.path.join(ROOT, 'data', 'watchlist.json')
STORY_UPDATES_CSV = os.path.join(ROOT, 'data', 'story_updates.csv')

STORY_UPDATE_COLUMNS = [
    'story_id', 'update_id', 'date', 'headline', 'summary',
    'source_name', 'url', 'status', 'severity', 'origin', 'found_at', 'image',
    'source_id',
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


def load_stories():
    """story_id → story record, for the per-story source selection."""
    if not os.path.exists(WATCHLIST_JSON):
        return {}
    with open(WATCHLIST_JSON, encoding='utf-8') as f:
        doc = json.load(f)
    return {s['story_id']: s for s in doc.get('stories', []) if s.get('story_id')}


def bump_stories(counts):
    """Credit each story with the beats just written: bump `last_update_at` and
    `update_count` in watchlist.json.

    update_stories.py (tracker Step 1) already does this for the beats IT finds,
    but the WebSearch path came through here and never did — so a story with no
    intel_feed coverage stayed frozen at the day it was created no matter how
    much research landed on it. That is not cosmetic: Step 2 of the routine
    processes active stories "oldest last_update_at first, at most 10", so a
    story whose only channel is WebSearch reports itself permanently stale and
    sorts on a number that never moves. The Space Companies story sat at
    `update_count: 0, last_update_at: 2026-07-23` with 14 real beats on it.

    Same convention as update_stories.py: the date is when we found the news,
    not the article's own date.
    """
    if not counts or not os.path.exists(WATCHLIST_JSON):
        return []
    with open(WATCHLIST_JSON, encoding='utf-8') as f:
        doc = json.load(f)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    bumped = []
    for s in doc.get('stories', []):
        n = counts.get(s.get('story_id'))
        if not n:
            continue
        s['last_update_at'] = today
        s['update_count'] = int(s.get('update_count') or 0) + n
        bumped.append((s['story_id'], n, s['update_count']))
    if not bumped:
        return []
    doc['updated_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(WATCHLIST_JSON, 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write('\n')
    return bumped


def recount_stories(dry_run=False):
    """Rebuild every story's `update_count` / `last_update_at` from the CSV.

    Repairs the drift the missing bump above left behind — story_updates.csv is
    the record of what actually happened, so it is the authority. `update_count`
    becomes the story's real number of beats; `last_update_at` becomes the
    newest `found_at` among them (falling back to the beat date), never earlier
    than what the story already claims.
    """
    if not os.path.exists(WATCHLIST_JSON) or not os.path.exists(STORY_UPDATES_CSV):
        print('Nothing to recount.')
        return
    with open(STORY_UPDATES_CSV, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    counts, newest = {}, {}
    for r in rows:
        sid = r.get('story_id')
        if not sid:
            continue
        counts[sid] = counts.get(sid, 0) + 1
        seen = (r.get('found_at') or '')[:10] or (r.get('date') or '')[:10]
        if seen > newest.get(sid, ''):
            newest[sid] = seen
    with open(WATCHLIST_JSON, encoding='utf-8') as f:
        doc = json.load(f)
    changed = []
    for s in doc.get('stories', []):
        sid = s.get('story_id')
        n, seen = counts.get(sid, 0), newest.get(sid, '')
        before = (s.get('update_count'), s.get('last_update_at'))
        if n != (s.get('update_count') or 0):
            s['update_count'] = n
        if seen and seen > (s.get('last_update_at') or ''):
            s['last_update_at'] = seen
        after = (s.get('update_count'), s.get('last_update_at'))
        if before != after:
            changed.append((sid, before, after))
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


def backfill_sources(dry_run=False):
    """Give every already-recorded beat a `source_id`, resolving its free-text
    `source_name` through the registry — and canonicalise the spelling while
    we're there ("Reuters (via Internazionale)" → Reuters). Idempotent: rows
    that already carry a source_id are left alone.

    Also what migrates the CSV when the `source_id` column is new: the writer
    below refuses to append until the header matches, so this runs first.
    """
    if not os.path.exists(STORY_UPDATES_CSV):
        print('No story_updates.csv — nothing to backfill.')
        return
    with open(STORY_UPDATES_CSV, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    registry = load_sources()
    filled = corrected = unknown = 0
    unknown_names = set()
    for r in rows:
        if (r.get('source_id') or '').strip():
            continue
        res = resolve(r.get('source_name', ''), registry)
        if not res.ok:
            unknown += 1
            unknown_names.add(r.get('source_name', ''))
            continue
        r['source_id'] = res['source_id']
        filled += 1
        if res.corrected and r['source_name'] != res['name']:
            print(f'  ~ {r["source_name"]!r} -> {res["name"]!r}')
            r['source_name'] = res['name']
            corrected += 1

    print(f'Resolved {filled} beat(s) to a registry source '
          f'({corrected} name(s) corrected, {unknown} unresolved).')
    for n in sorted(unknown_names):
        print(f'  ! unresolved source name: {n!r}')
    if dry_run:
        print('Dry run — no changes written.')
        return

    with open(STORY_UPDATES_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=STORY_UPDATE_COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in STORY_UPDATE_COLUMNS})
    print('Rewrote story_updates.csv with the source_id column.')


def header_matches():
    """True when the CSV on disk has exactly the columns we append with.
    Appending rows through a DictWriter whose fieldnames differ from the file's
    own header silently shifts every value one column — so we check first."""
    if not os.path.exists(STORY_UPDATES_CSV):
        return True
    with open(STORY_UPDATES_CSV, newline='', encoding='utf-8') as f:
        header = next(csv.reader(f), [])
    return header == STORY_UPDATE_COLUMNS


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

    if '--backfill-sources' in sys.argv:
        backfill_sources(dry_run=dry_run)
        return

    if '--recount' in sys.argv:
        recount_stories(dry_run=dry_run)
        return

    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit('No input on stdin. Pipe a JSON object or array of objects.')

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f'Invalid JSON on stdin: {e}')

    items = payload if isinstance(payload, list) else [payload]
    stories = load_stories()
    known_story_ids = set(stories)
    existing_rows, existing_keys = load_existing()
    fuzzy_index = build_index(existing_rows)
    registry = load_sources()

    accepted, rejected = [], []
    corrections = []          # (input, canonical) — reported, never silent
    unknown_sources = []      # names the registry can't place — reported
    touched_sources = {}      # source_id → how many updates it produced now
    now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    for item in items:
        err = validate(item)
        if err:
            rejected.append((item.get('story_id', '?'), err))
            continue
        if known_story_ids and item['story_id'] not in known_story_ids:
            rejected.append((item['story_id'], 'unknown story_id (not in watchlist.json)'))
            continue

        # ── Source resolution ──────────────────────────────────────────────
        # The credit line is free text ("Reuter", "U.S. News / Reuters"), so
        # map it onto a registry entity: correct the spelling, keep the id, and
        # honour a source the user switched off for this story.
        story = stories.get(item['story_id'], {})
        res = resolve(item['source_name'], registry)
        source_id = res['source_id']
        source_name = item['source_name']
        if res.ok:
            if source_id in set(story_sources(story)['excluded']):
                rejected.append((item['story_id'],
                                 f'source {res["name"]!r} is deselected for this story'))
                continue
            if res.corrected:
                corrections.append((source_name, res['name']))
            source_name = res['name']          # store the canonical spelling
        else:
            # Never drop a real scoop because the registry hasn't heard of the
            # outlet — take it, keep the user's spelling, and flag it.
            unknown_sources.append(source_name)

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
            'source_name': source_name,
            'url': url,
            'status': item.get('status', 'developing'),
            'severity': str(item.get('severity', '')),
            'origin': item.get('origin', 'websearch'),
            'found_at': now_iso,
            'image': image,
            'source_id': source_id,
        })
        if source_id:
            touched_sources[source_id] = touched_sources.get(source_id, 0) + 1

    print(f'Accepted: {len(accepted)}')
    for sid, err in rejected:
        print(f'  REJECTED [{sid}]: {err}')
    for typed, canonical in corrections:
        print(f'  CORRECTED source: {typed!r} -> {canonical!r}')
    for name in sorted(set(unknown_sources)):
        print(f'  UNKNOWN source: {name!r} — kept, but not in data/sources.csv. '
              f'Verify it exists, then register it with source_registry.py --upsert.')

    if not accepted:
        return
    if dry_run:
        print('Dry run — no changes written.')
        return

    # A file written before the source_id column existed must be migrated
    # first, or every appended value lands one column off.
    if not header_matches():
        print('story_updates.csv predates the source_id column — migrating it first.')
        backfill_sources()

    write_header = not os.path.exists(STORY_UPDATES_CSV)
    with open(STORY_UPDATES_CSV, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=STORY_UPDATE_COLUMNS, quoting=csv.QUOTE_ALL)
        if write_header:
            w.writeheader()
        w.writerows(accepted)

    # Stamp the registry: these sources demonstrably produced news just now.
    if touched_sources:
        for sid, n in touched_sources.items():
            record_fetch(sid, n, registry, persist=False)
        save_sources(registry)

    print(f'Appended {len(accepted)} rows to story_updates.csv.')

    # Credit the stories, so a WebSearch-only story stops reporting itself stale.
    story_counts = {}
    for row in accepted:
        story_counts[row['story_id']] = story_counts.get(row['story_id'], 0) + 1
    for sid, n, total in bump_stories(story_counts):
        print(f'  {sid}: +{n} update(s), count now {total}, last_update_at today')


if __name__ == '__main__':
    main()
