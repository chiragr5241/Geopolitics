#!/usr/bin/env python3
"""
YouTube ingestion — pull new videos from the registry's channels into
data/youtube_videos.csv.

This is the HIDDEN half of the source registry. A `scope=video` source behaves
like any other source — it sits in the picker, obeys per-story selection, gets
name-corrected, can be flagged not_found — with one difference: its items never
enter data/intel_feed.csv, so they never appear on the Feed page. A video
reaches the site only when scripts/link_youtube.py matches it onto a tracked
story. That is what "hidden unless it is part of a story" means mechanically.

Two stages, both stdlib-only (urllib + xml.etree), same shape as pull_wires.py:

  --resolve-channels   Turn each channel's @handle into a real channel id by
                       fetching youtube.com/@handle and reading the canonical
                       channel URL out of the HTML. Writes the resulting
                       feed_url back onto data/sources.csv and flips the row
                       active. NOTHING is guessed — a handle that doesn't
                       resolve stays `unverified` and is listed for the routine
                       to fix by WebSearch, exactly like a user-typed source.

  (default)            Fetch every resolved channel's feed
                       (youtube.com/feeds/videos.xml?channel_id=…, 15 most
                       recent videos, no API key) and merge new rows into
                       data/youtube_videos.csv.

Row schema (data/youtube_videos.csv):
  video_id, source_id, channel, title, description, published_at, url,
  thumbnail, categories, countries, keywords, detail_status, summary, fetched_at

`title`/`description` are what YouTube returned. `summary` is the routine's
rewritten one-line account of what the video actually covers, and
`detail_status` is base|detailed — the same two-tier split the tweet pipeline
uses, so a backlog of un-summarised videos can never block ingestion.

Unlike the wire pull there is NO time window: the file is the archive a newly
tracked story gets searched against, so old videos are kept deliberately.

Usage (from repo root):
    python3 scripts/pull_youtube.py --resolve-channels [--limit N] [--dry-run]
    python3 scripts/pull_youtube.py --resolve-channels --reverify   # re-check all
    python3 scripts/pull_youtube.py [--limit N] [--dry-run]
    python3 scripts/pull_youtube.py --unresolved      # what still needs a handle
"""

import csv
import difflib
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from source_registry import (load_sources, save_sources, record_fetch,  # noqa: E402
                             USABLE_STATUS, normalize)
from enrich_lib import classify  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEOS_CSV = os.path.join(ROOT, 'data', 'youtube_videos.csv')

VIDEO_COLUMNS = [
    'video_id', 'source_id', 'channel', 'title', 'raw_title', 'description',
    'published_at', 'url', 'thumbnail', 'categories', 'countries', 'keywords',
    'detail_status', 'summary', 'fetched_at',
]

UA = 'Mozilla/5.0 (compatible; geopolitics-tracker/1.0)'
FEED_TMPL = 'https://www.youtube.com/feeds/videos.xml?channel_id={}'
ATOM = '{http://www.w3.org/2005/Atom}'
MRSS = '{http://search.yahoo.com/mrss/}'
YT = '{http://www.youtube.com/xml/schemas/2015}'

CHANNEL_DELAY = 0.6          # be polite; ~185 channels
DESCRIPTION_CAP = 1500       # descriptions can be enormous (chapter lists, links)


def _now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def fetch(url, timeout=25, retries=1):
    last = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={'User-Agent': UA,
                                        'Accept-Language': 'en-US,en;q=0.9'})
            with urlopen(req, timeout=timeout) as r:
                return r.read()
        except (URLError, HTTPError) as e:
            last = e
            if isinstance(e, HTTPError) and e.code in (403, 404):
                raise
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last


# ── Stage 1: handle → channel id ─────────────────────────────────────────── #

# ORDER MATTERS. A channel page mentions several channel ids — the sidebar's
# featured/related channels among them — and the FIRST `"channelId"` in the
# HTML is routinely one of those, not the page's own. Matching it sent
# @CaspianReport to a Spanish channel and @NYCMayorsOffice to NYC's technology
# office. The canonical link and `externalId` are the page's own identity and
# agree with each other; the loose patterns stay only as a last resort.
_CHANNEL_ID_PATTERNS = [
    r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"',
    r'"externalId"\s*:\s*"(UC[\w-]{22})"',
    r'<meta property="og:url" content="https://www\.youtube\.com/channel/(UC[\w-]{22})"',
    r'"channelId"\s*:\s*"(UC[\w-]{22})"',
]


def resolve_channel_id(handle):
    """Real channel id for an @handle, or '' if YouTube doesn't confirm one.

    Only ever returns an id YouTube itself served — a handle we guessed wrong
    yields '' and the caller flags it. We never synthesise an id.
    """
    handle = (handle or '').lstrip('@').strip()
    if not handle:
        return ''
    for url in (f'https://www.youtube.com/@{handle}',
                f'https://www.youtube.com/c/{handle}',
                f'https://www.youtube.com/user/{handle}'):
        try:
            html = fetch(url).decode('utf-8', 'ignore')
        except (HTTPError, URLError):
            continue
        for pat in _CHANNEL_ID_PATTERNS:
            m = re.search(pat, html)
            if m:
                return m.group(1)
    return ''


