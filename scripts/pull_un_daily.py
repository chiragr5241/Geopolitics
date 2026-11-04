#!/usr/bin/env python3
"""
Daily UN reporting — merge the UN's own daily output into data/un_daily/reports.csv.

Two streams, both read through feeds published for automated readers (the
press.un.org HTML pages answer automated clients with 406, so we never fetch
them — only their RSS):

  press — press.un.org "Meetings Coverage and Press Releases" RSS: the official
          record of every Security Council / General Assembly / committee
          meeting, Secretary-General statements and the noon briefing. The
          document symbol in the URL (ga12805, gaspd848, sc16201, sgsm23353,
          db261103 …) says exactly which organ produced it, so classification
          is deterministic. CAVEAT: the feed only carries the latest ~10
          releases, so the archive is only as complete as the pull is frequent
          (so pull more than once a day).
  news  — UN News (news.un.org): the all-news feed plus topic feeds, and the
          UN News rows already ingested into data/intel_feed.csv by the wire
          pipeline (backfills the archive to July 2026 and fills any gap
          between runs).

Each row is classified into a branch of the UN: unga (General Assembly —
plenary + the six Main Committees), sc, sg, rights, field, other. The
`organ` is the specific body. scripts/un_story_updates.py then turns rows into
timeline beats on the United Nations story, routing General Assembly reports
to its UNGA 81 branch story (parent_id).

Idempotent: keyed by `id` (document symbol for press, story id for UN News);
re-runs refresh a row's text but never duplicate it. Nothing is ever dropped —
the archive is kept whole.

Usage (from repo root):
    python3 scripts/pull_un_daily.py            # fetch + merge + write
    python3 scripts/pull_un_daily.py --dry-run  # fetch + report, write nothing
    python3 scripts/pull_un_daily.py --offline  # only re-classify + backfill from intel_feed
"""

import csv
import gzip
import os
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pull_wires import fetch, parse_rss  # noqa: E402  (shared stdlib RSS adapter)
from enrich_lib import extract_countries, now_iso  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'data', 'un_daily')
REPORTS_CSV = os.path.join(OUT_DIR, 'reports.csv')
INTEL_CSV = os.path.join(ROOT, 'data', 'intel_feed.csv')
HEADERS = [
    'id', 'date', 'published', 'stream', 'branch', 'organ', 'kind', 'symbol',
    'title', 'lede', 'url', 'image', 'countries', 'fetched_at',
]

NY = ZoneInfo('America/New_York')   # the UN's own calendar day
EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)

PRESS_FEED = 'https://press.un.org/en/rss.xml'
NEWS_FEEDS = [
    'https://news.un.org/feed/subscribe/en/news/all/rss.xml',
    'https://news.un.org/feed/subscribe/en/news/topic/peace-and-security/feed/rss.xml',
    'https://news.un.org/feed/subscribe/en/news/topic/un-affairs/feed/rss.xml',
    'https://news.un.org/feed/subscribe/en/news/topic/human-rights/feed/rss.xml',
    'https://news.un.org/feed/subscribe/en/news/topic/humanitarian-aid/feed/rss.xml',
]

# press.un.org document prefixes → (branch, organ, kind, symbol prefix).
# Longest prefix wins (gaspd before ga, sgsm before sg).
PRESS_PREFIXES = [
    ('gadis',  'unga',   'First Committee',      'meeting',     'GA/DIS'),
    ('gaef',   'unga',   'Second Committee',     'meeting',     'GA/EF'),
    ('gashc',  'unga',   'Third Committee',      'meeting',     'GA/SHC'),
    ('gaspd',  'unga',   'Fourth Committee',     'meeting',     'GA/SPD'),
    ('gaab',   'unga',   'Fifth Committee',      'meeting',     'GA/AB'),
    ('gal',    'unga',   'Sixth Committee',      'meeting',     'GA/L'),
    ('gapal',  'unga',   'Palestinian Rights Committee', 'meeting', 'GA/PAL'),
    ('ga',     'unga',   'Plenary',              'meeting',     'GA'),
    ('sc',     'sc',     'Security Council',     'meeting',     'SC'),
    ('dsgsm',  'sg',     'Deputy Secretary-General', 'statement', 'DSG/SM'),
    ('sgsm',   'sg',     'Statements & messages', 'statement',  'SG/SM'),
    ('sga',    'sg',     'Appointments',         'appointment', 'SG/A'),
    ('sgt',    'sg',     'Travel & activities',  'release',     'SG/T'),
    ('sg',     'sg',     'Secretary-General',    'release',     'SG'),
    ('db',     'sg',     'Noon briefing',        'briefing',    'DB'),
    ('hr',     'rights', 'Human rights',         'meeting',     'HR'),
    ('iha',    'field',  'Humanitarian',         'release',     'IHA'),
    ('ecosoc', 'other',  'ECOSOC',               'meeting',     'ECOSOC'),
    ('bio',    'other',  'Credentials',          'release',     'BIO'),
    ('obv',    'other',  'Observances',          'release',     'OBV'),
    ('org',    'other',  'Organization',         'release',     'ORG'),
    ('pi',     'other',  'Public information',   'release',     'PI'),
    ('env',    'other',  'Environment',          'release',     'ENV'),
    ('dev',    'other',  'Development',          'release',     'DEV'),
    ('wom',    'other',  'Women',                'release',     'WOM'),
    ('dc',     'other',  'Disarmament Commission', 'meeting',   'DC'),
    ('l',      'other',  'Legal',                'release',     'L'),
]

