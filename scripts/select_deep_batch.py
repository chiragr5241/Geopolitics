#!/usr/bin/env python3
"""
Select the next BOUNDED batch of base-tier rows for deep (agent) enrichment.

Solution A (batch cap) + C (noise excluded): the scheduled task no longer tries
to deep-research every backlogged tweet in one run — it asks this script for the
top N most significant rows still at tier=base, deep-researches only those, and
always finishes within budget. Because base_enrich.py already cleared the queue,
whatever is left un-deepened is a soft backlog, not a hard stall.

Selection: tier=base, subcategory!=noise, severity>=MIN_SEV, ordered by
(prioritized-by-active-story, severity desc, oldest first), capped at N.

Prints a JSON array to stdout. Each item includes the raw text plus the current
base classification and any matched active story, so the agent knows what to
research and which tracked story to attribute it to.

Usage (from project root):
    python3 scripts/select_deep_batch.py [N]      # default N=8
"""

import json
import os
import sys

from enrich_lib import NOISE_SUBCATEGORY, ROOT, load_enriched

MIN_SEV = 2


def load_active_stories():
    path = os.path.join(ROOT, 'data', 'watchlist.json')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        wl = json.load(f)
    out = []
    for s in wl.get('stories', []):
        if s.get('status') != 'active':
            continue
        out.append({
            'story_id': s.get('story_id', ''),
            'keywords': [k.lower() for k in s.get('keywords', [])],
            'countries': [c.upper() for c in s.get('seed', {}).get('countries', [])],
            'query_hints': s.get('query_hints', []),
        })
    return out


def match_story(row, stories):
    text = (row.get('original_text') or '').lower()
    countries = set((row.get('countries') or '').split(';'))
    for s in stories:
        if any(kw in text for kw in s['keywords']):
            return s['story_id']
        if s['countries'] and countries & set(s['countries']) and any(
                kw in text for kw in s['keywords']):
            return s['story_id']
    return ''


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8
    stories = load_active_stories()
    rows, _ = load_enriched()

    candidates = []
    for r in rows:
        if r.get('tier') != 'base':
            continue
        if r.get('subcategory') == NOISE_SUBCATEGORY:
            continue
        try:
            sev = int(r.get('severity') or 0)
        except ValueError:
            sev = 0
        if sev < MIN_SEV:
            continue
        sid = match_story(r, stories)
        candidates.append((sid, sev, r))

    # prioritized (matches a tracked story) first, then severity desc, then oldest
    candidates.sort(key=lambda t: (t[0] == '', -t[1], t[2].get('pub_date', '')))

    batch = []
    for sid, sev, r in candidates[:n]:
        batch.append({
            'id': r['id'],
            'tweet_id': r['tweet_id'],
            'pub_date': r['pub_date'],
            'original_text': r['original_text'],
            'base_category': r['category'],
            'base_subcategory': r['subcategory'],
            'base_countries': r['countries'],
            'base_severity': sev,
            'matched_story_id': sid,
        })

    print(json.dumps(batch, indent=2, ensure_ascii=False))
    print(f'\n# {len(batch)} of {len(candidates)} deep-enrichment candidates '
          f'(cap={n})', file=sys.stderr)


if __name__ == '__main__':
    main()
