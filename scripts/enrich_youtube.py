#!/usr/bin/env python3
"""
Tier 2 for the video archive: record the routine's read of what a video is
actually about, derived from its description.

Why this exists: a YouTube title is written to be clicked, not to be indexed.
"The REAL Reason This Country Is Collapsing" tells the matcher nothing, while
the description usually names the country, the event and the date. So the
routine reads the description and writes back a plain `title` (the raw one is
kept), a one-line `summary`, and the countries/keywords it actually concerns —
which is what link_youtube.py scores against.

Same two-tier contract as the tweet pipeline: pull_youtube.py always writes a
`base` row so ingestion can never stall, and this upgrades rows to `detailed`
in bounded batches.

Reads one JSON object, or an array, from stdin:
    {
      "video_id": "dQw4w9WgXcQ",           (required, must exist in the archive)
      "title": "…",                         (optional — a clearer title; the
                                             original is preserved in raw_title)
      "summary": "…",                       (required, <=400 chars, plain prose)
      "countries": "UA;RU",                 (optional, ';'-separated ISO-2)
      "keywords": "yermak;nabu;energoatom"  (optional, ';'-separated)
    }

Usage (from project root):
    python3 scripts/enrich_youtube.py --batch 12        # list base rows to do
    cat details.json | python3 scripts/enrich_youtube.py [--dry-run]
    python3 scripts/enrich_youtube.py --status
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pull_youtube import load_videos, save_videos  # noqa: E402

MAX_SUMMARY = 400


def select_batch(n):
    """The base rows most worth detailing: newest first, since a fresh video is
    the one a story is most likely to want next."""
    rows = [r for r in load_videos() if r.get('detail_status') != 'detailed']
    rows.sort(key=lambda r: r.get('published_at', ''), reverse=True)
    return rows[:n]


def status():
    rows = load_videos()
    detailed = sum(1 for r in rows if r.get('detail_status') == 'detailed')
    print(f'Video archive: {len(rows)} rows')
    print(f'  detailed: {detailed}')
    print(f'  base:     {len(rows) - detailed}')
    if rows:
        newest = max(r.get('published_at', '') for r in rows)
        print(f'  newest published: {newest}')


def apply(items, dry_run=False):
    rows = load_videos()
    by_id = {r['video_id']: r for r in rows}
    applied, missing = 0, []

    for item in items:
        vid = (item.get('video_id') or '').strip()
        row = by_id.get(vid)
        if not row:
            missing.append(vid)
            continue
        summary = ' '.join((item.get('summary') or '').split())[:MAX_SUMMARY]
        if not summary:
            missing.append(f'{vid} (no summary)')
            continue
        row['summary'] = summary
        new_title = ' '.join((item.get('title') or '').split())
        if new_title and new_title != row.get('title'):
            # Preserve what the video is actually called the first time we
            # rewrite it; a later re-detail must not overwrite that with our
            # own earlier rewrite.
            if not row.get('raw_title'):
                row['raw_title'] = row.get('title', '')
            row['title'] = new_title[:200]
        if item.get('countries'):
            row['countries'] = item['countries']
        if item.get('keywords'):
            row['keywords'] = item['keywords']
        row['detail_status'] = 'detailed'
        applied += 1

    print(f'Detailed {applied} video(s).')
    for m in missing:
        print(f'  SKIPPED: no such video_id in the archive: {m!r}')
    if dry_run:
        print('Dry run — nothing written.')
        return
    if applied:
        save_videos(rows)
        print('Wrote data/youtube_videos.csv.')


def main():
    dry_run = '--dry-run' in sys.argv

    if '--status' in sys.argv:
        status()
        return

    if '--batch' in sys.argv:
        i = sys.argv.index('--batch')
        n = int(sys.argv[i + 1]) if i + 1 < len(sys.argv) else 10
        batch = select_batch(n)
        print(json.dumps([{
            'video_id': r['video_id'],
            'channel': r['channel'],
            'title': r['title'],
            'published_at': r['published_at'],
            'url': r['url'],
            'description': r['description'],
        } for r in batch], indent=2))
        return

    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit('No input on stdin. Pipe a JSON object or array of objects.')
    payload = json.loads(raw)
    apply(payload if isinstance(payload, list) else [payload], dry_run=dry_run)


if __name__ == '__main__':
    main()
