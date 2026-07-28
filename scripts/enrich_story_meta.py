#!/usr/bin/env python3
"""
Fill in a tracked story's MATCHING METADATA — keywords, country codes, and an
AI-written description — so the rest of the pipeline can actually find news for it.

Why this exists
---------------
A story seeded from a feed item inherits keywords (from the tweet's
entities_locations / entities_orgs) and countries (from enrichment). A story the
user types into "Add your own" on the Tracker page does not: both fields are
optional there, so they are usually left empty. That is silently fatal, because
every deterministic matcher in the pipeline needs at least two keyword hits:

  * update_stories.py  (tracker Step 1) — sum() over an empty keyword list is 0,
    so no intel_feed row can EVER match; the story gets no timeline beats.
  * link_stories.py — same rule, so the story never appears in linked_story_ids,
    which means no story tag on feed cards and nothing in the merged timeline.

(link_youtube.py already works around this with a title-word fallback.) The NYC
Mayor Mamdani story was exactly this case: 0 keywords, 0 countries, and the only
beats it ever got came from the YouTube tracker.

The fix is the one already applied by hand to the China-Taiwan story: an agent
reads the story's title + seed text, writes an enhanced description prefixed
"AI suggestion:", and fills the keywords / country codes. This script is the
idempotent, machine-checked way to do that from the story-tracker routine.

Two modes
---------
  --missing        List active stories whose keywords OR countries are empty —
                   the ones the agent should enhance. One JSON object per line,
                   carrying everything needed to write the enhancement.

  (stdin, default) Apply agent-written enhancements. Reads a JSON object or an
                   array of:
                     {"story_id":   "st-...",              (required)
                      "description": "Track ... ",          (the AI suggestion)
                      "keywords":   ["taiwan", "pla", ...],
                      "countries":  ["CN", "TW"],
                      "query_hints":["...", "..."],         (optional)
                      "category":   "political"}            (optional)

FILL-ONLY, never overwrite. A field the user already set is left exactly as it
is; the description is appended to seed.text under an "AI suggestion:" heading
and is skipped entirely if one is already there. Re-running is therefore a no-op,
and a user editing keywords later always wins.

--merge-keywords is the one escape hatch, and it still only ADDS: it unions the
supplied keywords onto the story's existing list instead of skipping them. Use it
for a story whose keywords are SET but unmatchable — `--missing` only reports an
EMPTY list, so "5 keywords that never appear in a wire headline" is invisible to
this script and silently behaves exactly like having none.

Usage (from repo root):
    python3 scripts/enrich_story_meta.py --missing
    cat /tmp/story_meta.json | python3 scripts/enrich_story_meta.py
    cat /tmp/story_meta.json | python3 scripts/enrich_story_meta.py --dry-run
    cat /tmp/story_meta.json | python3 scripts/enrich_story_meta.py --merge-keywords
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST_JSON = os.path.join(ROOT, 'data', 'watchlist.json')

AI_PREFIX = 'AI suggestion:'
MAX_KEYWORDS = 12
MAX_HINTS = 4
COUNTRY_RE = re.compile(r'^[A-Z]{2}$')


def load_watchlist():
    with open(WATCHLIST_JSON, encoding='utf-8') as f:
        return json.load(f)


def save_watchlist(doc):
    with open(WATCHLIST_JSON, 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write('\n')


def seed_of(story):
    return story.get('seed') or {}


def story_keywords(story):
    return [k.strip().lower() for k in (story.get('keywords') or []) if str(k).strip()]


def story_countries(story):
    return [c.strip().upper() for c in (seed_of(story).get('countries') or []) if str(c).strip()]


def has_ai_description(story):
    return AI_PREFIX.lower() in (seed_of(story).get('text') or '').lower()


def needs_enrichment(story):
    """The gate: a story the matchers cannot work with.

    Empty keywords or empty countries is what actually breaks matching, so that
    is the trigger — exactly as asked. The AI description is written at the same
    time because it is what the agent derives the keywords from."""
    missing = []
    if not story_keywords(story):
        missing.append('keywords')
    if not story_countries(story):
        missing.append('countries')
    return missing


def missing_stories(doc):
    return [s for s in doc.get('stories', [])
            if s.get('status') == 'active' and needs_enrichment(s)]


def cmd_missing(as_json_only=False):
    doc = load_watchlist()
    miss = missing_stories(doc)
    if not miss:
        if not as_json_only:
            print('All active stories already have keywords and country codes.')
        return
    if not as_json_only:
        print(f'{len(miss)} active story(ies) need metadata enhancement:')
    for s in miss:
        print(json.dumps({
            'story_id': s['story_id'],
            'title': s.get('title', ''),
            'missing': needs_enrichment(s),
            'has_ai_description': has_ai_description(s),
            'seed_text': (seed_of(s).get('text') or ''),
            'category': (seed_of(s).get('category') or ''),
            'keywords': story_keywords(s),
            'countries': story_countries(s),
            'query_hints': s.get('query_hints') or [],
        }, ensure_ascii=False))


def clean_keywords(raw):
    if isinstance(raw, str):
        raw = re.split(r'[,;]', raw)
    out = []
    for k in (raw or []):
        k = ' '.join(str(k).split()).lower()
        if k and k not in out:
            out.append(k)
    return out[:MAX_KEYWORDS]


def clean_countries(raw):
    """ISO-3166 alpha-2 only. Anything else is dropped and reported — a bad code
    would silently exclude every feed row (the country gate is an intersection)."""
    if isinstance(raw, str):
        raw = re.split(r'[,;]', raw)
    out, bad = [], []
    for c in (raw or []):
        c = str(c).strip().upper()
        if not c:
            continue
        if COUNTRY_RE.match(c):
            if c not in out:
                out.append(c)
        else:
            bad.append(c)
    return out, bad


def clean_hints(raw, title):
    if isinstance(raw, str):
        raw = [raw]
    out = []
    for h in (raw or []):
        h = ' '.join(str(h).split())
        if h and h not in out:
            out.append(h)
    # The title is always a usable hint; keep it first if the agent didn't send it.
    if title and title not in out:
        out.insert(0, title)
    return out[:MAX_HINTS]


def apply_item(story, item, merge_keywords=False):
    """Fill-only. Returns a list of human-readable changes (empty = no-op)."""
    changes = []
    seed = story.setdefault('seed', {})

    # 1. Description — appended under an "AI suggestion:" heading, preserving
    #    whatever the user originally typed. Never written twice.
    desc = ' '.join(str(item.get('description') or '').split())
    if desc:
        if has_ai_description(story):
            changes.append('description: already has an AI suggestion, kept')
        else:
            existing = (seed.get('text') or '').rstrip()
            seed['text'] = (existing + '\n\n' + AI_PREFIX + ' ' + desc) if existing \
                else (AI_PREFIX + ' ' + desc)
            changes.append(f'description: +{len(desc)} chars')

    # 2. Keywords — only when empty; a user's own list is never touched.
    #    --merge-keywords instead UNIONS the new terms onto the existing list.
    #    That covers the case fill-only cannot: a story whose keywords are set
    #    but unmatchable, so `--missing` never lists it and nothing ever gets
    #    fixed. The Space Companies story was seeded with stock TICKERS
    #    ("rklb", "spcx") — wires write "Rocket Lab", never "RKLB", so the >=2-hit
    #    rule could never clear and the story matched zero feed rows for a week.
    #    A union only ever ADDS, so the user's own terms still stand.
    kws = clean_keywords(item.get('keywords'))
    if kws:
        existing = story_keywords(story)
        if not existing:
            story['keywords'] = kws
            changes.append('keywords: ' + ', '.join(kws))
        elif merge_keywords:
            added = [k for k in kws if k not in existing]
            if added:
                story['keywords'] = (existing + added)[:MAX_KEYWORDS]
                changes.append('keywords +' + ', '.join(added) +
                               f'  (now {len(story["keywords"])})')
            else:
                changes.append('keywords: nothing new to add, kept')
        else:
            changes.append('keywords: already set, kept')

    # 3. Country codes — only when empty.
    ctry, bad = clean_countries(item.get('countries'))
    for b in bad:
        changes.append(f'countries: dropped invalid code {b!r} (need ISO alpha-2)')
    if ctry:
        if story_countries(story):
            changes.append('countries: already set, kept')
        else:
            seed['countries'] = ctry
            changes.append('countries: ' + ', '.join(ctry))

    # 4. Query hints — the Step 2 WebSearch runs off these. A custom story starts
    #    with just its title; better hints mean better searches.
    hints = clean_hints(item.get('query_hints'), story.get('title', ''))
    current = story.get('query_hints') or []
    if hints and len(hints) > len(current):
        story['query_hints'] = hints
        changes.append('query_hints: ' + ' | '.join(hints))

    # 5. Category — only when empty.
    cat = ' '.join(str(item.get('category') or '').split()).lower()
    if cat and not (seed.get('category') or '').strip():
        seed['category'] = cat
        changes.append('category: ' + cat)

    if any(not c.endswith(', kept') for c in changes):
        story['meta_enriched_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return changes


def cmd_stdin(dry_run, merge_keywords=False):
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit('No input on stdin. Pipe a JSON object/array, or use --missing.')
    payload = json.loads(raw)
    items = payload if isinstance(payload, list) else [payload]

    doc = load_watchlist()
    by_id = {s.get('story_id'): s for s in doc.get('stories', [])}
    touched = 0
    for it in items:
        sid = (it.get('story_id') or '').strip()
        if sid not in by_id:
            print(f'  skipped (unknown story_id): {sid or "<empty>"}')
            continue
        changes = apply_item(by_id[sid], it, merge_keywords=merge_keywords)
        real = [c for c in changes if not c.endswith(', kept')]
        if real:
            touched += 1
            print(f'  ~ {sid}')
            for c in changes:
                print(f'      {c}')
        else:
            print(f'  = {sid} (nothing to fill — already complete)')

    still = [s['story_id'] for s in missing_stories(doc)]
    if dry_run:
        print(f'Dry run — {touched} story(ies) would change, nothing written.')
        return
    if touched:
        save_watchlist(doc)
        print(f'Wrote metadata for {touched} story(ies) to data/watchlist.json.')
    else:
        print('No changes — data/watchlist.json untouched.')
    if still:
        print('Still missing keywords/countries: ' + ', '.join(still))


def main():
    args = sys.argv[1:]
    if '--missing' in args:
        cmd_missing('--json' in args)
    else:
        cmd_stdin('--dry-run' in args, merge_keywords='--merge-keywords' in args)


if __name__ == '__main__':
    main()
