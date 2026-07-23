#!/usr/bin/env python3
"""
Shared duplicate detection for story-update scraping.

Both update_stories.py (deterministic intel matches) and add_story_update.py
(agent WebSearch beats) append to data/story_updates.csv. Exact keys
((story_id, url) or (story_id, date, normalized headline)) miss NEAR-duplicates:
the same event scraped by two sources, or by 7a and 7b, whose headlines differ
in wording (e.g. "IRGC declares the Strait of Hormuz fully closed" vs "IRGC
declares the Strait of Hormuz fully closed until US strikes stop, disputed by
Trump"). This module adds a fuzzy check so those collapse to one row.

An incoming update is a duplicate of an existing one when they belong to the
same story, are within DATE_WINDOW days of each other, and share at least
JACCARD_THRESHOLD of their significant words.

Pure, deterministic, no network.
"""

import re
from datetime import datetime

JACCARD_THRESHOLD = 0.6
DATE_WINDOW = 1          # days; same event can straddle a day boundary across sources

_STOP = {
    'the', 'a', 'an', 'of', 'to', 'in', 'on', 'and', 'for', 'as', 'at', 'by',
    'is', 'are', 'was', 'were', 'with', 'after', 'over', 'from', 'its', 'that',
    'this', 'has', 'have', 'had', 'will', 'amid', 'into', 'out', 'up', 'says',
    'said', 'new', 'us',
}


def sig(text):
    """Significant-word set of a headline (len>=4, no stopwords, deduped)."""
    words = re.sub(r'[^a-z0-9 ]', ' ', (text or '').lower()).split()
    return {w for w in words if len(w) >= 4 and w not in _STOP}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def _parse_date(d):
    try:
        return datetime.strptime((d or '')[:10], '%Y-%m-%d')
    except ValueError:
        return None


def build_index(existing_rows):
    """Index existing story_updates rows by story_id -> [(date, sigset)]."""
    idx = {}
    for r in existing_rows:
        sid = r.get('story_id')
        if not sid:
            continue
        idx.setdefault(sid, []).append((r.get('date', ''), sig(r.get('headline') or r.get('summary') or '')))
    return idx


def is_fuzzy_dup(story_id, date, headline, index):
    """True if a near-duplicate of (date, headline) already exists for story_id.

    `index` is a MUTABLE dict from build_index(); accepted rows should be added
    to it (see note_accepted) so a batch doesn't admit its own duplicates."""
    incoming = sig(headline)
    if not incoming:
        return False
    idt = _parse_date(date)
    for edate, esig in index.get(story_id, []):
        edt = _parse_date(edate)
        if idt and edt and abs((idt - edt).days) > DATE_WINDOW:
            continue
        if jaccard(incoming, esig) >= JACCARD_THRESHOLD:
            return True
    return False


def note_accepted(story_id, date, headline, index):
    """Record an accepted row so later items in the same batch dedup against it."""
    index.setdefault(story_id, []).append((date, sig(headline)))
