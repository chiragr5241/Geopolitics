#!/usr/bin/env python3
"""
Match the hidden YouTube archive onto tracked stories.

This is the only way a video reaches the site. data/youtube_videos.csv never
feeds data/intel_feed.csv, so nothing here shows on the Feed page; a video
becomes visible exactly when it earns a place on a story's timeline, as a
story_updates row with origin='youtube'.

RETROACTIVE BY DESIGN — and that is the difference from update_stories.py,
which only scans intel rows newer than a story's last_update_at. When you start
tracking something, the interesting videos about it were published BEFORE you
started tracking it: a channel's 40-minute explainer of the conflict you just
added is the whole point. So every run scores the WHOLE archive against every
tracked story.

Because the archive is scored whole, an unbounded match would bury the curated
beats (the same failure mode that keeps update_stories.py forward-only — one
story matched 623 feed rows). So matches are ranked and capped per story:
MAX_PER_STORY overall, MAX_PER_RUN newly added each run.

Scoring (a video must clear MIN_SCORE):
    +3  per story keyword found in the video's title
    +2  per story keyword found in its description/keywords
    +2  shares a country with the story
    +1  the channel sits in a core geopolitics/news/defence topic
    -2  the video predates the story's earliest interest by years
Ties break toward the more recent video.

Per-story source selection is honoured exactly as everywhere else: a channel
the user deselected contributes nothing, and one they re-select is picked up on
the next run (retroactively, since the whole archive is rescored).

Usage (from project root):
    python3 scripts/link_youtube.py [--dry-run] [--story st-…] [--verbose]
"""

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from source_registry import load_sources, story_sources, categories_of  # noqa: E402
from story_dedup import build_index, is_fuzzy_dup, note_accepted        # noqa: E402
from add_story_update import header_matches, backfill_sources           # noqa: E402
from pull_youtube import load_videos                                    # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST_JSON = os.path.join(ROOT, 'data', 'watchlist.json')
STORY_UPDATES_CSV = os.path.join(ROOT, 'data', 'story_updates.csv')

STORY_UPDATE_COLUMNS = [
    'story_id', 'update_id', 'date', 'headline', 'summary',
    'source_name', 'url', 'status', 'severity', 'origin', 'found_at', 'image',
    'source_id',
]

MIN_SCORE = 6            # below this it's a coincidence, not a match
MAX_PER_STORY = 12       # total video beats a story may accumulate
MAX_PER_RUN = 4          # new ones per run, so a timeline never floods at once

# Channels whose subject matter is the site's own — a tie-break nudge only.
CORE_TOPIC_WORDS = ('Geopolitics', 'News & Current', 'War, Defense',
                    'Military History', 'Economics & Business', 'Geography')


def load_watchlist():
    if not os.path.exists(WATCHLIST_JSON):
        return {'stories': []}
    with open(WATCHLIST_JSON, encoding='utf-8') as f:
        return json.load(f)


