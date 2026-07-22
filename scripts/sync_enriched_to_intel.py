#!/usr/bin/env python3
"""
Sync deep-enriched tweets into the canonical intel feed.

Bridges the gap between the two enrichment tracks:
  data/spectator_enriched.csv  (24-col deep enrichment, written by the
                                spectator-deep-enrichment scheduled task)
  data/intel_feed.csv          (18-col canonical feed consumed by
                                build_db.py and the map app)

Deterministic — no API key needed. Idempotent — safe to re-run; rows are
deduplicated on (created_at, full_text).

Usage (from project root):
    python3 scripts/sync_enriched_to_intel.py [--dry-run]
"""

import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENRICHED_CSV = os.path.join(ROOT, 'data', 'spectator_enriched.csv')
INTEL_CSV = os.path.join(ROOT, 'data', 'intel_feed.csv')
OPS_CSV = os.path.join(ROOT, 'data', 'operations.csv')

INTEL_COLUMNS = [
    'created_at', 'full_text',
    'category', 'subcategory', 'countries',
    'sentiment', 'severity', 'is_breaking',
    'lat', 'lng', 'location_confidence',
    'linked_operation', 'linked_incident_ids',
    'entities_people', 'entities_orgs', 'entities_weapons', 'entities_locations',
    'summary', 'images', 'source', 'source_url', 'perspective', 'linked_story_ids',
]

# Conservative keyword → operation linking. Only link when the evidence in
# the tweet text is unambiguous; otherwise leave linked_operation empty.
OPERATION_KEYWORDS = [
    (re.compile(r'\bepic fury\b', re.I), 'Op. Epic Fury'),
    (re.compile(r'\broaring lion\b', re.I), 'Op. Roaring Lion'),
    (re.compile(r'\bmidnight hammer\b', re.I), 'Op. Midnight Hammer'),
    (re.compile(r'\babsolute resolve\b', re.I), 'Op. Absolute Resolve'),
    (re.compile(r'\bsouthern spear\b', re.I), 'Op. Southern Spear'),
    (re.compile(r'\bscorpion strike\b', re.I), 'Task Force Scorpion Strike'),
    (re.compile(r'\bswords of iron\b', re.I), 'Op. Swords of Iron'),
    (re.compile(r'\bnorthern arrows\b', re.I), 'Op. Northern Arrows'),
    (re.compile(r'\bhouthi', re.I), 'Houthi / Proxies'),
    (re.compile(r'iranian (ballistic )?missile.{0,40}(toward|towards|at) israel', re.I),
     'Iran Retaliation'),
    (re.compile(r'\b(scarborough shoal|spratly)\b', re.I), 'China SCS Operations'),
]


def normalize_created_at(value):
    """2026-05-04T04:50:01.000Z → 2026-05-04 04:50:01 (intel_feed format)."""
    value = (value or '').strip()
    value = re.sub(r'\.\d+Z?$', '', value.replace('T', ' ')).rstrip('Z')
    return value[:19]


def dedup_key(created_at, text):
    return (normalize_created_at(created_at), ' '.join((text or '').split()))


def link_operation(row, known_ops):
    haystack = ' '.join([
        row.get('original_text', ''),
        row.get('summary', ''),
        row.get('context', ''),
    ])
    for pattern, op_name in OPERATION_KEYWORDS:
        if op_name in known_ops and pattern.search(haystack):
            return op_name
    return ''


def location_confidence(row):
    if not (row.get('lat') or '').strip():
        return 'none'
    # Deep-enriched coordinates backed by independent sources are trusted;
    # research-estimated ones are marked approximate.
    if row.get('source_count', '0') not in ('', '0') and \
            row.get('confirmation_status') == 'confirmed':
        return 'exact'
    return 'approximate'