def channel_title(feed_url):
    """The channel's own name, straight from its feed."""
    try:
        root = ET.fromstring(fetch(feed_url))
    except (HTTPError, URLError, ET.ParseError):
        return None
    return _text(root, ATOM + 'title')


def titles_match(expected, actual):
    """Is the channel we landed on the one we were looking for?

    Necessary because a guessed handle can resolve to a REAL channel that is
    simply the wrong one — @CaspianReport served a Spanish channel called
    "Historia Geopolítica". Checking only "did YouTube return an id" would have
    silently filed that channel's videos under CaspianReport. Substring either
    way (channels append "News", "TV", "Official"), else fuzzy on the
    registry's own normalised comparison.
    """
    if not actual:
        return False
    a, b = normalize(expected), normalize(actual)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def resolve_channels(limit=None, dry_run=False, reverify=False):
    rows = load_sources()
    todo = [r for r in rows
            if r.get('kind') == 'youtube'
            and (reverify or not r.get('feed_url'))
            and r.get('status') in USABLE_STATUS]
    if limit:
        todo = todo[:limit]
    print(f'Resolving {len(todo)} channel(s)' +
          (' (re-verifying already-resolved ones too)' if reverify else
           ' with no feed_url yet') + '.')

    ok, failed, mismatched = 0, [], []
    for i, r in enumerate(todo):
        if i:
            time.sleep(CHANNEL_DELAY)
        feed = r.get('feed_url') if reverify and r.get('feed_url') else None
        cid = ''
        if not feed:
            cid = resolve_channel_id(r.get('handle'))
            if not cid:
                failed.append(r)
                print(f"  ? {r['name'][:38]:38s} handle @{r.get('handle')} did not resolve")
                continue
            feed = FEED_TMPL.format(cid)

        # Confirm the channel we found is the channel we wanted.
        actual = channel_title(feed)
        if not titles_match(r['name'], actual):
            mismatched.append((r, actual))
            r['feed_url'] = ''
            r['status'] = 'unverified'
            r['notes'] = (f"handle @{r.get('handle')} resolves to "
                          f"{actual!r} — not this channel; needs the right handle")
            print(f"  ! {r['name'][:38]:38s} resolved to {str(actual)[:34]!r} — REJECTED")
            continue

        r['feed_url'] = feed
        r['status'] = 'active'
        r['notes'] = f'confirmed as {actual!r}' + (f' (channel_id={cid})' if cid else '')
        ok += 1
        print(f"  + {r['name'][:38]:38s} {actual[:34]}")

    print(f'\nConfirmed {ok}; wrong-channel {len(mismatched)}; unresolved {len(failed)}.')
    if failed or mismatched:
        print('Those keep status=unverified and are NOT pulled. Give them the '
              'right @handle (or confirm the channel does not exist) via:')
        print("  echo '[{\"source_id\":\"yt-…\",\"handle\":\"RealHandle\"}]' "
              "| python3 scripts/source_registry.py --upsert")
    if dry_run:
        print('Dry run — nothing written.')
        return
    save_sources(rows)
    print('Updated data/sources.csv.')


# ── Stage 2: channel feed → videos ───────────────────────────────────────── #

def _text(node, tag):
    el = node.find(tag)
    return (el.text or '').strip() if el is not None and el.text else ''


def parse_channel_feed(xml_bytes, source_id, fallback_name):
    root = ET.fromstring(xml_bytes)
    channel = _text(root, ATOM + 'title') or fallback_name
    out = []
    for entry in root.findall(ATOM + 'entry'):
        vid = _text(entry, YT + 'videoId')
        title = _text(entry, ATOM + 'title')
        if not vid or not title:
            continue
        published = _text(entry, ATOM + 'published') or _text(entry, ATOM + 'updated')
        group = entry.find(MRSS + 'group')
        desc, thumb = '', ''
        if group is not None:
            desc = _text(group, MRSS + 'description')
            t = group.find(MRSS + 'thumbnail')
            if t is not None:
                thumb = t.get('url', '')
        if len(desc) > DESCRIPTION_CAP:
            desc = desc[:DESCRIPTION_CAP].rstrip() + '…'
        out.append({
            'video_id': vid,
            'source_id': source_id,
            'channel': channel,
            'title': title,
            'description': desc,
            'published_at': published.replace('+00:00', 'Z'),
            'url': f'https://www.youtube.com/watch?v={vid}',
            'thumbnail': thumb,
            'detail_status': 'base',
            'summary': '',
            'fetched_at': _now_iso(),
        })
    return out


# ── Deterministic base pass ──────────────────────────────────────────────── #
# Mirrors base_enrich.py: every video gets keyword-derived categories/countries
# the moment it lands, so link_youtube.py works without waiting for the agent's
# detail pass. Reuses the SAME keyword tables as the tweet/wire pipeline so a
# story's keywords match against videos the way they match against everything.