def load_existing_updates():
    if not os.path.exists(STORY_UPDATES_CSV):
        return [], set(), {}
    with open(STORY_UPDATES_CSV, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    keys, video_counts = set(), {}
    for r in rows:
        if r.get('url'):
            keys.add((r['story_id'], 'url', r['url']))
        else:
            keys.add((r['story_id'], 'text', r['date'],
                      ' '.join((r.get('headline') or '').split())))
        if r.get('origin') == 'youtube':
            video_counts[r['story_id']] = video_counts.get(r['story_id'], 0) + 1
    return rows, keys, video_counts


def next_update_id(rows, story_id):
    nums = []
    for r in rows:
        if r['story_id'] != story_id:
            continue
        m = re.search(r'-u(\d+)$', r.get('update_id', ''))
        if m:
            nums.append(int(m.group(1)))
    return max(nums, default=0) + 1


def story_year(story):
    """The year the story's interest starts — its seed date."""
    for val in ((story.get('seed') or {}).get('created_at'), story.get('marked_at')):
        if val and len(val) >= 4 and val[:4].isdigit():
            return int(val[:4])
    return 0


# Words too generic to identify a story if they're all we have to go on.
_TITLE_STOP = {
    'the', 'a', 'an', 'and', 'or', 'of', 'in', 'on', 'at', 'to', 'for', 'from',
    'with', 'his', 'her', 'its', 'their', 'new', 'war', 'crisis', 'news',
    'world', 'across', 'use', 'against', 'over', 'between', 'политика',
}


def story_keywords(story):
    """The story's keywords, falling back to significant words in its title.

    A story added by hand often has an empty `keywords` list — the NYC Mayor
    Mamdani story is exactly that — and with no keywords and no countries it
    could never match any video at all. Its title is the one thing every story
    has, so use it rather than silently returning nothing.
    """
    keywords = [k.lower() for k in (story.get('keywords') or []) if k]
    if keywords:
        return keywords
    words = re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", story.get('title') or '')
    return [w.lower() for w in words if w.lower() not in _TITLE_STOP][:8]


def keyword_rarity(videos):
    """How discriminating each word is, as a share of the archive that uses it.

    Without this every keyword weighs the same, so "mayor" (in hundreds of
    videos) counts as much as "mamdani" (in one) — and a story whose subject is
    named by a rare proper noun scores BELOW a story matched on two generic
    words. Cheap document-frequency over the archive, computed once per run.
    """
    counts = {}
    for v in videos:
        seen = set(re.findall(r"[a-z][a-z'\-]{2,}",
                              (v.get('title', '') + ' ' + v.get('description', '') + ' ' +
                               v.get('keywords', '')).lower()))
        for w in seen:
            counts[w] = counts.get(w, 0) + 1
    return counts, max(1, len(videos))


def rarity_bonus(word, counts, total):
    """+2 for a word that identifies a subject, 0 for a common one."""
    share = counts.get(word, 0) / total
    if share and share <= 0.005:      # in <=0.5% of the archive: highly specific
        return 2
    if share and share <= 0.02:
        return 1
    return 0


def score_video(video, story, core_channel, counts=None, total=1):
    keywords = story_keywords(story)
    countries = {c.upper() for c in ((story.get('seed') or {}).get('countries') or [])}
    if not keywords and not countries:
        return 0, []

    title = (video.get('title') or '').lower()
    body = ((video.get('description') or '') + ' ' +
            (video.get('keywords') or '')).lower()

    score, why, kw_hits = 0, [], 0
    for kw in keywords:
        bonus = rarity_bonus(kw, counts or {}, total)
        if kw in title:
            score += 3 + bonus
            kw_hits += 1
            why.append(f'title:{kw}' + ('+' if bonus else ''))
        elif kw in body:
            score += 2 + bonus
            kw_hits += 1
            why.append(f'body:{kw}' + ('+' if bonus else ''))

    vid_countries = {c.strip().upper()
                     for c in (video.get('countries') or '').split(';') if c.strip()}
    country_hit = bool(countries & vid_countries)
    if country_hit:
        score += 2
        why.append('country:' + ','.join(sorted(countries & vid_countries)))

    # Two independent signals, or it's a coincidence. One keyword on its own
    # matched "Mayor warns of possible Bordeaux evacuation" to a story about the
    # mayor of New York — the word was shared, the subject was not. The channel
    # being on-topic is NOT a second signal; most of them are.
    if kw_hits < 2 and not (kw_hits and country_hit):
        return 0, []

    if core_channel:
        score += 1
        why.append('core-topic')

    # A video from years before the story began is usually background, not
    # coverage. Still allowed (background explainers are wanted) but ranked down.
    sy = story_year(story)
    vy = int(video['published_at'][:4]) if video.get('published_at', '')[:4].isdigit() else 0
    if sy and vy and vy < sy - 2:
        score -= 2
        why.append('old')

    return score, why


def main():
    dry_run = '--dry-run' in sys.argv
    verbose = '--verbose' in sys.argv
    only_story = None
    if '--story' in sys.argv:
        i = sys.argv.index('--story')
        if i + 1 < len(sys.argv):
            only_story = sys.argv[i + 1]

    videos = load_videos()
    if not videos:
        print('data/youtube_videos.csv is empty — run pull_youtube.py first.')
        return

    kw_counts, kw_total = keyword_rarity(videos)
    registry = {r['source_id']: r for r in load_sources()}
    core_ids = {sid for sid, r in registry.items()
                if any(w in c for c in categories_of(r) for w in CORE_TOPIC_WORDS)}

    watchlist = load_watchlist()
    stories = [s for s in watchlist.get('stories', [])
               if s.get('status') in ('active', 'resolved')]
    if only_story:
        stories = [s for s in stories if s.get('story_id') == only_story]
    if not stories:
        print('No tracked stories to match against.')
        return

    existing_rows, existing_keys, video_counts = load_existing_updates()
    fuzzy_index = build_index(existing_rows)
    now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    new_rows = []
    per_story = {}
    skipped_deselected = {}

    for story in stories:
        sid = story['story_id']
        excluded = set(story_sources(story)['excluded'])
        room = MAX_PER_STORY - video_counts.get(sid, 0)
        if room <= 0:
            continue

        ranked = []
        for v in videos:
            src = v.get('source_id') or ''
            if src in excluded:
                skipped_deselected[sid] = skipped_deselected.get(sid, 0) + 1
                continue
            row = registry.get(src)
            if not row or row.get('status') not in ('active', 'unverified'):
                continue
            score, why = score_video(v, story, src in core_ids, kw_counts, kw_total)
            if score >= MIN_SCORE:
                ranked.append((score, v.get('published_at', ''), v, why))

        # Best score first; among equals, the most recent video.
        ranked.sort(key=lambda t: (t[0], t[1]), reverse=True)

        added = 0
        for score, _pub, v, why in ranked:
            if added >= min(room, MAX_PER_RUN):
                break
            key = (sid, 'url', v['url'])
            if key in existing_keys:
                continue
            headline = ' '.join((v.get('title') or '').split())[:140]
            date_str = (v.get('published_at') or '')[:10] or now_iso[:10]
            if is_fuzzy_dup(sid, date_str, headline, fuzzy_index):
                continue
            existing_keys.add(key)
            note_accepted(sid, date_str, headline, fuzzy_index)

            # The routine's rewritten summary when it has one, else the raw
            # description trimmed to something a timeline cell can show.
            summary = (v.get('summary') or '').strip()
            if not summary:
                summary = ' '.join((v.get('description') or '').split())[:400]

            n = next_update_id(existing_rows + new_rows, sid)
            new_rows.append({
                'story_id': sid,
                'update_id': f'{sid}-u{n:03d}',
                'date': date_str,
                'headline': headline,
                'summary': summary,
                'source_name': v.get('channel') or registry.get(v['source_id'], {}).get('name', ''),
                'url': v['url'],
                'status': 'developing',
                'severity': '',
                'origin': 'youtube',
                'found_at': now_iso,
                'image': v.get('thumbnail', ''),
                'source_id': v.get('source_id', ''),
            })
            added += 1
            per_story.setdefault(sid, []).append((score, v['title'][:60], why))

    print(f'Stories scored: {len(stories)};  archive: {len(videos)} videos')
    print(f'New video beats: {len(new_rows)}')
    for sid, hits in per_story.items():
        print(f'  {sid}: +{len(hits)}')
        for score, title, why in hits:
            print(f'      [{score:2d}] {title}' + (f'   ({", ".join(why[:4])})' if verbose else ''))
    for sid, n in skipped_deselected.items():
        print(f'  {sid}: {n} video(s) skipped — their channel is deselected for this story')

    if not new_rows:
        print('No new matches.')
        return
    if dry_run:
        print('Dry run — no changes written.')
        return

    if not header_matches():
        print('story_updates.csv predates the source_id column — migrating first.')
        backfill_sources()

    write_header = not os.path.exists(STORY_UPDATES_CSV)
    with open(STORY_UPDATES_CSV, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=STORY_UPDATE_COLUMNS, quoting=csv.QUOTE_ALL)
        if write_header:
            w.writeheader()
        w.writerows(new_rows)
    print(f'Appended {len(new_rows)} rows to story_updates.csv.')
    print('Next: python3 scripts/build_db.py')


if __name__ == '__main__':
    main()