def to_intel_row(row, known_ops):
    severity = (row.get('severity') or '').strip()
    if severity not in ('1', '2', '3', '4', '5'):
        severity = '1'
    summary = ' '.join((row.get('summary') or '').split())
    if len(summary) > 140:
        summary = summary[:137] + '...'
    return {
        'created_at': normalize_created_at(row.get('pub_date', '')),
        'full_text': row.get('original_text', ''),
        'category': row.get('category', ''),
        'subcategory': row.get('subcategory', ''),
        'countries': row.get('countries', ''),
        'sentiment': row.get('sentiment', ''),
        'severity': severity,
        'is_breaking': (row.get('is_breaking') or 'FALSE').upper(),
        'lat': row.get('lat', ''),
        'lng': row.get('lng', ''),
        'location_confidence': location_confidence(row),
        'linked_operation': link_operation(row, known_ops),
        'linked_incident_ids': '',
        'entities_people': row.get('entities_people', ''),
        'entities_orgs': row.get('entities_orgs', ''),
        'entities_weapons': row.get('entities_weapons', ''),
        'entities_locations': row.get('entities_locations', ''),
        'summary': summary,
        'images': row.get('images', ''),
        'source': row.get('source', '') or 'spectator',
        'source_url': row.get('source_url', ''),
        'perspective': row.get('perspective', ''),
    }


def main():
    dry_run = '--dry-run' in sys.argv

    if not os.path.exists(ENRICHED_CSV):
        print(f'Nothing to sync: {ENRICHED_CSV} not found.')
        return

    with open(ENRICHED_CSV, newline='', encoding='utf-8') as f:
        enriched = list(csv.DictReader(f))

    with open(INTEL_CSV, newline='', encoding='utf-8') as f:
        existing = list(csv.DictReader(f))
    existing_by_key = {}
    for r in existing:
        existing_by_key.setdefault(dedup_key(r.get('created_at'), r.get('full_text')), r)

    known_ops = set()
    if os.path.exists(OPS_CSV):
        with open(OPS_CSV, newline='', encoding='utf-8') as f:
            known_ops = {r.get('operation_name', '') for r in csv.DictReader(f)}

    # Columns refreshed on upsert. `linked_incident_ids` and `linked_story_ids`
    # are preserved (set by promotion / link_stories.py, not by enrichment) and
    # `full_text`/`created_at` are the key.
    REFRESH_COLS = [c for c in INTEL_COLUMNS
                    if c not in ('created_at', 'full_text',
                                 'linked_incident_ids', 'linked_story_ids')]

    new_rows = []
    updated = 0
    for row in enriched:
        key = dedup_key(row.get('pub_date'), row.get('original_text'))
        candidate = to_intel_row(row, known_ops)
        cur = existing_by_key.get(key)
        if cur is None:
            existing_by_key[key] = candidate
            new_rows.append(candidate)
        else:
            # Refresh in place if the enriched row now carries better data.
            changed = False
            for c in REFRESH_COLS:
                if (cur.get(c) or '') != (candidate.get(c) or ''):
                    cur[c] = candidate.get(c, '')
                    changed = True
            if changed:
                updated += 1

    new_rows.sort(key=lambda r: r['created_at'])

    print(f'Deep-enriched rows:    {len(enriched)}')
    print(f'Already in intel_feed: {len(enriched) - len(new_rows)}')
    print(f'New rows to sync:      {len(new_rows)}')
    print(f'Existing rows updated: {updated}')

    if not new_rows and not updated:
        print('intel_feed.csv is up to date.')
        return
    if dry_run:
        print('Dry run — no changes written.')
        return

    # Rewrite the whole file atomically: existing rows (possibly refreshed) keep
    # their order, new rows are appended in date order.
    all_rows = existing + new_rows
    tmp = INTEL_CSV + '.tmp'
    with open(tmp, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=INTEL_COLUMNS, extrasaction='ignore')
        writer.writeheader()
        for r in all_rows:
            writer.writerow({c: r.get(c, '') for c in INTEL_COLUMNS})
    os.replace(tmp, INTEL_CSV)

    linked = sum(1 for r in new_rows if r['linked_operation'])
    span = (f'Date range: {new_rows[0]["created_at"]} → {new_rows[-1]["created_at"]}'
            if new_rows else '')
    print(f'Wrote intel_feed.csv: +{len(new_rows)} new ({linked} op-linked), '
          f'{updated} updated. {span}')
    print('Next: python3 scripts/build_db.py')


if __name__ == '__main__':
    main()
