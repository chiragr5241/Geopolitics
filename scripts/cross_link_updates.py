#!/usr/bin/env python3
"""
Assign an already-recorded beat to the OTHER stories it also belongs to.

Every writer in this pipeline places a beat on exactly ONE story: update_stories.py
matches an intel row to the first story it clears, add_story_update.py takes the
`story_id` the researcher typed, link_youtube.py appends one row per (story,
video) pair it scores. Nothing ever asks the second question — *which other
tracked story is this also about?* — so a piece of news that sits across two
files silently reaches only one timeline.

The case that named this step:

    "Ukraine's Strike on an Iranian Cargo Ship and the Moscow-Tehran Weapons
     Pipeline" — the weapons pipeline linking Moscow and Tehran, and the risk of
     the Ukraine and Iran wars colliding.

It landed on the US-Iran story alone. It is just as much a Russia-Ukraine beat,
and the Russia-Ukraine timeline never saw it.

Why the existing matchers miss these. link_youtube.py and link_stories.py both
demand text evidence that the item is about the story, and deliberately refuse
to let a shared country be the second signal (a US-tagged video is not about the
US midterms because "midterm" appears once). That bar is right for pulling an
unknown item out of a 2500-video archive. It is too strict here: this beat is
ALREADY established news on a story, and the only open question is whether it
also belongs to another — so one keyword in its headline plus a genuine country
overlap is admissible evidence, where in a cold archive it would not be.

Scoring is a filter, not the verdict — same division of labour as
review_youtube_links.py. It narrows the pairs to a handful of candidates; the
agent then reads each one and decides whether the beat is really about the other
story too. Every verdict, keep or drop, is remembered in data/crosslink_review.csv
so a pair is never proposed twice.

A kept pair is written as a NEW story_updates row on the target story — same
date, headline, summary, url, image and source, its own update_id, and
`cross_linked_from` naming the beat it was copied from. That column is also what
protects it: link_youtube.py's `--prune` re-scores video beats against the rules
that placed them, and would drop these on the next run, because the whole point
is that they did NOT clear that bar. A cross-link was placed by judgement, so
the score-based passes leave it alone.

Usage (from project root):
    python3 scripts/cross_link_updates.py --propose [N] [--verbose] [--all-origins]
    cat /tmp/crosslinks.json | python3 scripts/cross_link_updates.py
    python3 scripts/cross_link_updates.py --status
    python3 scripts/cross_link_updates.py --prune-orphans [--dry-run]
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from enrich_lib import extract_countries                                  # noqa: E402
from source_registry import load_sources, story_sources                   # noqa: E402
from story_dedup import build_index, is_fuzzy_dup, note_accepted          # noqa: E402
from add_story_update import (STORY_UPDATE_COLUMNS, bump_stories,         # noqa: E402
                              header_matches, backfill_sources, next_update_id)
from link_youtube import kw_in, story_keywords, strip_promo               # noqa: E402
from review_youtube_links import rejected_pairs                           # noqa: E402
from pull_youtube import load_videos                                      # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST_JSON = os.path.join(ROOT, 'data', 'watchlist.json')
STORY_UPDATES_CSV = os.path.join(ROOT, 'data', 'story_updates.csv')
REVIEW_CSV = os.path.join(ROOT, 'data', 'crosslink_review.csv')

REVIEW_COLUMNS = ['story_id', 'update_id', 'url', 'verdict', 'reason',
                  'headline', 'reviewed_at']

MIN_SCORE = 5              # one headline keyword + a country overlap, at least
MAX_NEW_PER_STORY = 4      # cross-links a story may gain in one run
MAX_PER_STORY = 15         # cross-linked beats a story may hold in total
DEFAULT_BATCH = 20
SUMMARY_CHARS = 700

# The origins this step is for: what the two routines themselves produced this
# run. `intel_feed` beats are excluded by default because tweets already reach
# every story they match through `linked_story_ids` (link_stories.py), which the
# tracker page merges into each timeline — cross-linking them would duplicate a
# mechanism that already exists. `--all-origins` includes them anyway.
DEFAULT_ORIGINS = ('websearch', 'youtube')


def load_updates():
    if not os.path.exists(STORY_UPDATES_CSV):
        return []
    with open(STORY_UPDATES_CSV, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def load_stories():
    if not os.path.exists(WATCHLIST_JSON):
        return []
    with open(WATCHLIST_JSON, encoding='utf-8') as f:
        return json.load(f).get('stories', [])


def load_reviews():
    """(story_id, update_id) -> review row."""
    if not os.path.exists(REVIEW_CSV):
        return {}
    with open(REVIEW_CSV, newline='', encoding='utf-8') as f:
        return {(r['story_id'], r['update_id']): r for r in csv.DictReader(f)}


def write_reviews(reviews):
    with open(REVIEW_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in reviews.values():
            w.writerow({k: r.get(k, '') for k in REVIEW_COLUMNS})


def beat_countries(row, videos):
    """The countries a beat is about.

    A video carries its own curated `countries` (written by the base pass, or by
    the routine when it rewrote the title), so prefer that. Everything else has
    only its text, which the same deterministic classifier the rest of the
    pipeline uses can read.
    """
    video = videos.get(row.get('url') or '')
    if video and (video.get('countries') or '').strip():
        return {c.strip().upper()
                for c in video['countries'].split(';') if c.strip()}
    text = (row.get('headline') or '') + ' ' + (row.get('summary') or '')
    return {c for c in extract_countries(text).split(';') if c}


def beat_body(row, videos):
    """The text below the headline: the video's description when there is one
    (richer than the 400-char summary the row kept), else the summary.

    Sponsor blocks and link dumps are stripped for the same reason
    link_youtube.py strips them — half a typical description is a discount code
    and says nothing about the subject."""
    video = videos.get(row.get('url') or '')
    if video and (video.get('description') or '').strip():
        return strip_promo(video['description'])
    return row.get('summary') or ''


def score_pair(row, story, countries, videos):
    """How strongly an existing beat belongs to another story as well.

        +3  per story keyword in the beat's HEADLINE — it states the subject
        +2  per story keyword in the body
        +2  the beat and the story share a country

    Gate: a country overlap (when both sides declare countries), AND either one
    headline keyword or two different body keywords. When the beat's countries
    can't be read at all, the text has to carry it alone — two different
    keywords, at least one in the headline.
    """
    keywords = story_keywords(story)
    story_countries = {c.upper()
                       for c in ((story.get('seed') or {}).get('countries') or [])}
    if not keywords:
        return 0, []

    headline = (row.get('headline') or '').lower()
    body = beat_body(row, videos).lower()

    score, why = 0, []
    strong = weak = 0
    for kw in keywords:
        if kw_in(kw, headline):
            score += 3
            strong += 1
            why.append(f'headline:{kw}')
        elif kw_in(kw, body):
            score += 2
            weak += 1
            why.append(f'body:{kw}')

    shared = story_countries & countries
    if story_countries and countries and not shared:
        return 0, []
    if shared:
        score += 2
        why.append('country:' + ','.join(sorted(shared)))

    if not countries or not story_countries:
        # No country signal to lean on — demand the text say it twice.
        if strong < 1 or strong + weak < 2:
            return 0, []
    elif strong < 1 and weak < 2:
        return 0, []

    return score, why


def propose(batch, origins, verbose=False, only_story=None):
    rows = load_updates()
    stories = [s for s in load_stories() if s.get('status') in ('active', 'resolved')]
    if only_story:
        stories = [s for s in stories if s.get('story_id') == only_story]
    if not rows or not stories:
        print('[]')
        print('# nothing to cross-link', file=sys.stderr)
        return

    reviews = load_reviews()
    yt_rejected = rejected_pairs()
    videos = {v['url']: v for v in load_videos()}
    registry = {r['source_id']: r for r in load_sources()}
    fuzzy_index = build_index(rows)

    # What each story already holds, so a cross-link never repeats a beat it has.
    have_url = {(r['story_id'], r.get('url') or '') for r in rows if r.get('url')}
    crosslinks_held = {}
    for r in rows:
        if (r.get('cross_linked_from') or '').strip():
            crosslinks_held[r['story_id']] = crosslinks_held.get(r['story_id'], 0) + 1

    excluded_by_story = {s['story_id']: set(story_sources(s)['excluded']) for s in stories}
    countries_by_row = {}

    candidates = []
    skipped = {'reviewed': 0, 'rejected': 0, 'deselected': 0, 'duplicate': 0}
    for row in rows:
        if row.get('origin') not in origins:
            continue
        if (row.get('cross_linked_from') or '').strip():
            # Only ever cross-link from the original beat. A copy of a copy
            # would chain its provenance through a row that --prune-orphans can
            # remove, and the original is proposed for that third story anyway.
            continue
        uid = row.get('update_id') or ''
        if uid not in countries_by_row:
            countries_by_row[uid] = beat_countries(row, videos)
        for story in stories:
            sid = story['story_id']
            if sid == row.get('story_id'):
                continue
            if (sid, uid) in reviews:
                skipped['reviewed'] += 1
                continue
            if row.get('url') and (sid, row['url']) in yt_rejected:
                skipped['rejected'] += 1
                continue
            if row.get('url') and (sid, row['url']) in have_url:
                skipped['duplicate'] += 1
                continue
            src = row.get('source_id') or ''
            if src and src in excluded_by_story.get(sid, ()):
                skipped['deselected'] += 1
                continue
            if crosslinks_held.get(sid, 0) >= MAX_PER_STORY:
                continue
            if is_fuzzy_dup(sid, row.get('date') or '', row.get('headline') or '',
                            fuzzy_index):
                skipped['duplicate'] += 1
                continue
            score, why = score_pair(row, story, countries_by_row[uid], videos)
            if score >= MIN_SCORE:
                candidates.append((score, row.get('date') or '', row, story, why))

    # Best evidence first; among equals, the most recent beat.
    candidates.sort(key=lambda t: (t[0], t[1]), reverse=True)

    out, per_story = [], {}
    for score, _date, row, story, why in candidates:
        sid = story['story_id']
        if per_story.get(sid, 0) >= MAX_NEW_PER_STORY:
            continue
        if len(out) >= batch:
            break
        per_story[sid] = per_story.get(sid, 0) + 1
        seed = story.get('seed') or {}
        src_story = row.get('story_id')
        out.append({
            'update_id': row.get('update_id', ''),
            'story_id': sid,                       # the story being PROPOSED
            'story_title': story.get('title', ''),
            'story_summary': ' '.join((seed.get('text') or '').split())[:600],
            'story_keywords': story.get('keywords', []),
            'story_countries': seed.get('countries', []),
            'already_on': src_story,
            'headline': row.get('headline', ''),
            'summary': ' '.join(beat_body(row, videos).split())[:SUMMARY_CHARS],
            'source_name': row.get('source_name', ''),
            'origin': row.get('origin', ''),
            'date': row.get('date', ''),
            'url': row.get('url', ''),
            'beat_countries': ';'.join(sorted(countries_by_row[row.get('update_id', '')])),
            'score': score,
            'why': why if verbose else why[:4],
        })

    print(json.dumps(out, ensure_ascii=False, indent=1))
    print(f'# {len(out)} candidate pair(s) of {len(candidates)} scored; '
          f'{len(registry)} sources', file=sys.stderr)
    for key, n in skipped.items():
        if n:
            print(f'#   {n} pair(s) skipped — {key}', file=sys.stderr)


def apply_verdicts(dry_run=False):
    payload = sys.stdin.read().strip()
    if not payload:
        print('cross_link_updates: no input on stdin', file=sys.stderr)
        sys.exit(2)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        print(f'cross_link_updates: invalid JSON: {e}', file=sys.stderr)
        sys.exit(2)
    if isinstance(data, dict):
        data = [data]

    rows = load_updates()
    by_update = {r.get('update_id'): r for r in rows}
    story_ids = {s['story_id'] for s in load_stories()}
    reviews = load_reviews()
    fuzzy_index = build_index(rows)
    have_url = {(r['story_id'], r.get('url') or '') for r in rows if r.get('url')}
    now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    new_rows, skipped, dropped, counts = [], [], 0, {}
    for rec in data:
        uid = str(rec.get('update_id', '')).strip()
        sid = str(rec.get('story_id', '')).strip()
        verdict = str(rec.get('verdict', '')).strip().lower()
        source = by_update.get(uid)
        if not source:
            skipped.append(f'{uid or "(no update_id)"}: no such beat')
            continue
        if sid not in story_ids:
            skipped.append(f'{uid}: unknown target story {sid!r}')
            continue
        if sid == source.get('story_id'):
            skipped.append(f'{uid}: already on {sid}')
            continue
        if verdict not in ('keep', 'drop'):
            skipped.append(f'{uid}: verdict must be keep or drop, got {verdict!r}')
            continue

        reviews[(sid, uid)] = {
            'story_id': sid,
            'update_id': uid,
            'url': source.get('url', ''),
            'verdict': verdict,
            'reason': ' '.join(str(rec.get('reason', '')).split())[:240],
            'headline': source.get('headline', ''),
            'reviewed_at': now_iso,
        }
        if verdict == 'drop':
            dropped += 1
            print(f'  drop  {sid}  {source.get("headline", "")[:60]}')
            continue

        if source.get('url') and (sid, source['url']) in have_url:
            skipped.append(f'{uid}: {sid} already carries this url')
            continue
        date_str = source.get('date') or ''
        headline = source.get('headline') or ''
        if is_fuzzy_dup(sid, date_str, headline, fuzzy_index):
            skipped.append(f'{uid}: {sid} already has this beat (fuzzy match)')
            continue
        note_accepted(sid, date_str, headline, fuzzy_index)
        if source.get('url'):
            have_url.add((sid, source['url']))

        n = next_update_id(rows + new_rows, sid)
        new_rows.append({
            'story_id': sid,
            'update_id': f'{sid}-u{n:03d}',
            'date': date_str,
            'headline': headline,
            'summary': source.get('summary', ''),
            'source_name': source.get('source_name', ''),
            'url': source.get('url', ''),
            'status': source.get('status', 'developing'),
            'severity': source.get('severity', ''),
            'origin': source.get('origin', ''),
            'found_at': now_iso,
            'image': source.get('image', ''),
            'source_id': source.get('source_id', ''),
            'cross_linked_from': uid,
        })
        counts[sid] = counts.get(sid, 0) + 1
        print(f'  + {sid}  {headline[:60]}   (from {source.get("story_id")})')

    print(f'Reviewed {len(new_rows) + dropped}: {len(new_rows)} cross-linked, '
          f'{dropped} dropped.')
    for s in skipped:
        print(f'  skipped {s}', file=sys.stderr)

    if dry_run:
        print('Dry run — no changes written.')
        return

    write_reviews(reviews)
    if not new_rows:
        return

    if not header_matches():
        print('story_updates.csv predates the cross_linked_from column — migrating first.')
        backfill_sources()

    with open(STORY_UPDATES_CSV, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=STORY_UPDATE_COLUMNS, quoting=csv.QUOTE_ALL)
        w.writerows(new_rows)
    for sid, n, total in bump_stories(counts):
        print(f'  {sid}: +{n} -> {total} update(s)')
    print(f'Appended {len(new_rows)} cross-linked row(s) to story_updates.csv.')
    print('Next: python3 scripts/build_db.py')


def prune_orphans(dry_run=False):
    """Drop cross-links whose original beat is gone.

    A cross-link is a copy, so it outlives its source: review_youtube_links.py
    deletes a rejected video beat, and `link_youtube.py --prune` drops one that
    no longer scores — neither knows about the copies. This removes the copies
    the same way, and only ever touches rows that carry `cross_linked_from`.
    """
    rows = load_updates()
    ids = {r.get('update_id') for r in rows}
    keep, orphans = [], []
    for r in rows:
        src = (r.get('cross_linked_from') or '').strip()
        if src and src not in ids:
            orphans.append(r)
        else:
            keep.append(r)

    print(f'Cross-linked rows: {sum(1 for r in rows if (r.get("cross_linked_from") or "").strip())}')
    print(f'Orphaned (source beat deleted): {len(orphans)}')
    for r in orphans:
        print(f'  - {r["story_id"]}  {r["headline"][:60]}  (was {r["cross_linked_from"]})')
    if not orphans or dry_run:
        if dry_run and orphans:
            print('Dry run — no changes written.')
        return
    with open(STORY_UPDATES_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=STORY_UPDATE_COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in keep:
            w.writerow({k: r.get(k, '') for k in STORY_UPDATE_COLUMNS})
    print(f'Rewrote story_updates.csv without {len(orphans)} orphan(s).')
    print('Next: python3 scripts/add_story_update.py --recount && python3 scripts/build_db.py')


def status():
    rows = load_updates()
    reviews = load_reviews()
    linked = [r for r in rows if (r.get('cross_linked_from') or '').strip()]
    drops = sum(1 for r in reviews.values() if r.get('verdict') == 'drop')
    per_story = {}
    for r in linked:
        per_story[r['story_id']] = per_story.get(r['story_id'], 0) + 1
    print(f'Beats on timelines:      {len(rows)}')
    print(f'Cross-linked beats:      {len(linked)}')
    for sid in sorted(per_story):
        print(f'    {sid}: {per_story[sid]}')
    print(f'Pairs reviewed:          {len(reviews)}  ({drops} rejected, '
          f'{len(reviews) - drops} accepted)')


def _int_after(flag, default):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            return int(sys.argv[i + 1])
    return default


def _str_after(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith('--'):
            return sys.argv[i + 1]
    return default


def main():
    dry_run = '--dry-run' in sys.argv

    if '--status' in sys.argv:
        status()
        return
    if '--prune-orphans' in sys.argv:
        prune_orphans(dry_run=dry_run)
        return
    if '--propose' in sys.argv:
        origins = None if '--all-origins' in sys.argv else DEFAULT_ORIGINS
        rows_origins = origins or {r.get('origin') for r in load_updates()}
        propose(_int_after('--propose', DEFAULT_BATCH), rows_origins,
                verbose='--verbose' in sys.argv, only_story=_str_after('--story'))
        return
    apply_verdicts(dry_run=dry_run)


if __name__ == '__main__':
    main()
