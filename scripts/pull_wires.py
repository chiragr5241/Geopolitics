#!/usr/bin/env python3
"""
Wire ingestion — pull global news sources into data/raw_data/wire_raw.csv.

Companion to pull_spectator.py. Where the Spectator pull captures one curated
tweet stream, this captures a *diverse* set of outlets so the feed can show an
event from several perspectives instead of a single (usually Western) framing —
e.g. Russian-sourced coverage of the Ukraine war via GDELT alongside BBC/AJ.

Two adapter kinds, both stdlib-only (urllib + xml.etree), matching the
zero-dependency style of pull_spectator.py:

  rss    — plain RSS/Atom feeds (BBC, DW, Al Jazeera, UN News, ReliefWeb, BNO).
           Native images pulled from media:thumbnail / media:content /
           enclosure / first <img> in the description when present.
  gdelt  — GDELT DOC 2.0 ArtList API (no key). One query per theatre with a
           sourcecountry: filter, so `perspective`/`source_country` carry the
           reporting country — this is the non-Western lever.

Output row schema (data/raw_data/wire_raw.csv):
  id, source, source_kind, perspective, pub_date, title, lede, url,
  source_country, image, is_fast_lead

`id` = sha1(source|url) — stable, so re-runs dedup and never duplicate a URL.
`pub_date` normalised to YYYY-MM-DDTHH:MM:SSZ (same shape as spectator_raw).
Idempotent: merges with the existing file, keeps a 60h window, sorts ascending.

Usage (from repo root):
    python3 scripts/pull_wires.py            # fetch + write
    python3 scripts/pull_wires.py --dry-run  # fetch + report, write nothing
    python3 scripts/pull_wires.py --no-gdelt # skip the GDELT queries (RSS only)
"""

import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIRE_CSV = os.path.join(ROOT, 'data', 'raw_data', 'wire_raw.csv')
WIRE_HEADERS = [
    'id', 'source', 'source_kind', 'perspective', 'pub_date',
    'title', 'lede', 'url', 'source_country', 'image', 'is_fast_lead',
]

WINDOW_HOURS = 60           # keep rows newer than this
UA = 'Mozilla/5.0 (compatible; geopolitics-tracker/1.0)'
MRSS = '{http://search.yahoo.com/mrss/}'

# ── RSS sources ───────────────────────────────────────────────────────────── #
# (source_label, feed_url, perspective, source_country, is_fast_lead)
#
# These are the SEED definitions and the offline fallback. The live list comes
# from data/sources.csv via the registry (see load_registry_sources below), so a
# source a user adds on the Tracker page — or deselects — is picked up here
# without editing this file. Keep them in sync when adding a permanent source:
# add the row to data/sources.csv, and mirror it here only if it should survive
# the registry file going missing.
RSS_SOURCES = [
    ('BBC World',   'https://feeds.bbci.co.uk/news/world/rss.xml',        'western-uk',    'GB', False),
    ('DW English',  'https://rss.dw.com/rdf/rss-en-world',                'german',        'DE', False),
    ('Al Jazeera',  'https://www.aljazeera.com/xml/rss/all.xml',          'gulf',          'QA', False),
    ('UN News',     'https://news.un.org/feed/subscribe/en/news/all/rss.xml', 'institutional', 'UN', False),
    ('BNO News',    'https://bnonews.com/index.php/feed/',                'wire-fast',     '',   True),
    # ReliefWeb: RSS feeds now return empty and the v1 API is 410 Gone / v2 is
    # gated behind a registered appname. Re-add once we register a key (put it
    # in .env alongside SPECTATOR_BEARER_TOKEN and add an api adapter).
    # Guardian: needs a free dev key — same pattern, add when the key exists.
]

# A source is "fast lead" (breaking-first, low-context) by perspective rather
# than by a column of its own — the registry stays generic that way.
FAST_LEAD_PERSPECTIVES = {'wire-fast'}

