#!/usr/bin/env python3
"""
Install a downloaded watchlist.json into the repo and rebuild the database.

The tracker page saves your tracked-story selection to the browser's
localStorage automatically, and the "Export watchlist.json" button downloads
that record. This helper "commits" that download into the site's data so the
selection becomes the durable, versioned record everyone sees after deploy:

  1. validates the JSON shape,
  2. copies it to data/watchlist.json,
  3. runs scripts/build_db.py to regenerate data/database.json.

Usage (from project root):
  python scripts/import_watchlist.py ~/Downloads/watchlist.json
  python scripts/import_watchlist.py ~/Downloads/watchlist.json --no-build

Then review `git diff data/watchlist.json` and commit.
"""

import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data')
DEST = os.path.join(DATA_DIR, 'watchlist.json')
BUILD = os.path.join(ROOT, 'scripts', 'build_db.py')


def latest_download():
    """Best-effort default: the newest watchlist*.json in ~/Downloads."""
    dl = os.path.expanduser('~/Downloads')
    if not os.path.isdir(dl):
        return None
    cands = [os.path.join(dl, f) for f in os.listdir(dl)
             if f.startswith('watchlist') and f.endswith('.json')]
    if not cands:
        return None
    return max(cands, key=os.path.getmtime)


def validate(path):
    with open(path, encoding='utf-8') as f:
        doc = json.load(f)
    if not isinstance(doc, dict) or 'stories' not in doc:
        raise ValueError('Not a watchlist file: missing top-level "stories".')
    stories = doc['stories']
    if not isinstance(stories, list):
        raise ValueError('"stories" must be a list.')
    ids = set()
    for s in stories:
        sid = s.get('story_id')
        if not sid:
            raise ValueError('A story is missing "story_id".')
        if sid in ids:
            raise ValueError(f'Duplicate story_id: {sid}')
        ids.add(sid)
        if not s.get('title'):
            raise ValueError(f'Story {sid} is missing a title.')
    active = sum(1 for s in stories if s.get('status') == 'active')
    return len(stories), active


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    no_build = '--no-build' in sys.argv

    src = args[0] if args else latest_download()
    if not src:
        print('Usage: python scripts/import_watchlist.py <path-to-watchlist.json>')
        print('(No path given and no watchlist*.json found in ~/Downloads.)')
        sys.exit(1)
    src = os.path.expanduser(src)
    if not os.path.isfile(src):
        print(f'File not found: {src}')
        sys.exit(1)

    try:
        total, active = validate(src)
    except (ValueError, json.JSONDecodeError) as e:
        print(f'Invalid watchlist file: {e}')
        sys.exit(1)

    shutil.copyfile(src, DEST)
    print(f'Installed {src}\n     -> {DEST}')
    print(f'  {total} stories ({active} active)')

    if no_build:
        print('Skipped rebuild (--no-build). Run scripts/build_db.py when ready.')
        return

    print('\nRebuilding database...')
    subprocess.run([sys.executable, BUILD], check=True)
    print('\nDone. Review `git diff data/watchlist.json` and commit.')


if __name__ == '__main__':
    main()