_DOC_RE = re.compile(r'/en/(\d{4})/([a-z]+)(\d+)\.doc\.htm', re.I)
_BLOG_RE = re.compile(r'/en/blog/([a-z]+)(\d+)', re.I)
_NEWS_RE = re.compile(r'/story/(\d{4})/(\d{2})/(\d+)')

COMMITTEES = ['first committee', 'second committee', 'third committee',
              'fourth committee', 'fifth committee', 'sixth committee']


def _norm_press_url(url):
    # The feed sometimes repeats a release as "…doc.htm-0" — same document.
    return re.sub(r'(\.doc\.htm)-\d+$', r'\1', url.strip())


def classify_press(url, title):
    """(id, symbol, branch, organ, kind) for a press.un.org URL, or None."""
    m = _DOC_RE.search(url)
    blog = False
    if not m:
        m = _BLOG_RE.search(url)
        blog = bool(m)
    if not m:
        return None
    if blog:
        prefix, num = m.group(1).lower(), m.group(2)
    else:
        prefix, num = m.group(2).lower(), m.group(3)
    for p, branch, organ, kind, sym in PRESS_PREFIXES:
        if prefix == p:
            break
    else:
        branch, organ, kind, sym = 'other', 'Press release', 'release', prefix.upper()
    symbol = sym + '/' + num
    low = title.lower()
    if blog:
        kind = 'live'
    elif branch == 'sc' and 'press statement' in low:
        kind = 'statement'
    elif branch == 'sc' and ('adopt' in low or 'resolution' in low or 'veto' in low):
        kind = 'decision'
    elif branch == 'unga' and ('adopt' in low or 'elects' in low):
        kind = 'decision'
    rid = ('press-blog-' if blog else 'press-') + prefix + num
    return rid, symbol, branch, organ, kind


def classify_news(title, lede):
    """Branch + organ for a UN News story, by what it is about.

    The headline decides before the lede does: "Equality 'ends at the doors of
    the Security Council', Ruto tells General Assembly" is a General Debate
    speech, not a Council meeting."""
    def match(s):
        if 'general assembly' in s or 'unga' in s or 'general debate' in s:
            return 'unga', 'Plenary'
        for c in COMMITTEES:
            if c in s:
                return 'unga', c.title()
        if 'security council' in s:
            return 'sc', 'Security Council'
        if ('human rights council' in s or 'rights chief' in s or 'ohchr' in s
                or 'special rapporteur' in s or 'türk' in s or 'rights experts' in s):
            return 'rights', 'Human rights'
        return None
    t = title.lower()
    hit = match(t)
    if hit:
        return hit
    if 'guterres' in t or 'secretary-general' in t:
        return 'sg', 'Secretary-General'
    return match(lede.lower()) or ('field', 'UN News')