# ── GDELT DOC 2.0 queries ─────────────────────────────────────────────────── #
# (label, query, perspective, source_country). The sourcecountry: filter is what
# gives us the reporting-nation viewpoint. `sourcelang:english` keeps base-tier
# headlines readable (RT/TASS-English, Global Times, Tehran Times still carry
# the domestic framing). Drop `sourcelang:english` for richer domestic-language
# coverage once enrichment can translate — that yields the fullest non-Western
# view but base-tier rows would show untranslated headlines.
# Keep this list small and high-value; GDELT is rate-limited, so queries are
# spaced out (see GDELT_DELAY).
GDELT_DELAY = 6             # seconds between GDELT calls (429s otherwise)
GDELT_MAXRECORDS = 60
GDELT_TIMESPAN = '2d'
GDELT_QUERIES = [
    ('GDELT/RU Ukraine', 'ukraine sourcecountry:RS sourcelang:english', 'russia',  'RU'),
    ('GDELT/CN Taiwan',  'taiwan sourcecountry:CH sourcelang:english',  'chinese', 'CN'),
    ('GDELT/IR MidEast', 'israel sourcecountry:IR sourcelang:english',  'iranian', 'IR'),
]


# ── Registry-driven source list ───────────────────────────────────────────── #

def load_registry_sources():
    """Read the pullable sources out of data/sources.csv.

    Returns (rss, gdelt, ids) where rss/gdelt match the shapes of the hardcoded
    lists above and `ids` maps a source LABEL back to its registry source_id so
    the fetch result can be stamped onto the registry row (last_ok_at /
    last_items — the record that distinguishes "the source is broken" from "the
    source is fine and simply had nothing").

    Falls back to the hardcoded seeds when the registry is missing or has no
    pullable rows, so this script still works standalone.
    """
    try:
        from source_registry import load_sources, USABLE_STATUS
    except ImportError:
        return RSS_SOURCES, GDELT_QUERIES, {}

    rows = load_sources()
    rss, gdelt, ids = [], [], {}
    for r in rows:
        if r.get('status') not in USABLE_STATUS:
            continue          # retired, or a user-typed name we couldn't verify
        label = r.get('name') or r.get('source_id')
        if r.get('kind') == 'rss' and r.get('feed_url'):
            rss.append((label, r['feed_url'], r.get('perspective', ''),
                        r.get('source_country', ''),
                        r.get('perspective') in FAST_LEAD_PERSPECTIVES))
            ids[label] = r['source_id']
        elif r.get('kind') == 'gdelt' and r.get('query'):
            gdelt.append((label, r['query'], r.get('perspective', ''),
                          r.get('source_country', '')))
            ids[label] = r['source_id']

    if not rss and not gdelt:
        return RSS_SOURCES, GDELT_QUERIES, {}
    return (rss or RSS_SOURCES), (gdelt or GDELT_QUERIES), ids


def _now():
    return datetime.now(timezone.utc)


def strip_html(s):
    return re.sub(r'<[^>]+>', '', s or '').strip()


def iso(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def make_id(source, url):
    return hashlib.sha1((source + '|' + (url or '')).encode('utf-8')).hexdigest()[:16]


def fetch(url, timeout=25, retries=2):
    """GET with a couple of retries — public feeds time out intermittently."""
    last = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={'User-Agent': UA})
            with urlopen(req, timeout=timeout) as r:
                return r.read()
        except (URLError, HTTPError) as e:
            last = e
            # Don't retry definite client/server rejections (4xx/5xx).
            if isinstance(e, HTTPError):
                raise
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last


# ── RSS parsing ───────────────────────────────────────────────────────────── #

def _localname(tag):
    return tag.split('}')[-1]


def _child_text(item, name):
    """First child whose local tag name matches, namespace-agnostic. Handles
    RSS 2.0 (`pubDate`), RSS 1.0/RDF (`dc:date`), and Atom alike."""
    for ch in item:
        if _localname(ch.tag) == name and (ch.text or '').strip():
            return ch.text.strip()
    return ''


