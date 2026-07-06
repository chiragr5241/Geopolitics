#!/usr/bin/env python3
"""
Promote significant intel_feed events into incidents.csv.

This is the deterministic replacement for what used to be prose-only
Step 6 in the spectator-deep-enrichment scheduled task ("read intel_feed,
find severity>=4 military/nuclear/terrorism rows, group same-event rows,
append one incident per event"). Because that step had no script backing
it, the agent silently skipped it and incidents.csv went 71 days stale
while intel_feed.csv stayed current. This script makes it a real,
idempotent, re-runnable step.

Usage (from project root):
    python3 scripts/promote_incidents.py [--dry-run]
"""

import csv
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTEL_CSV = os.path.join(ROOT, 'data', 'intel_feed.csv')
INCIDENTS_CSV = os.path.join(ROOT, 'data', 'incidents.csv')
ENRICHED_CSV = os.path.join(ROOT, 'data', 'spectator_enriched.csv')

PROMOTE_CATEGORIES = {'military', 'nuclear', 'terrorism'}
MIN_SEVERITY = 4
MAX_PER_RUN = 50

INCIDENT_COLUMNS = [
    'incident_id', 'operation_name', 'incident_title', 'date', 'incident_type',
    'strike_type', 'confirmed', 'origin_lat', 'origin_lng', 'origin_label',
    'origin_sublabel', 'target_lat', 'target_lng', 'target_label',
    'target_sublabel', 'summary', 'target_type', 'platform_or_unit',
    'result_outcome', 'tags', 'source_type', 'is_retaliation', 'is_covert',
    'is_first_use', 'disputed',
]


def parse_dt(value):
    value = (value or '').strip()
    if not value:
        return None
    norm = re.sub(r'\.\d+Z?$', '', value.replace('T', ' ')).rstrip('Z')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%b %d, %Y', '%B %d, %Y', '%B %Y', '%b %Y'):
        try:
            return datetime.strptime(norm[:19].strip() if ' ' in fmt else norm.strip(), fmt)
        except ValueError:
            continue
    return None


def slugify(text):
    text = (text or '').strip().lower()
    text = re.split(r'[;,]', text)[0].strip()
    text = re.sub(r'[^a-z0-9]+', '-', text).strip('-')
    return text or 'unknown'


def sync_dedup_key(created_at, text):
    """Mirrors sync_enriched_to_intel.py's dedup key so we can join back to
    spectator_enriched.csv for richer summary/confirmation data."""
    created_at = (created_at or '').strip()
    created_at = re.sub(r'\.\d+Z?$', '', created_at.replace('T', ' ')).rstrip('Z')[:19]
    return (created_at, ' '.join((text or '').split()))


def map_incident_type(category, subcategory):
    cat = (category or '').lower()
    sub = (subcategory or '').lower()
    if 'sanction' in sub or 'economic' in cat:
        return 'economic'
    if 'ceasefire' in sub or 'diplomat' in sub or 'diplomat' in cat:
        return 'diplomatic'
    if 'humanitarian' in cat:
        return 'humanitarian'
    if 'intel' in cat or 'intelligence' in cat:
        return 'intel'
    return 'strike'


def map_strike_type(subcategory, text):
    s = ((subcategory or '') + ' ' + (text or '')).lower()
    if 'missile' in s or 'ballistic' in s or 'rocket' in s:
        return 'missile'
    if 'drone' in s or 'uav' in s:
        return 'drone'
    if 'naval' in s or 'navy' in s or 'warship' in s or 'destroyer' in s:
        return 'naval'
    if 'bomber' in s or 'b-2' in s or 'b-52' in s:
        return 'bomber'
    if 'fighter' in s or 'jet' in s or 'airstrike' in s or 'air strike' in s:
        return 'fighter'
    if 'artillery' in s or 'shelling' in s:
        return 'artillery'
    return 'strike'


def event_key(row, dt):
    """Groups intel rows describing the same real-world event: same
    calendar day + same primary location (rounded) or, absent
    coordinates, the same country set."""
    day = dt.strftime('%Y-%m-%d')
    lat, lng = (row.get('lat') or '').strip(), (row.get('lng') or '').strip()
    if lat and lng:
        try:
            loc = (round(float(lat) * 2) / 2, round(float(lng) * 2) / 2)
        except ValueError:
            loc = None
    else:
        loc = None
    if loc is None:
        countries = tuple(sorted(c.strip().upper() for c in (row.get('countries') or '').split(';') if c.strip()))
        loc = countries
    return (day, loc)


def richness(row):
    try:
        sev = int((row.get('severity') or '0').strip())
    except ValueError:
        sev = 0
    return (sev, len(row.get('summary') or ''))


