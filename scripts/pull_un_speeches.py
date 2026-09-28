#!/usr/bin/env python3
"""
UN General Debate speeches: list, then transcribe, every delegation's address.

Source is the official United Nations YouTube channel, which uploads one video
per delegation titled like

  🇮🇳 India - Minister for External Affairs Addresses UN General Debate, 81st Session | #UNGA
  🇺🇳 India, Pakistan - Right of Replies (25 Sep) - United Nations General Debate, 81st Session

The leading flag emoji IS the country code (two regional-indicator letters →
ISO-2), so no name tables are needed. 🇺🇳 marks UN officials and the
right-of-reply sessions. Those reply sessions are kept (kind=reply): they are
nations rebutting each other by name, the strongest hostility signal the
debate produces.

The UN uploads carry the English interpretation track, so every transcript is
English regardless of the language spoken at the podium.

Usage (from project root):
  python3 scripts/pull_un_speeches.py                # list + fetch missing transcripts
  python3 scripts/pull_un_speeches.py --session 81 --scan 900
  python3 scripts/pull_un_speeches.py --list-only    # refresh the index, no transcripts
  python3 scripts/pull_un_speeches.py --dates        # backfill upload dates (slow, 1 call/video)

Writes:
  data/un_speeches/unga<N>/speeches.csv           index, one row per video
  data/un_speeches/unga<N>/transcripts/<id>.txt   English transcript

Summaries / concerns / mentions are NOT produced here. They are written by
the agent via scripts/add_un_summaries.py and combined by scripts/analyze_un_speeches.py.
"""

import argparse
import csv
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANNEL_URL = 'https://www.youtube.com/@unitednations/videos'

# Fetched first, so a short window between YouTube rate-limit blocks lands the
# speeches that matter most to the analysis: the P5 and G20, the parties to
# this year's wars, and every right-of-reply session.
PRIORITY = ['US', 'CN', 'RU', 'GB', 'FR', 'IN', 'PK', 'IR', 'IL', 'PS', 'UA', 'SA', 'TR',
            'DE', 'JP', 'KR', 'ZA', 'EG', 'QA', 'AE', 'ID', 'MX', 'CA', 'IT', 'EU', 'VE',
            'CU', 'KP', 'SY', 'LB', 'IQ', 'AF', 'SD', 'NG', 'ET', 'KE', 'AU', 'AR', 'BR']

COLUMNS = ['video_id', 'kind', 'iso2', 'country', 'speaker_role', 'title',
           'url', 'published', 'transcript_status', 'words', 'fetched_at']


def session_dir(session):
    return os.path.join(ROOT, 'data', 'un_speeches', f'unga{session}')


def flag_to_iso(title):
    """First two regional-indicator symbols → ISO-2 ('🇮🇳' → 'IN')."""
    letters = [chr(ord(c) - 0x1F1E6 + ord('A')) for c in title[:4]
               if 0x1F1E6 <= ord(c) <= 0x1F1FF]
    return ''.join(letters[:2]) if len(letters) >= 2 else ''


# The channel occasionally reuses a neighbour's flag (UNGA 81 posted Mauritius
# under 🇲🇷 Mauritania). Keyed by the title's country name, which is reliable.
FLAG_FIXES = {'Mauritius': 'MU'}

_ADDR_RE = re.compile(r'^\W*(?P<country>.+?)\s+-\s+(?P<role>.+?)\s+Addresses\b', re.I)
_REPLY_RE = re.compile(r'^\W*(?P<countries>.+?)\s+-\s+(?:First\s+|Second\s+)?Right of Repl', re.I)


def parse_title(vid, title):
    """→ row dict, or None for ceremonial / unrelated clips."""
    iso = flag_to_iso(title)
    row = {c: '' for c in COLUMNS}
    row.update(video_id=vid, title=title.strip(),
               url=f'https://www.youtube.com/watch?v={vid}')
    m = _REPLY_RE.match(title)
    if m:
        # "India, Pakistan - Right of Replies" (🇺🇳 flag) or
        # "🇦🇷 Argentina - First Right of Reply" (own flag).
        row.update(kind='reply', country=m.group('countries').strip(),
                   iso2='' if iso == 'UN' else iso)
        return row
    m = _ADDR_RE.match(title)
    if not m:
        return None
    country = m.group('country').strip()
    kind = 'address'
    if iso == 'UN':
        kind = 'un_official'       # Secretary-General, PGA
    iso = FLAG_FIXES.get(country, iso)
    row.update(kind=kind, iso2=iso, country=country,
               speaker_role=m.group('role').strip())
    return row