def _ny_date(published_iso):
    try:
        dt = datetime.strptime(published_iso, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError:
        return published_iso[:10]
    return dt.astimezone(NY).strftime('%Y-%m-%d')


def _bytes(raw):
    return gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw


def press_rows(fetched_at):
    rows = []
    items = parse_rss('UN Press', _bytes(fetch(PRESS_FEED)), 'institutional', 'UN', False, EPOCH)
    for it in items:
        url = _norm_press_url(it['url'])
        c = classify_press(url, it['title'])
        if not c:
            continue
        rid, symbol, branch, organ, kind = c
        rows.append({
            'id': rid, 'date': _ny_date(it['pub_date']), 'published': it['pub_date'],
            'stream': 'press', 'branch': branch, 'organ': organ, 'kind': kind,
            'symbol': symbol, 'title': it['title'], 'lede': it['lede'], 'url': url,
            'image': it['image'], 'countries': extract_countries(it['title'] + ' ' + it['lede']),
            'fetched_at': fetched_at,
        })
    return rows


def news_row(title, lede, url, published, image, fetched_at):
    m = _NEWS_RE.search(url)
    if not m:
        return None
    branch, organ = classify_news(title, lede)
    return {
        'id': 'news-' + m.group(3), 'date': _ny_date(published), 'published': published,
        'stream': 'news', 'branch': branch, 'organ': organ, 'kind': 'news', 'symbol': '',
        'title': title, 'lede': lede, 'url': url, 'image': image,
        'countries': extract_countries(title + ' ' + lede), 'fetched_at': fetched_at,
    }


def news_rows(fetched_at):
    rows, errors = [], []
    for feed in NEWS_FEEDS:
        try:
            items = parse_rss('UN News', _bytes(fetch(feed)), 'institutional', 'UN', False, EPOCH)
        except Exception as e:  # one dead topic feed must not sink the run
            errors.append(f'{feed}: {e}')
            continue
        for it in items:
            r = news_row(it['title'], it['lede'], it['url'], it['pub_date'], it['image'], fetched_at)
            if r:
                rows.append(r)
    return rows, errors


def intel_backfill(fetched_at):
    """UN News rows the wire pipeline already put in intel_feed.csv."""
    rows = []
    if not os.path.exists(INTEL_CSV):
        return rows
    with open(INTEL_CSV, newline='', encoding='utf-8') as f:
        for x in csv.DictReader(f):
            if x.get('source') != 'UN News':
                continue
            text = x.get('full_text') or ''
            title, _, lede = text.partition(' — ')
            title = title.strip() or (x.get('summary') or '').strip()
            published = (x.get('created_at') or '').replace(' ', 'T')[:19] + 'Z'
            img = (x.get('images') or '').split(';')[0].strip()
            r = news_row(title, lede.strip(), x.get('source_url') or '', published, img, fetched_at)
            if r:
                rows.append(r)
    return rows


def load_existing():
    if not os.path.exists(REPORTS_CSV):
        return {}
    with open(REPORTS_CSV, newline='', encoding='utf-8') as f:
        return {r['id']: r for r in csv.DictReader(f)}


def write(rows):
    os.makedirs(OUT_DIR, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r['published'], r['id']))
    with open(REPORTS_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=HEADERS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in HEADERS})


def main():
    dry = '--dry-run' in sys.argv
    offline = '--offline' in sys.argv
    fetched_at = now_iso()
    existing = load_existing()
    incoming, problems = [], []

    if not offline:
        try:
            p = press_rows(fetched_at)
            incoming += p
            print(f'press.un.org RSS: {len(p)} release(s)')
        except Exception as e:
            problems.append(f'press.un.org RSS UNREACHABLE: {e}')
        n, errs = news_rows(fetched_at)
        incoming += n
        problems += [f'UN News feed UNREACHABLE: {e}' for e in errs]
        print(f'UN News RSS: {len(n)} item(s) across {len(NEWS_FEEDS)} feed(s)')
    # The backfill only fills gaps: a story read from the live feed wins.
    seen = set(existing) | {r['id'] for r in incoming}
    b = [r for r in intel_backfill(fetched_at) if r['id'] not in seen]
    incoming += b
    print(f'intel_feed backfill: {len(b)} UN News row(s) not already archived')

    added = updated = 0
    merged = dict(existing)
    for r in incoming:
        old = merged.get(r['id'])
        if old is None:
            merged[r['id']] = r
            added += 1
            continue
        # Keep first-seen fetch time and the richer text/image; refresh classification.
        r = dict(r, fetched_at=old.get('fetched_at') or r['fetched_at'])
        if len(old.get('lede', '')) > len(r['lede']):
            r['lede'] = old['lede']
        r['image'] = r['image'] or old.get('image', '')
        if any(old.get(k, '') != r[k] for k in HEADERS):
            updated += 1
        merged[r['id']] = r

    if offline:
        # Re-classify everything with the current rules.
        for r in merged.values():
            if r['stream'] == 'press':
                c = classify_press(r['url'], r['title'])
                if c:
                    _, r['symbol'], r['branch'], r['organ'], r['kind'] = c
            else:
                r['branch'], r['organ'] = classify_news(r['title'], r['lede'])

    for msg in problems:
        print(msg)
    print(f'{added} new, {updated} refreshed, {len(merged)} total report(s)')
    if dry:
        print('(dry run — nothing written)')
        return 0
    write(list(merged.values()))
    print(f'wrote {os.path.relpath(REPORTS_CSV, ROOT)}')
    # Unreachable press feed = the official stream is missing today: fail loudly.
    return 1 if any(m.startswith('press.un.org') for m in problems) else 0


if __name__ == '__main__':
    sys.exit(main())
