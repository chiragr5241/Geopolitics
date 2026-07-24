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


def save_watchlist(doc):
    with open(WATCHLIST_JSON, 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write('\n')


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


def has_good_image(story):
    """True if this story already has a TRUSTWORTHY hero image.

    An explicit story.image always counts. Otherwise we consult the keyword
    matcher — but only trust the match when it is country-consistent: the matched
    image must be generic (no countries) OR share the story's PRIMARY (first)
    country. This rejects false positives where a broad keyword + a shared
    secondary country (e.g. "Taiwan Strait" hitting the US-gated Hormuz photo via
    a US tag) cross-assigns a wrong-country image, which is exactly what let the
    routine believe a story "had an image" when it had the wrong one.
    """
    if (story.get('image') or '').strip():
        return True
    url = match_image(story_match_text(story), story_countries(story))
    if not url:
        return False
    row = _row_for_url(url)
    row_cs = {c.strip().upper() for c in (row.get('countries') or '').split(';') if c.strip()}
    if not row_cs:
        return True   # generic image (munitions, oil, stadium) — always fine
    countries = (story.get('seed', {}) or {}).get('countries', []) or []
    primary = (countries[0].strip().upper() if countries else '')
    return primary in row_cs


def _row_for_url(url):
    for r in load_story_images():
        if (r.get('url') or '') == url:
            return r
    return {}


def missing_stories():
    doc = load_watchlist()
    return [s for s in doc.get('stories', [])
            if s.get('status') == 'active' and not has_good_image(s)]


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
    doc = load_watchlist()
    stories = doc.get('stories', [])
    miss = [s for s in stories if s.get('status') == 'active' and not has_good_image(s)]
    if not miss:
        print('All active stories already have a trustworthy image.')
        return
    intel = load_intel()
    story_urls = existing_urls()
    changed = 0
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
        # Set an EXPLICIT per-story image. The frontend prefers story.image over
        # keyword matching, so this reliably overrides any wrong keyword match
        # (a low-priority story_images row could never win against an earlier
        # false positive). Deterministic and correct-by-construction: the photo
        # comes from an article literally linked to this story.
        s['image'] = cands[0][2]
        changed += 1
        print(f'  + {sid}  ->  {cands[0][2][:70]}  ({cands[0][3]})')

    print(f'from-feed: {changed} story(ies) get their own linked native image, '
          f'{len(still)} still need an agent WebSearch')
    for sid in still:
        print(f'  still missing: {sid}')
    if dry_run:
        print('Dry run — nothing written.')
        return
    if changed:
        save_watchlist(doc)
        print(f'Wrote {changed} story.image value(s) to data/watchlist.json.')


def cmd_stdin():
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit('No input on stdin. Pipe a JSON object/array, or use --missing / --from-feed.')
    payload = json.loads(raw)
    items = payload if isinstance(payload, list) else [payload]

    # Two kinds of item, both accepted in one array:
    #  - {"story_id": "...", "url": "..."} → set that story's EXPLICIT story.image
    #    (highest priority; the reliable fix for a story with a wrong keyword
    #    match, since a low-priority story_images row can never override it).
    #  - {"keywords": "...", "url": "...", ...} → append a generic story_images row
    #    (the keyword table, shared by any story that matches those keywords).
    direct = [it for it in items if (it.get('story_id') or '').strip()]
    generic = [it for it in items if not (it.get('story_id') or '').strip()]

    if direct:
        doc = load_watchlist()
        by_id = {s.get('story_id'): s for s in doc.get('stories', [])}
        set_n = 0
        for it in direct:
            sid = it['story_id'].strip()
            url = (it.get('url') or '').strip()
            if sid not in by_id:
                print(f'  skipped (unknown story_id): {sid}')
                continue
            if not url.startswith(('http://', 'https://')):
                print(f'  skipped (bad url) for {sid}: {url[:60]}')
                continue
            by_id[sid]['image'] = url
            set_n += 1
            print(f'  set story.image [{sid}] -> {url[:70]}')
        if set_n:
            save_watchlist(doc)
            print(f'Wrote {set_n} story.image value(s) to data/watchlist.json.')

    if generic:
        n = append_rows(generic)
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