def main():
    dry_run = '--dry-run' in sys.argv

    if not os.path.exists(INTEL_CSV):
        print(f'Nothing to promote: {INTEL_CSV} not found.')
        return
    with open(INTEL_CSV, newline='', encoding='utf-8') as f:
        intel_rows = list(csv.DictReader(f))

    with open(INCIDENTS_CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        incident_rows = list(reader)

    existing_ids = {r['incident_id'] for r in incident_rows}
    enriched_latest = [parse_dt(r['date']) for r in incident_rows if r.get('source_type') == 'enriched']
    enriched_latest = [d for d in enriched_latest if d]
    cutoff = max(enriched_latest) if enriched_latest else datetime.min

    enriched_by_key = {}
    if os.path.exists(ENRICHED_CSV):
        with open(ENRICHED_CSV, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                key = sync_dedup_key(r.get('pub_date'), r.get('original_text'))
                enriched_by_key[key] = r

    # 1. Filter qualifying rows newer than the cutoff.
    candidates = []
    for row in intel_rows:
        cat = (row.get('category') or '').lower()
        try:
            sev = int((row.get('severity') or '0').strip())
        except ValueError:
            sev = 0
        if cat not in PROMOTE_CATEGORIES or sev < MIN_SEVERITY:
            continue
        dt = parse_dt(row.get('created_at'))
        if not dt or dt <= cutoff:
            continue
        candidates.append((dt, row))

    candidates.sort(key=lambda pair: pair[0])

    # 2. Group same-event rows.
    groups = {}
    order = []
    for dt, row in candidates:
        key = event_key(row, dt)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((dt, row))

    promoted = 0
    skipped_existing = 0
    new_rows = []
    # IDs created *within this run* — used only to disambiguate two distinct
    # new events that land on the same day+location in the same run.
    new_ids_this_run = set()

    for key in order:
        if promoted >= MAX_PER_RUN:
            break
        members = groups[key]
        dt0 = members[0][0]
        best_dt, best_row = max(members, key=lambda pair: richness(pair[1]))

        day_str = dt0.strftime('%Y%m%d')
        loc_source = best_row.get('entities_locations') or ';'.join(
            sorted(c.strip() for c in (best_row.get('countries') or '').split(';') if c.strip()))
        slug = slugify(loc_source)
        naive_id = f'ma-{day_str}-{slug}'

        # If the plain (unsuffixed) ID already exists from a prior run, this
        # is the same real-world event resurfacing (the day-level cutoff is
        # coarser than intel_feed's per-tweet timestamps) — skip it rather
        # than minting a numbered duplicate, which would break idempotency.
        if naive_id in existing_ids:
            skipped_existing += 1
            continue

        incident_id = naive_id
        suffix = 2
        while incident_id in new_ids_this_run:
            incident_id = f'{naive_id}-{suffix}'
            suffix += 1
        new_ids_this_run.add(incident_id)

        enriched_match = enriched_by_key.get(sync_dedup_key(best_row.get('created_at'), best_row.get('full_text')))
        confirmed = 'TRUE' if enriched_match and enriched_match.get('confirmation_status') == 'confirmed' else 'FALSE'
        summary = (enriched_match.get('summary') if enriched_match else '') or best_row.get('summary') or ''
        summary = ' '.join(summary.split())

        countries = [c.strip().upper() for c in (best_row.get('countries') or '').split(';') if c.strip()]
        category = best_row.get('category', '')
        subcategory = best_row.get('subcategory', '')
        tags = sorted(set(countries + [category.upper()] + ([subcategory.upper()] if subcategory else [])))

        lat, lng = (best_row.get('lat') or '').strip(), (best_row.get('lng') or '').strip()
        target_label = (best_row.get('entities_locations') or '').split(';')[0].strip() or (countries[0] if countries else '')

        new_rows.append({
            'incident_id': incident_id,
            'operation_name': best_row.get('linked_operation', '') or '',
            'incident_title': summary[:120],
            'date': dt0.strftime('%b %d, %Y'),
            'incident_type': map_incident_type(category, subcategory),
            'strike_type': map_strike_type(subcategory, best_row.get('full_text', '')),
            'confirmed': confirmed,
            'origin_lat': '', 'origin_lng': '', 'origin_label': '', 'origin_sublabel': '',
            'target_lat': lat, 'target_lng': lng, 'target_label': target_label, 'target_sublabel': '',
            'summary': summary,
            'target_type': '', 'platform_or_unit': '', 'result_outcome': '',
            'tags': ';'.join(tags),
            'source_type': 'enriched',
            'is_retaliation': 'FALSE', 'is_covert': 'FALSE', 'is_first_use': 'FALSE', 'disputed': 'FALSE',
        })
        promoted += 1

    print(f'Qualifying intel rows newer than cutoff ({cutoff.date() if cutoff != datetime.min else "none"}): {len(candidates)}')
    print(f'Grouped into {len(order)} events')
    print(f'Promoted: {promoted}')
    if skipped_existing:
        print(f'Skipped (incident_id already exists): {skipped_existing}')

    if not new_rows:
        print('incidents.csv is up to date.')
        return
    if dry_run:
        print('Dry run — no changes written.')
        return

    all_rows = incident_rows + new_rows
    with open(INCIDENTS_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(all_rows)

    print(f'Appended {len(new_rows)} incidents to incidents.csv. '
          f'Date range: {new_rows[0]["date"]} -> {new_rows[-1]["date"]}')
    print('Next: python3 scripts/build_db.py')


if __name__ == '__main__':
    main()
