#!/usr/bin/env python3
"""
Pipeline health check — detects enrichment stalls before they become
three-month backlogs.

Checks every stage of the pipeline:
    raw ingest → deep enrichment → intel_feed sync → incidents → database

Exits non-zero if any stage is stale, so scheduled runs surface the failure.

Usage (from project root):
    python3 scripts/enrich_status.py
"""

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda *p: os.path.join(ROOT, 'data', *p)

# Max acceptable lag (days) per stage before it is flagged as STALE.
# 'database build' has no wall-clock threshold: it is checked against the
# data files' freshness instead (see below).
THRESHOLDS = {
    'raw ingest': 2,
    'deep enrichment': 3,
    'intel_feed sync': 3,
}

# incidents.csv is stale if the newest qualifying intel_feed row (the kind
# promote_incidents.py promotes) is more than this many days ahead of the
# latest promoted incident. This used to be unenforced, which is exactly
# how incidents.csv went 71 days stale while every other stage looked "OK".
INCIDENT_PROMOTION_LAG_DAYS = 3
PROMOTE_CATEGORIES = {'military', 'nuclear', 'terrorism'}
PROMOTE_MIN_SEVERITY = 4

# Story tracker is stale if there are active watchlist stories but no
# story_updates row has landed in this many days.
TRACKER_LAG_DAYS = 3

NOW = datetime.now(timezone.utc).replace(tzinfo=None)


def parse_ts(value):
    value = (value or '').strip()
    value = re.sub(r'\.\d+Z?$', '', value.replace('T', ' ')).rstrip('Z')
    formats = ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%B %d, %Y', '%b %d, %Y',
               '%B %Y', '%b %Y')
    for fmt in formats:
        cut = 19 if ' ' in value[:11] and ':' in value else None
        try:
            return datetime.strptime(value[:cut] if cut else value, fmt)
        except ValueError:
            continue
    return None


def load(path, date_col):
    if not os.path.exists(path):
        return None, None
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    dates = [d for d in (parse_ts(r.get(date_col)) for r in rows) if d]
    return rows, (max(dates) if dates else None)