def list_channel(scan):
    out = subprocess.run(
        ['yt-dlp', '--flat-playlist', '--playlist-end', str(scan),
         '--print', '%(id)s\t%(title)s', CHANNEL_URL],
        capture_output=True, text=True)
    if out.returncode != 0 and not out.stdout:
        sys.exit('error: yt-dlp listing failed:\n' + out.stderr[-800:])
    for line in out.stdout.splitlines():
        if '\t' in line:
            yield line.split('\t', 1)


def load_index(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return {r['video_id']: r for r in csv.DictReader(f)}


def write_index(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    order = {'address': 0, 'un_official': 1, 'reply': 2}
    rows = sorted(rows, key=lambda r: (order.get(r['kind'], 9), r['country']))
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, '') for c in COLUMNS})


def fetch_transcript(api, vid):
    """English track (manual > auto); else translate whatever exists to English."""
    try:
        fetched = api.fetch(vid, languages=['en'])
    except Exception as exc:
        if exc.__class__.__name__ != 'NoTranscriptFound':
            raise
        first = next(iter(api.list(vid)))
        fetched = first.translate('en').fetch() if first.is_translatable else first.fetch()
    text = ' '.join(s.text.replace('\n', ' ').strip() for s in fetched)
    return re.sub(r'\s+', ' ', text).strip()


def backfill_dates(rows, sdir):
    todo = [r for r in rows if not r['published']]
    if not todo:
        return
    print(f'Fetching upload dates for {len(todo)} videos...', file=sys.stderr)
    out = subprocess.run(
        ['yt-dlp', '--skip-download', '--ignore-errors', '--print', '%(id)s\t%(upload_date)s']
        + [r['url'] for r in todo], capture_output=True, text=True)
    got = dict(l.split('\t', 1) for l in out.stdout.splitlines() if '\t' in l)
    for r in todo:
        d = got.get(r['video_id'], '')
        if re.fullmatch(r'\d{8}', d):
            r['published'] = f'{d[:4]}-{d[4:6]}-{d[6:]}'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--session', type=int, default=81)
    ap.add_argument('--scan', type=int, default=900, help='how many recent channel uploads to scan')
    ap.add_argument('--list-only', action='store_true')
    ap.add_argument('--dates', action='store_true', help='backfill upload dates via yt-dlp')
    ap.add_argument('--sleep', type=float, default=1.5, help='pause between transcript fetches')
    args = ap.parse_args()

    sdir = session_dir(args.session)
    index_path = os.path.join(sdir, 'speeches.csv')
    tdir = os.path.join(sdir, 'transcripts')
    os.makedirs(tdir, exist_ok=True)
    index = load_index(index_path)

    marker = f'{args.session}st Session' if args.session % 10 == 1 else f'{args.session}th Session'
    new = 0
    for vid, title in list_channel(args.scan):
        if marker.lower() not in title.lower() or vid in index:
            continue
        row = parse_title(vid, title)
        if row:
            index[vid] = row
            new += 1
    print(f'Index: {len(index)} videos ({new} new)', file=sys.stderr)

    rows = list(index.values())
    if not args.list_only:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        def urgency(r):
            if r['kind'] == 'reply':
                return -1
            return PRIORITY.index(r['iso2']) if r['iso2'] in PRIORITY else len(PRIORITY)
        for r in sorted(rows, key=urgency):
            if r['video_id'].startswith('press-'):
                continue   # UN press-coverage-only nation: no video to transcribe
            path = os.path.join(tdir, f"{r['video_id']}.txt")
            if os.path.exists(path):
                if not r.get('words'):
                    with open(path, encoding='utf-8') as f:
                        r['words'] = str(len(f.read().split()))
                    r['transcript_status'] = 'ok'
                continue
            try:
                text = fetch_transcript(api, r['video_id'])
            except Exception as exc:
                r['transcript_status'] = 'error:' + exc.__class__.__name__
                print(f"  {r['video_id']} {r['country']}: {r['transcript_status']}", file=sys.stderr)
                if exc.__class__.__name__ in ('IpBlocked', 'RequestBlocked'):
                    print('YouTube is blocking requests — stopping; re-run later.', file=sys.stderr)
                    break
                continue
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text + '\n')
            r.update(transcript_status='ok', words=str(len(text.split())),
                     fetched_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
            print(f"  {r['video_id']} {r['country']}: {r['words']} words", file=sys.stderr)
            write_index(index_path, rows)   # checkpoint — a block mid-run keeps progress
            time.sleep(args.sleep)

    if args.dates:
        backfill_dates(rows, sdir)
    write_index(index_path, rows)
    ok = sum(1 for r in rows if r.get('transcript_status') == 'ok')
    print(f'Done: {ok}/{len(rows)} transcripts on disk → {os.path.relpath(index_path, ROOT)}',
          file=sys.stderr)


if __name__ == '__main__':
    main()