_TITLE_STOPWORDS = {
    'the', 'this', 'that', 'how', 'why', 'what', 'when', 'who', 'and', 'but',
    'for', 'are', 'was', 'its', 'new', 'not', 'you', 'your', 'has', 'can',
    'all', 'his', 'her', 'their', 'from', 'with', 'into', 'over',
}


def base_annotate(row):
    # Title AND description: a channel's title is often a hook ("The REAL
    # reason…") while the description names the actual subject.
    text = f"{row['title']}. {row['description']}"
    c = classify(text)
    row['categories'] = ';'.join(x for x in [c['category'], c['subcategory']] if x)
    row['countries'] = c['countries']

    # Keywords: proper nouns from the title, which is what a story's own
    # keyword list is matched against in link_youtube.py.
    keywords = []
    for w in re.findall(r'\b[A-Z][a-zA-Z\-]{2,}\b', row['title']):
        wl = w.lower()
        if wl not in _TITLE_STOPWORDS and wl not in keywords:
            keywords.append(wl)
    row['keywords'] = ';'.join(keywords[:10])
    return row


# ── File I/O ─────────────────────────────────────────────────────────────── #

def load_videos():
    if not os.path.exists(VIDEOS_CSV):
        return []
    with open(VIDEOS_CSV, newline='', encoding='utf-8') as f:
        rows = [dict(r) for r in csv.DictReader(f)]
    for r in rows:
        for c in VIDEO_COLUMNS:
            r.setdefault(c, '')
    return rows


def save_videos(rows):
    rows.sort(key=lambda r: r.get('published_at', ''), reverse=True)
    tmp = VIDEOS_CSV + '.tmp'
    with open(tmp, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=VIDEO_COLUMNS, quoting=csv.QUOTE_ALL,
                           extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, VIDEOS_CSV)


def pull(limit=None, dry_run=False):
    rows = load_sources()
    channels = [r for r in rows
                if r.get('kind') == 'youtube' and r.get('feed_url')
                and r.get('status') in USABLE_STATUS]
    if limit:
        channels = channels[:limit]
    if not channels:
        print('No resolved YouTube channels yet — run --resolve-channels first.')
        return

    existing = load_videos()
    seen = {r['video_id'] for r in existing}

    fetched, per_channel, failed = [], {}, {}
    for i, ch in enumerate(channels):
        if i:
            time.sleep(CHANNEL_DELAY)
        try:
            vids = parse_channel_feed(fetch(ch['feed_url']), ch['source_id'], ch['name'])
        except (HTTPError, URLError, ET.ParseError, OSError) as e:
            print(f"  ! {ch['name'][:34]:34s} {e} — skipped")
            failed[ch['name']] = str(e)
            continue
        new = [v for v in vids if v['video_id'] not in seen]
        for v in new:
            seen.add(v['video_id'])
            fetched.append(base_annotate(v))
        per_channel[ch['name']] = (len(vids), len(new))

    print(f'\nYouTube pull: {len(channels)} channel(s)')
    quiet = [n for n, (_, new) in per_channel.items() if not new]
    for name, (total, new) in sorted(per_channel.items(), key=lambda kv: -kv[1][1]):
        if new:
            print(f'  {name[:34]:34s} {new:3d} new  (of {total} in feed)')
    # A channel with nothing new is healthy and common — say so once, plainly,
    # rather than printing 150 lines that look like failures.
    print(f'  {len(quiet)} channel(s) reached with nothing new — normal.')
    for name, why in failed.items():
        print(f'  {name[:34]:34s} UNREACHABLE — {why}')
    print(f'New videos: {len(fetched)}; archive would hold {len(existing) + len(fetched)}.')

    if dry_run:
        for v in fetched[:8]:
            print(f"    [{v['channel'][:20]:20s}] {v['published_at'][:10]}  {v['title'][:60]}")
        print('Dry run — nothing written.')
        return

    for ch in channels:
        if ch['name'] in per_channel:
            record_fetch(ch['source_id'], per_channel[ch['name']][1], rows, persist=False)
    save_sources(rows)

    if not fetched:
        print('Nothing new to write.')
        return
    save_videos(existing + fetched)
    print(f'Wrote {len(existing) + len(fetched)} rows -> data/youtube_videos.csv '
          f'(+{len(fetched)} new)')


def report_unresolved():
    rows = load_sources()
    todo = [r for r in rows if r.get('kind') == 'youtube' and not r.get('feed_url')]
    if not todo:
        print('Every YouTube channel has a resolved feed.')
        return
    print(f'{len(todo)} channel(s) without a resolved feed:')
    for r in todo:
        print(f"  {r['source_id']:34s} {r['name'][:34]:34s} handle=@{r.get('handle')} [{r['status']}]")


def main():
    dry_run = '--dry-run' in sys.argv
    limit = None
    if '--limit' in sys.argv:
        i = sys.argv.index('--limit')
        if i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])

    if '--unresolved' in sys.argv:
        report_unresolved()
    elif '--resolve-channels' in sys.argv:
        resolve_channels(limit=limit, dry_run=dry_run,
                         reverify='--reverify' in sys.argv)
    else:
        pull(limit=limit, dry_run=dry_run)


if __name__ == '__main__':
    main()
