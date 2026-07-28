#!/usr/bin/env python3
"""
Backfill data/story_updates.csv with distinct chronological "beats" for the
auto-tracked stories, pulled from data/intel_feed.csv.

The intel feed is huge and full of near-identical rows (dozens of "explosions
heard in X" tweets a day), so we can't just dump every matching headline onto a
timeline. For each managed story we:
  1. filter the feed by keyword / country rules,
  2. drop near-duplicate headlines,
  3. keep the most significant beats (severity + breaking), capped per story,
  4. re-sort chronologically and emit story_updates rows.

Only the story_ids in STORIES below are regenerated; any other rows already in
story_updates.csv (e.g. the hand-curated Iran / World Cup / Ukraine-corruption
timelines) are preserved untouched.

Usage (from project root):
  python scripts/backfill_story_updates.py            # write rows
  python scripts/backfill_story_updates.py --preview  # print, don't write
"""

import csv
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data')
FEED_PATH = os.path.join(DATA_DIR, 'intel_feed.csv')
OUT_PATH = os.path.join(DATA_DIR, 'story_updates.csv')

# Must stay in step with add_story_update.STORY_UPDATE_COLUMNS — this script
# rewrites the whole file, so a column missing here is a column deleted from
# every existing row. (`image` and `source_id` were both added after this
# one-shot backfill was written.)
OUT_COLS = [
    'story_id', 'update_id', 'date', 'headline', 'summary',
    'source_name', 'url', 'status', 'severity', 'origin', 'found_at',
    'image', 'source_id',
]

CAP_PER_STORY = 32
PER_MONTH = 3
FOREIGN_CODES = {
    'UA', 'RU', 'VE', 'IR', 'IL', 'CN', 'TW', 'DE', 'FR', 'TR',
    'SY', 'LB', 'PS', 'YE', 'IN', 'PK', 'SA', 'AE', 'QA', 'JP', 'KR', 'GB', 'AU',
}


# ── Per-story matching rules ───────────────────────────────────────────────────
# match(row) -> bool decides membership; the harness then dedupes + caps.

def countries_of(row):
    return {c.strip() for c in (row.get('countries') or '').split(';') if c.strip()}


def text_of(row):
    return ((row.get('full_text') or '') + ' ' + (row.get('summary') or '')).lower()


def has_any(text, words):
    return any(w in text for w in words)


# Spectator posts a lot of "ranking list" stat tweets (e.g. "Oil reserves 🇻🇪
# Venezuela: 303.8 🇸🇦 Saudi Arabia: 258.6 ...") that match on a country but
# carry no event value. Detect them by a pile-up of flag emoji or "Label: num"
# pairs and keep them out of every story timeline.
_FLAG_RE = re.compile(r'[\U0001F1E6-\U0001F1FF]')
_STAT_RE = re.compile(r':\s*[\$€£]?\d')


def is_noise(row):
    raw = (row.get('full_text') or '') + ' ' + (row.get('summary') or '')
    if len(_FLAG_RE.findall(raw)) >= 6:       # 3+ country flags → listicle
        return True
    if len(_STAT_RE.findall(raw)) >= 3:       # 3+ "Label: number" pairs
        return True
    return False


VEN_KW = [
    'venezuela', 'venezuelan', 'maduro', 'caracas', 'guyana', 'essequibo',
    'pdvsa', 'tren de aragua', 'cartel de los soles', 'guaido', 'guaid',
]

WAR_KW = [
    'kharkiv', 'pokrovsk', 'avdiivka', 'bakhmut', 'kherson', 'zaporizhzhia',
    'kramatorsk', 'sloviansk', 'kupiansk', 'kursk', 'belgorod', 'donetsk',
    'donbas', 'luhansk', 'sumy', 'kremlin', 'putin',
    'russian forces', 'russian troops', 'russian army', 'russian missile',
    'russian drone', 'russian strike', 'russian shelling', 'russian offensive',
    'ukrainian forces', 'ukrainian army', 'ukrainian drone',
    'shahed', 'front line', 'frontline', 'invasion of ukraine',
]
WAR_EXCLUDE = [
    'yermak', 'nabu', 'sapo', 'energoatom', 'mindich', 'operation midas',
    'anti-corruption', 'kickback', 'money laundering', 'chernyshov', 'halushchenko',
    'supreme leader', 'khamenei', 'gaza board', 'israel-iran', 'israel iran',
    'iran-israel', 'iran conflict',
]

VEN_EXCLUDE = [
    'earthquake', 'tsunami', 'magnitude', 'richter', 'aftershock', 'death toll',
    'usgs',
]

MID_EXCLUDE = [
    'flights cancelled', 'flight delays', 'flights have been cancelled',
    'flight cancellations', 'faa to reduce', 'youngest self-made', 'taylor swift',
    'flights delayed',
]

MID_KW = [
    'midterm', 'government shutdown', 'house speaker', 'speaker of the house',
    'senate majority', 'house majority', 'winning the us house',
    'winning the us senate', 'win the us house', 'win the us senate',
    'us house of representatives', 'redistricting', 'gerrymander', 'filibuster',
    'congressional', 'approval rating', 'democratic primary', 'republican primary',
    'gop primary', 'gubernatorial', 'senate race', 'house race',
    'impeachment', 're-elected house',
]