def _rss_image(item):
    """Best-effort native image URL from an RSS item."""
    thumb = item.find(MRSS + 'thumbnail')
    if thumb is not None and thumb.get('url'):
        return thumb.get('url')
    content = item.find(MRSS + 'content')
    if content is not None and content.get('url') and \
            (content.get('medium') == 'image' or 'image' in (content.get('type') or '')):
        return content.get('url')
    for ch in item:
        if _localname(ch.tag) == 'enclosure' and 'image' in (ch.get('type') or '') and ch.get('url'):
            return ch.get('url')
    m = re.search(r'<img[^>]+src="([^"]+)"', _child_text(item, 'description'))
    return m.group(1) if m else ''


def _rss_date(item):
    raw = _child_text(item, 'pubDate') or _child_text(item, 'date') or ''
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        pass
    # RDF/Atom ISO dates (DW's rss-en uses dc:date like 2026-07-22T05:00:00Z)
    try:
        return datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None


def parse_rss(label, xml_bytes, perspective, source_country, is_fast_lead, cutoff):
    root = ET.fromstring(xml_bytes)
    rows = []
    items = [e for e in root.iter() if _localname(e.tag) == 'item']
    for item in items:
        link = (_child_text(item, 'link') or _child_text(item, 'guid')).strip()
        title = strip_html(_child_text(item, 'title'))
        if not link or not title:
            continue
        dt = _rss_date(item)
        if dt is None:
            dt = _now()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt < cutoff:
            continue
        lede = strip_html(_child_text(item, 'description'))
        if len(lede) > 400:
            lede = lede[:397].rstrip() + '...'
        rows.append({
            'id': make_id(label, link),
            'source': label,
            'source_kind': 'rss',
            'perspective': perspective,
            'pub_date': iso(dt),
            'title': title,
            'lede': lede,
            'url': link,
            'source_country': source_country,
            'image': _rss_image(item),
            'is_fast_lead': 'TRUE' if is_fast_lead else 'FALSE',
        })
    return rows


# ── GDELT parsing ─────────────────────────────────────────────────────────── #

def _gdelt_date(seendate):
    # "20260722T140000Z"
    try:
        return datetime.strptime(seendate, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def fetch_gdelt(label, query, perspective, source_country, cutoff):
    from urllib.parse import quote
    url = (
        'https://api.gdeltproject.org/api/v2/doc/doc'
        f'?query={quote(query)}&mode=ArtList&format=json'
        f'&maxrecords={GDELT_MAXRECORDS}&timespan={GDELT_TIMESPAN}&sort=DateDesc'
    )
    raw = None
    for attempt in range(3):
        try:
            raw = fetch(url)
            break
        except HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(GDELT_DELAY * (attempt + 2))   # 429 → back off harder
                continue
            print(f'  ! {label}: GDELT fetch failed ({e}) — skipped')
            return []
        except URLError as e:
            print(f'  ! {label}: GDELT fetch failed ({e}) — skipped')
            return []
    if raw is None:
        print(f'  ! {label}: GDELT rate-limited after retries — skipped')
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f'  ! {label}: GDELT returned non-JSON — skipped')
        return []
    rows = []
    for a in data.get('articles', []):
        link = (a.get('url') or '').strip()
        title = strip_html(a.get('title') or '')
        if not link or not title:
            continue
        dt = _gdelt_date(a.get('seendate'))
        if dt is None or dt < cutoff:
            continue
        rows.append({
            'id': make_id(label, link),
            'source': f"{a.get('domain', label)} ({perspective})",
            'source_kind': 'gdelt',
            'perspective': perspective,
            'pub_date': iso(dt),
            'title': title,
            'lede': '',
            'url': link,
            'source_country': source_country,
            'image': (a.get('socialimage') or '').strip(),
            'is_fast_lead': 'FALSE',
        })
    return rows


# ── Main ──────────────────────────────────────────────────────────────────── #

