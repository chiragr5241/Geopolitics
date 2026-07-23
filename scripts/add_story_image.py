#!/usr/bin/env python3
"""
Give tracked stories a hero image — routine-only, via data/story_images.csv.

The Tracker / main page render a story's hero image by keyword-matching the
story against data/story_images.csv (js/home.js + js/tracker.js `findImage`,
mirrored by match_image() in enrich_lib.py). A story added "by description"
(a custom story, or one whose subject no story_images row covers) therefore
renders with no image. This tool fixes that WITHOUT any frontend change: it
appends a row to story_images.csv so the existing matcher picks it up.

Two modes:

  --missing        List active stories with NO current image match (the ones the
                   story-tracker agent should WebSearch an image for). Prints a
                   JSON-ish line per story with its keywords + countries.

  --from-feed      Deterministic backfill: for each missing story that has linked
                   feed coverage carrying a NATIVE article image (a wire item's
                   own photo), append a story_images row using that image. No
                   network. Covers most stories immediately.

  (stdin, default) Append agent-supplied rows. Reads a JSON object or array of
                   {keywords, countries, label, url, caption, credit}. Use this
                   for the stories --missing still reports after --from-feed
                   (the agent WebSearches a representative, license-safe image —
                   prefer Wikimedia Commons — and pipes it in).

All writes DEDUP on url (idempotent) and skip a story that already matches, so
re-running never adds a duplicate row. Rows are appended at the END, i.e. lowest
match priority, so they never override a more-specific existing image.

Usage (from repo root):
    python3 scripts/add_story_image.py --missing
    python3 scripts/add_story_image.py --from-feed
    echo '[{"keywords":"india;modi;bjp","countries":"IN","label":"India Gate",
           "url":"https://upload.wikimedia.org/...","caption":"...","credit":"..."}]' \
        | python3 scripts/add_story_image.py
"""

import csv
import json
import os
import sys

from enrich_lib import match_image, load_story_images

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORY_IMAGES_CSV = os.path.join(ROOT, 'data', 'story_images.csv')
INTEL_CSV = os.path.join(ROOT, 'data', 'intel_feed.csv')
WATCHLIST_JSON = os.path.join(ROOT, 'data', 'watchlist.json')
COLUMNS = ['keywords', 'countries', 'label', 'url', 'caption', 'credit']


def load_watchlist():
    if not os.path.exists(WATCHLIST_JSON):
        return {'stories': []}
    with open(WATCHLIST_JSON, encoding='utf-8') as f:
        return json.load(f)


def load_intel():
    if not os.path.exists(INTEL_CSV):
        return []
    with open(INTEL_CSV, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def story_match_text(story):
    seed = story.get('seed', {}) or {}
    return ' '.join([
        story.get('title', ''), seed.get('text', ''),
        ' '.join(story.get('keywords', []) or []),
    ])


def story_countries(story):
    return ';'.join((story.get('seed', {}) or {}).get('countries', []) or [])


def has_image(story):
    """True if the frontend keyword matcher already gives this story an image."""
    return bool(match_image(story_match_text(story), story_countries(story)))


def missing_stories():
    doc = load_watchlist()
    return [s for s in doc.get('stories', [])
            if s.get('status') == 'active' and not has_image(s)]


def existing_urls():
    return {(r.get('url') or '').strip() for r in load_story_images() if r.get('url')}


def append_rows(rows):
    """Append validated, deduped rows to story_images.csv. Returns count added."""
    have = existing_urls()
    added = 0
    write_header = not os.path.exists(STORY_IMAGES_CSV)
    with open(STORY_IMAGES_CSV, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL, extrasaction='ignore')
        if write_header:
            w.writeheader()
        for r in rows:
            url = (r.get('url') or '').strip()
            kw = (r.get('keywords') or '').strip()
            if not url or not kw:
                print(f'  skipped (missing url/keywords): {r}')
                continue
            if url in have:
                print(f'  skipped (url already present): {url[:60]}')
                continue
            have.add(url)
            w.writerow({
                'keywords': kw,
                'countries': (r.get('countries') or '').strip(),
                'label': (r.get('label') or '').strip(),
                'url': url,
                'caption': (r.get('caption') or '').strip(),
                'credit': (r.get('credit') or '').strip(),
            })
            added += 1
            print(f'  + {kw[:40]}  ->  {url[:60]}')
    return added


def story_keywords_field(story):
    """A story_images `keywords` value for this story: its keywords, or failing
    that its title words. Semicolon-separated to match the table's format."""
    kws = [k.strip().lower() for k in (story.get('keywords') or []) if k.strip()]
    if not kws:
        kws = [w.lower() for w in story.get('title', '').split() if len(w) > 3][:5]
    return ';'.join(dict.fromkeys(kws))   # dedup, preserve order


def cmd_missing():
    miss = missing_stories()
    if not miss:
        print('All active stories already have an image.')
        return
    print(f'{len(miss)} active story(ies) with no image — WebSearch one each:')
    for s in miss:
        print(json.dumps({
            'story_id': s['story_id'],
            'title': s.get('title', ''),
            'suggested_keywords': story_keywords_field(s),
            'countries': story_countries(s),
        }, ensure_ascii=False))


def cmd_from_feed(dry_run):
    miss = missing_stories()
    if not miss:
        print('All active stories already have an image.')
        return
    intel = load_intel()
    story_urls = existing_urls()
    rows = []
    still = []
    for s in miss:
        sid = s['story_id']
        cands = []
        for r in intel:
            if sid not in (r.get('linked_story_ids') or '').split(';'):
                continue
            img = (r.get('images') or '').split(';')[0].strip()
            if not img or img in story_urls:        # empty or a generic story image
                continue
            try:
                sev = int(r.get('severity') or 0)
            except ValueError:
                sev = 0
            cands.append((sev, r.get('created_at') or '', img, r.get('source') or ''))
        if not cands:
            still.append(sid)
            continue
        cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
        best = cands[0]
        rows.append({
            'keywords': story_keywords_field(s),
            'countries': story_countries(s),
            'label': s.get('title', '')[:80],
            'url': best[2],
            'caption': s.get('title', ''),
            'credit': best[3],
        })

    print(f'from-feed: {len(rows)} story(ies) get a linked native image, '
          f'{len(still)} still need an agent WebSearch')
    for sid in still:
        print(f'  still missing: {sid}')
    if dry_run:
        print('Dry run — nothing written.')
        return
    if rows:
        n = append_rows(rows)
        print(f'Appended {n} row(s) to data/story_images.csv.')


def cmd_stdin():
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit('No input on stdin. Pipe a JSON object/array, or use --missing / --from-feed.')
    payload = json.loads(raw)
    rows = payload if isinstance(payload, list) else [payload]
    n = append_rows(rows)
    print(f'Appended {n} row(s) to data/story_images.csv.')


def main():
    args = sys.argv[1:]
    if '--missing' in args:
        cmd_missing()
    elif '--from-feed' in args:
        cmd_from_feed('--dry-run' in args)
    else:
        cmd_stdin()


if __name__ == '__main__':
    main()