def match_venezuela(row):
    if is_noise(row):
        return False
    t = text_of(row)
    if has_any(t, VEN_EXCLUDE):
        return False
    return 'VE' in countries_of(row) or has_any(t, VEN_KW)


def match_war(row):
    if is_noise(row):
        return False
    t = text_of(row)
    if has_any(t, WAR_EXCLUDE):
        return False
    cc = countries_of(row)
    if 'RU' in cc and 'UA' in cc:
        return True
    return has_any(t, WAR_KW)


def match_midterms(row):
    if is_noise(row):
        return False
    t = text_of(row)
    if has_any(t, MID_EXCLUDE):
        return False
    if not has_any(t, MID_KW):
        return False
    cc = countries_of(row)
    # US-domestic only: allow US-tagged or untagged rows, reject rows that are
    # really about a foreign country's politics that happen to share a keyword.
    foreign = cc & FOREIGN_CODES
    if foreign and 'US' not in cc:
        return False
    return True


STORIES = [
    {'story_id': 'st-20260115-venezuela-us', 'match': match_venezuela, 'floor': '2024-09-01'},
    {'story_id': 'st-20260101-russia-ukraine-war', 'match': match_war, 'floor': '2025-01-01'},
    {'story_id': 'st-20260101-us-midterms-2026', 'match': match_midterms, 'floor': '2025-01-01'},
]


# ── Beat extraction ────────────────────────────────────────────────────────────

def norm(text):
    text = (text or '').lower()
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[^a-z0-9 ]+', ' ', text)
    return ' '.join(text.split())


def dedupe_key(row):
    """Collapse near-identical headlines: normalized text prefix + date."""
    base = norm(row.get('summary') or row.get('full_text'))
    return (row.get('created_at', '')[:10], base[:60])


def severity_int(row):
    try:
        return int(row.get('severity') or 0)
    except ValueError:
        return 0


def select_beats(rows):
    # 1) drop near-duplicates
    seen = set()
    uniq = []
    for r in rows:
        k = dedupe_key(r)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)

    # 2) bucket by month and keep the most significant few per month, so the
    #    timeline covers the whole arc instead of collapsing onto whichever
    #    weeks had the highest-severity spikes (e.g. a shutdown or an
    #    earthquake) and dropping on-topic but lower-severity electoral beats.
    def sig(r):
        return (severity_int(r), 1 if (r.get('is_breaking') == 'TRUE') else 0)

    buckets = {}
    for r in uniq:
        month = (r.get('created_at') or '')[:7]
        buckets.setdefault(month, []).append(r)

    picked = []
    for month, rs in buckets.items():
        rs.sort(key=lambda r: (sig(r), r.get('created_at', '')), reverse=True)
        picked.extend(rs[:PER_MONTH])

    # 3) if still over budget, drop the least significant across all months
    if len(picked) > CAP_PER_STORY:
        picked.sort(key=lambda r: (sig(r), r.get('created_at', '')), reverse=True)
        picked = picked[:CAP_PER_STORY]

    # 4) chronological order for display
    picked.sort(key=lambda r: r.get('created_at', ''))
    return picked


def make_rows(story_id, beats, now_iso):
    out = []
    for i, r in enumerate(beats, 1):
        # Prefer the complete full_text as the headline; the feed's short
        # "summary" is usually just a clipped prefix, which looks like a
        # truncated-then-repeated line when shown as headline + summary.
        full = ' '.join((r.get('full_text') or '').split())
        short = ' '.join((r.get('summary') or '').split())
        headline = full or short
        summary = ''
        sev = severity_int(r)
        status = 'confirmed' if sev >= 4 else 'developing'
        out.append({
            'story_id': story_id,
            'update_id': f'{story_id}-u{i:03d}',
            'date': (r.get('created_at') or '')[:10],
            'headline': headline[:220],
            'summary': summary[:400],
            'source_name': 'Spectator Index',
            'url': '',
            'status': status,
            'severity': str(sev) if sev else '',
            'origin': 'intel_feed',
            'found_at': now_iso,
        })
    return out


# ── Main ───────────────────────────────────────────────────────────────────────

def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def main():
    preview = '--preview' in sys.argv
    feed = read_csv(FEED_PATH)
    print(f'Loaded {len(feed)} intel feed rows.')

    now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    managed_ids = {s['story_id'] for s in STORIES}

    generated = []
    for spec in STORIES:
        floor = spec.get('floor', '')
        rows = [r for r in feed
                if (r.get('created_at') or '')[:10] >= floor and spec['match'](r)]
        beats = select_beats(rows)
        story_rows = make_rows(spec['story_id'], beats, now_iso)
        generated.extend(story_rows)
        print(f"\n{spec['story_id']}: {len(rows)} matched -> {len(beats)} beats")
        for r in story_rows:
            print(f"  {r['date']}  [{r['severity'] or '-'}] {r['headline'][:88]}")

    if preview:
        print('\n(preview only — nothing written)')
        return

    # Preserve any existing rows that we don't manage (hand-curated timelines).
    existing = read_csv(OUT_PATH)
    kept = [r for r in existing if r.get('story_id') not in managed_ids]

    with open(OUT_PATH, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in kept:
            w.writerow({k: r.get(k, '') for k in OUT_COLS})
        for r in generated:
            w.writerow(r)

    print(f'\nWrote {OUT_PATH}: {len(kept)} preserved + {len(generated)} generated '
          f'= {len(kept) + len(generated)} rows.')


if __name__ == '__main__':
    main()