def main():
    problems = []
    lines = []

    def report(stage, detail, latest, extra='', status_override=None):
        lag = (NOW - latest).days if latest else None
        threshold = THRESHOLDS.get(stage)
        if status_override is not None:
            status = status_override
        elif latest is None:
            status = 'MISSING'
        elif threshold is not None and lag > threshold:
            status = f'STALE ({lag}d behind)'
        else:
            status = 'OK'
        if status != 'OK' and status_override is None:
            problems.append(f'{stage}: {status}')
        latest_str = latest.strftime('%Y-%m-%d %H:%M') if latest else '—'
        lines.append(f'  {stage:<18} {status:<18} latest={latest_str}  {detail} {extra}')

    raw, raw_latest = load(D('raw_data', 'spectator_raw.csv'), 'pub_date')
    report('raw ingest', f'{len(raw or [])} tweets', raw_latest)

    deep, deep_latest = load(D('spectator_enriched.csv'), 'pub_date')
    raw_ids = {r['id'] for r in (raw or [])}
    deep_ids = {r['id'] for r in (deep or [])}
    unenriched = len(raw_ids - deep_ids)
    report('deep enrichment', f'{len(deep or [])} rows', deep_latest,
           f'({unenriched} raw tweets unenriched)' if unenriched else '')
    if unenriched > 20:
        problems.append(f'deep enrichment: {unenriched} tweets in backlog')

    intel, intel_latest = load(D('intel_feed.csv'), 'created_at')
    intel_keys = {((r.get('created_at') or '')[:19],
                   ' '.join((r.get('full_text') or '').split()))
                  for r in (intel or [])}
    unsynced = 0
    for r in (deep or []):
        ts = parse_ts(r.get('pub_date'))
        key = (ts.strftime('%Y-%m-%d %H:%M:%S') if ts else '',
               ' '.join((r.get('original_text') or '').split()))
        if key not in intel_keys:
            unsynced += 1
    report('intel_feed sync', f'{len(intel or [])} rows', intel_latest,
           f'({unsynced} deep rows not synced)' if unsynced else '')
    if unsynced > 20:
        problems.append(f'intel_feed sync: {unsynced} rows behind '
                        f'(run scripts/sync_enriched_to_intel.py)')

    incidents, inc_latest = load(D('incidents.csv'), 'date')
    enriched_dates = [parse_ts(r.get('date')) for r in (incidents or [])
                       if r.get('source_type') == 'enriched']
    enriched_dates = [d for d in enriched_dates if d]
    promoted_latest = max(enriched_dates) if enriched_dates else None

    qualifying = [r for r in (intel or [])
                  if (r.get('category') or '').lower() in PROMOTE_CATEGORIES
                  and (int(r.get('severity')) if (r.get('severity') or '').isdigit() else 0) >= PROMOTE_MIN_SEVERITY]
    qualifying_dates = [parse_ts(r.get('created_at')) for r in qualifying]
    qualifying_dates = [d for d in qualifying_dates if d]
    qualifying_latest = max(qualifying_dates) if qualifying_dates else None

    promotion_lag = None
    if qualifying_latest and (promoted_latest is None or qualifying_latest > promoted_latest):
        promoted_or_epoch = promoted_latest or datetime(2000, 1, 1)
        promotion_lag = (qualifying_latest - promoted_or_epoch).days
    promo_status = 'OK'
    if promotion_lag is not None and promotion_lag > INCIDENT_PROMOTION_LAG_DAYS:
        promo_status = f'STALE ({promotion_lag}d behind)'
        problems.append(f'incidents: promotion lag {promotion_lag}d '
                         f'(run scripts/promote_incidents.py)')
    report('incidents', f'{len(incidents or [])} rows', inc_latest, status_override=promo_status)

    watchlist_path = D('watchlist.json')
    if os.path.exists(watchlist_path):
        with open(watchlist_path, encoding='utf-8') as f:
            watchlist = json.load(f)
        active = [s for s in watchlist.get('stories', []) if s.get('status') == 'active']
        updates, updates_latest = load(D('story_updates.csv'), 'found_at')
        lag = (NOW - updates_latest).days if updates_latest else None
        status = 'OK'
        if active and (updates_latest is None or lag > TRACKER_LAG_DAYS):
            status = f'STALE ({lag if lag is not None else "no updates"}d behind)'
            problems.append('story tracker: no updates for active stories '
                             '(run scripts/update_stories.py)')
        report('story tracker', f'{len(active)} active / {len(watchlist.get("stories", []))} total',
               updates_latest, status_override=status)

    db_path = D('database.json')
    db_latest = None
    db_detail = 'missing'
    if os.path.exists(db_path):
        db_latest = datetime.utcfromtimestamp(os.path.getmtime(db_path))
        try:
            with open(db_path, encoding='utf-8') as f:
                db = json.load(f)
            meta = db.get('_meta', {})
            db_detail = (f"v{meta.get('version', '?')}, "
                         f"{len(db.get('tweets', []))} tweets, "
                         f"{len(db.get('incidents', []))} incidents")
        except (json.JSONDecodeError, OSError):
            db_detail = 'unreadable'
    # database is stale if intel_feed has newer data than the last build
    if db_latest and intel_latest and intel_latest > db_latest:
        problems.append('database build: intel_feed.csv is newer than '
                        'database.json (run scripts/build_db.py)')
    report('database build', db_detail, db_latest)

    print('Enrichment pipeline status')
    print('\n'.join(lines))
    print()
    if problems:
        print('PROBLEMS:')
        for p in problems:
            print(f'  - {p}')
        sys.exit(1)
    print('All stages healthy.')


if __name__ == '__main__':
    main()
