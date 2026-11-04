#!/usr/bin/env python3
"""
Route the daily UN archive onto the United Nations story and its branches.

data/un_daily/reports.csv (written by pull_un_daily.py) holds every UN report
ever seen. This turns each one into a timeline beat on the right story, using
the tracker's existing branching (a child story's `parent_id`):

  st-20261103-united-nations            the UN story — the umbrella: EVERY report
  │                                     (Security Council, Secretary-General,
  │                                     human rights, agencies & field, and the
  │                                     General Assembly too)
  └─ st-20260922-unga81-general-debate  UNGA 81 branch (parent_id → UN story):
                                        General Assembly plenary + the six Main
                                        Committees, from the session's opening on

A branch report is written to BOTH stories, so the parent stays the complete
daily record (matching its feed link, which is every UN News row — see
`link_sources` in link_stories.py) and the branch is the focused view. A General
Assembly report from before UNGA 81 opened (the 80th session's close) goes to
the parent only. The UN body that produced the report becomes the
beat's `origin` tag ("Security Council", "Sixth Committee", "Noon briefing"…),
so the timeline shows which part of the UN each beat came from.

Writes through scripts/add_story_update.py (the validated writer) with
--no-fetch: press.un.org refuses automated page fetches, and the RSS already
gave us the image when there is one. Deduplicated on (story_id, url) there, so
re-runs only add what is new.

Usage (from repo root):
    python3 scripts/un_story_updates.py [--dry-run]
"""

import csv
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_CSV = os.path.join(ROOT, 'data', 'un_daily', 'reports.csv')
WRITER = os.path.join(ROOT, 'scripts', 'add_story_update.py')

UN_STORY = 'st-20261103-united-nations'
BRANCHES = {
    # branch → (story_id, first date it applies from)
    'unga': ('st-20260922-unga81-general-debate', '2026-09-08'),   # UNGA 81 opened 8 Sep
}
SOURCE_NAME = {'press': 'UN Meetings Coverage', 'news': 'UN News'}


def stories_for(row):
    target = BRANCHES.get(row['branch'])
    if target and row['date'] >= target[1]:
        return [UN_STORY, target[0]]
    return [UN_STORY]


def headline(title):
    title = ' '.join(title.split())
    if len(title) <= 140:
        return title
    return title[:139].rsplit(' ', 1)[0].rstrip(' ,;:–-') + '…'


def payload(row, story_id):
    return {
        'story_id': story_id,
        'date': row['date'],
        'headline': headline(row['title']),
        'summary': ' '.join((row['lede'] or row['title']).split()),
        'source_name': SOURCE_NAME.get(row['stream'], 'UN News'),
        'url': row['url'],
        'status': 'new',
        'origin': row['organ'],
        'image': row['image'],
    }


def main():
    dry = '--dry-run' in sys.argv
    with open(REPORTS_CSV, newline='', encoding='utf-8') as f:
        rows = sorted(csv.DictReader(f), key=lambda r: (r['published'], r['id']))
    items = [payload(r, sid) for r in rows if r['url'] and r['title'] for sid in stories_for(r)]
    counts = {}
    for it in items:
        counts[it['story_id']] = counts.get(it['story_id'], 0) + 1
    print(f'{len(items)} UN report(s) → ' + ', '.join(f'{k}: {v}' for k, v in counts.items()))
    args = [sys.executable, WRITER, '--no-fetch'] + (['--dry-run'] if dry else [])
    res = subprocess.run(args, input=json.dumps(items), text=True, capture_output=True, cwd=ROOT)
    # The writer reports per-item; print only its summary lines, not one line per duplicate.
    out = [l for l in res.stdout.splitlines() if 'duplicate' not in l.lower()]
    print('\n'.join(out[-15:]))
    if res.returncode:
        print(res.stderr, file=sys.stderr)
    return res.returncode


if __name__ == '__main__':
    sys.exit(main())