def load_existing():
    if not os.path.exists(WIRE_CSV):
        return []
    with open(WIRE_CSV, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def main():
    dry_run = '--dry-run' in sys.argv
    skip_gdelt = '--no-gdelt' in sys.argv

    cutoff = _now() - timedelta(hours=WINDOW_HOURS)
    existing = load_existing()
    existing_ids = {r['id'] for r in existing}

    rss_sources, gdelt_queries, registry_ids = load_registry_sources()

    fetched = []
    per_source = {}
    failed = {}          # label → why we couldn't reach it (a real problem)

    for label, url, perspective, country, fast in rss_sources:
        try:
            rows = parse_rss(label, fetch(url), perspective, country, fast, cutoff)
        except (HTTPError, URLError, ET.ParseError) as e:
            print(f'  ! {label}: {e} — skipped')
            failed[label] = str(e)
            continue
        per_source[label] = len(rows)
        fetched.extend(rows)

    if not skip_gdelt:
        for i, (label, query, perspective, country) in enumerate(gdelt_queries):
            if i:
                time.sleep(GDELT_DELAY)
            rows = fetch_gdelt(label, query, perspective, country, cutoff)
            per_source[label] = len(rows)
            fetched.extend(rows)

    # Dedup: within this fetch (same URL across GDELT queries) and vs the file.
    new_rows = []
    seen = set(existing_ids)
    for r in fetched:
        if r['id'] in seen:
            continue
        seen.add(r['id'])
        new_rows.append(r)

    print('Wire pull:')
    for label in [s[0] for s in rss_sources] + [q[0] for q in gdelt_queries]:
        if label in per_source:
            # 0 in window is NOT a failure — a real outlet with nothing new in
            # the last 60h is the common case, and must read differently from
            # an outlet we couldn't reach at all.
            note = '' if per_source[label] else '   (reached, nothing in window)'
            print(f'  {label:20s} {per_source[label]:3d} in window{note}')
    for label, why in failed.items():
        print(f'  {label:20s}  UNREACHABLE — {why}')
    with_img = sum(1 for r in new_rows if r['image'])
    print(f'New rows: {len(new_rows)} ({with_img} with native image), '
          f'{len(fetched) - len(new_rows)} dupes skipped')

    if dry_run:
        for r in new_rows[:8]:
            print(f"    [{r['perspective']:13s}] {r['pub_date'][:16]}  {r['title'][:64]}")
        print('Dry run — nothing written.')
        return

    # Stamp every source we actually reached (including the ones that answered
    # with nothing) back onto the registry, so the story-tracker routine can
    # tell "no news from this source" apart from "this source is broken".
    if registry_ids:
        try:
            from source_registry import load_sources, record_fetch, save_sources
            reg = load_sources()
            touched = False
            for label, count in per_source.items():
                if label in registry_ids:
                    record_fetch(registry_ids[label], count, reg, persist=False)
                    touched = True
            if touched:
                save_sources(reg)
        except ImportError:
            pass

    if not new_rows:
        print('Nothing new to write.')
        return

    # Merge, drop rows now outside the window, sort ascending, rewrite.
    merged = existing + new_rows
    kept = []
    for r in merged:
        try:
            dt = datetime.fromisoformat(r['pub_date'].replace('Z', '+00:00'))
        except (ValueError, KeyError):
            continue
        if dt >= cutoff:
            kept.append(r)
    kept.sort(key=lambda r: r['pub_date'])

    os.makedirs(os.path.dirname(WIRE_CSV), exist_ok=True)
    tmp = WIRE_CSV + '.tmp'
    with open(tmp, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=WIRE_HEADERS, quoting=csv.QUOTE_ALL,
                           extrasaction='ignore')
        w.writeheader()
        w.writerows(kept)
    os.replace(tmp, WIRE_CSV)

    print(f'Wrote {len(kept)} rows -> {os.path.relpath(WIRE_CSV, ROOT)} '
          f'(+{len(new_rows)} new)')
    if kept:
        print(f'Date range: {kept[0]["pub_date"]} → {kept[-1]["pub_date"]}')


if __name__ == '__main__':
    main()
