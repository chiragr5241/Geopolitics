#!/usr/bin/env python3
"""
Agent review pass over the video beats link_youtube.py proposed.

WHY THIS EXISTS. `score_video` is a keyword scorer, and a keyword scorer cannot
tell a topic from a subject. "Police fight gangs, guns and corruption in
Ecuador's war on drugs" landed on the Ukraine corruption story on 2026-07-28:
one story keyword ("corruption") in the title (+3), a rarity bonus because only
6 of 2586 archived videos use the word (+2), and a core-topic channel (+1) —
exactly MIN_SCORE, with no country overlap and nothing else in common. Rare in
the archive is not the same as specific to the story, and no amount of further
rule-tightening fixes that class of error, because the judgement it needs is
"is this video ABOUT this story", which is a reading task.

So the scorer keeps its job — cheaply narrowing 2500+ videos to a handful of
candidates — and this script hands those candidates to the agent for the yes/no.
The scorer may be generous; this is the gate.

VERDICTS ARE REMEMBERED, in data/youtube_review.csv, keyed by (story_id, url).
That file is not a log — link_youtube.py reads it and will not re-propose a
video that was already rejected for that story. Without it, matching being
retroactive means every rejected video comes back on the very next run.

Usage (from project root):
    python3 scripts/review_youtube_links.py --select [N]   # candidates as JSON
    ... judge each ...
    cat verdicts.json | python3 scripts/review_youtube_links.py
    python3 scripts/review_youtube_links.py --status
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pull_youtube import load_videos                                    # noqa: E402
from add_story_update import STORY_UPDATE_COLUMNS                       # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST_JSON = os.path.join(ROOT, 'data', 'watchlist.json')
STORY_UPDATES_CSV = os.path.join(ROOT, 'data', 'story_updates.csv')
REVIEW_CSV = os.path.join(ROOT, 'data', 'youtube_review.csv')

REVIEW_COLUMNS = ['story_id', 'url', 'verdict', 'reason', 'headline', 'reviewed_at']

DEFAULT_BATCH = 25
DESC_CHARS = 700     # enough to judge aboutness, short enough to batch 25 of them


def load_reviews():
    """(story_id, url) -> review row."""
    if not os.path.exists(REVIEW_CSV):
        return {}
    with open(REVIEW_CSV, newline='', encoding='utf-8') as f:
        return {(r['story_id'], r['url']): r for r in csv.DictReader(f)}


def rejected_pairs():
    """The (story_id, url) pairs link_youtube.py must not propose again."""
    return {k for k, r in load_reviews().items() if r.get('verdict') == 'drop'}


def write_reviews(reviews):
    with open(REVIEW_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in reviews.values():
            w.writerow({k: r.get(k, '') for k in REVIEW_COLUMNS})


def load_updates():
    if not os.path.exists(STORY_UPDATES_CSV):
        return []
    with open(STORY_UPDATES_CSV, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def load_stories():
    if not os.path.exists(WATCHLIST_JSON):
        return {}
    with open(WATCHLIST_JSON, encoding='utf-8') as f:
        return {s['story_id']: s for s in json.load(f).get('stories', [])}


def pending(rows, reviews):
    """Video beats awaiting a verdict.

    A row carrying `cross_linked_from` is excluded: cross_link_updates.py placed
    it on this story only after its own review, so it has already been judged —
    against the right question, too ("does it ALSO belong here?").
    """
    return [r for r in rows
            if r.get('origin') == 'youtube'
            and not (r.get('cross_linked_from') or '').strip()
            and (r.get('story_id'), r.get('url')) not in reviews]


def select(n):
    rows = load_updates()
    reviews = load_reviews()
    stories = load_stories()
    videos = {v['url']: v for v in load_videos()}

    out = []
    for r in pending(rows, reviews)[:n]:
        story = stories.get(r.get('story_id'), {})
        seed = story.get('seed') or {}
        video = videos.get(r.get('url', '')) or {}
        # raw_title matters to the judgement: Step 3 may have rewritten the
        # title, and a rewrite is exactly where a subject can drift.
        out.append({
            'update_id': r.get('update_id', ''),
            'story_id': r.get('story_id', ''),
            'story_title': story.get('title', ''),
            'story_summary': seed.get('text', ''),
            'story_keywords': story.get('keywords', []),
            'story_countries': seed.get('countries', []),
            'video_title': video.get('title') or r.get('headline', ''),
            'video_raw_title': video.get('raw_title', ''),
            'channel': r.get('source_name', ''),
            'published_at': (video.get('published_at') or r.get('date', ''))[:10],
            'video_countries': video.get('countries', ''),
            'description': ' '.join((video.get('description') or
                                     r.get('summary') or '').split())[:DESC_CHARS],
            'url': r.get('url', ''),
        })
    print(json.dumps(out, ensure_ascii=False, indent=1))
    remaining = len(pending(rows, reviews)) - len(out)
    print(f'# {len(out)} candidate(s); {remaining} still unreviewed after this batch',
          file=sys.stderr)


def apply_verdicts():
    payload = sys.stdin.read().strip()
    if not payload:
        print('review_youtube_links: no input on stdin', file=sys.stderr)
        sys.exit(2)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        print(f'review_youtube_links: invalid JSON: {e}', file=sys.stderr)
        sys.exit(2)
    if isinstance(data, dict):
        data = [data]

    rows = load_updates()
    reviews = load_reviews()
    by_update = {r.get('update_id'): r for r in rows if r.get('origin') == 'youtube'}
    now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    drop_ids, kept, skipped = set(), 0, []
    for rec in data:
        uid = str(rec.get('update_id', '')).strip()
        verdict = str(rec.get('verdict', '')).strip().lower()
        row = by_update.get(uid)
        if not row:
            skipped.append(f'{uid or "(no update_id)"}: not a video beat')
            continue
        if verdict not in ('keep', 'drop'):
            skipped.append(f'{uid}: verdict must be keep or drop, got {verdict!r}')
            continue
        reviews[(row['story_id'], row['url'])] = {
            'story_id': row['story_id'],
            'url': row['url'],
            'verdict': verdict,
            'reason': ' '.join(str(rec.get('reason', '')).split())[:240],
            'headline': row.get('headline', ''),
            'reviewed_at': now_iso,
        }
        if verdict == 'drop':
            drop_ids.add(uid)
            print(f'  drop  {row["story_id"]}  {row["headline"][:60]}')
        else:
            kept += 1

    write_reviews(reviews)
    if drop_ids:
        keep_rows = [r for r in rows if r.get('update_id') not in drop_ids]
        with open(STORY_UPDATES_CSV, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=STORY_UPDATE_COLUMNS, quoting=csv.QUOTE_ALL)
            w.writeheader()
            for r in keep_rows:
                w.writerow({k: r.get(k, '') for k in STORY_UPDATE_COLUMNS})

    print(f'Reviewed {kept + len(drop_ids)}: {kept} kept, {len(drop_ids)} dropped.')
    for s in skipped:
        print(f'  skipped {s}', file=sys.stderr)
    if drop_ids:
        print('Next: python3 scripts/build_db.py')


def status():
    rows = load_updates()
    reviews = load_reviews()
    beats = [r for r in rows if r.get('origin') == 'youtube']
    drops = sum(1 for r in reviews.values() if r.get('verdict') == 'drop')
    print(f'Video beats on timelines: {len(beats)}')
    print(f'Reviewed:                 {len(reviews)}  ({drops} rejected, '
          f'{len(reviews) - drops} approved)')
    print(f'Awaiting review:          {len(pending(rows, reviews))}')


def main():
    if '--status' in sys.argv:
        status()
        return
    if '--select' in sys.argv:
        i = sys.argv.index('--select')
        n = int(sys.argv[i + 1]) if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit() \
            else DEFAULT_BATCH
        select(n)
        return
    apply_verdicts()


if __name__ == '__main__':
    main()
