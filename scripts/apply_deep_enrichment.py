#!/usr/bin/env python3
"""
Apply agent-produced DEEP enrichment records, upserting by tweet id.

The scheduled task deep-researches the batch from select_deep_batch.py and
pipes the resulting records here as a JSON array (or one object) on stdin. Each
record replaces the matching base row in data/spectator_enriched.csv and flips
its tier to `deep`. This is the ONLY sanctioned way to write deep rows — never
hand-edit the CSV.

Idempotent and order-independent: re-applying the same record is a no-op beyond
refreshing fields; unknown ids are reported and skipped (deep enrichment must
upgrade an existing base row, not invent one).

Fields accepted (missing ones fall back to the existing base value):
    id (required), category, subcategory, countries, entities_people,
    entities_orgs, entities_weapons, entities_locations, lat, lng, sentiment,
    severity, is_breaking, summary, context, implications, confirmation_status,
    source_count, sources_json, images

Usage (from project root):
    python3 scripts/select_deep_batch.py 8 > batch.json
    ... research each ...
    cat deep_records.json | python3 scripts/apply_deep_enrichment.py
"""

import json
import sys

from enrich_lib import ENRICHED_COLUMNS, now_iso, load_enriched, write_enriched

# Fields the agent may set; everything else on the row is preserved.
UPDATABLE = [c for c in ENRICHED_COLUMNS if c not in ('id', 'tweet_id', 'pub_date',
                                                      'original_text', 'tier')]


def main():
    payload = sys.stdin.read().strip()
    if not payload:
        print('apply_deep_enrichment: no input on stdin', file=sys.stderr)
        sys.exit(2)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        print(f'apply_deep_enrichment: invalid JSON: {e}', file=sys.stderr)
        sys.exit(2)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        print('apply_deep_enrichment: expected a JSON object or array', file=sys.stderr)
        sys.exit(2)

    rows, by_id = load_enriched()
    applied, skipped = 0, []

    for rec in data:
        rid = str(rec.get('id', '')).strip()
        if not rid:
            skipped.append('(record with no id)')
            continue
        row = by_id.get(rid)
        if row is None:
            skipped.append(rid)
            continue
        for field in UPDATABLE:
            if field in rec and rec[field] is not None:
                val = rec[field]
                if field == 'sources_json' and not isinstance(val, str):
                    val = json.dumps(val, ensure_ascii=False)
                row[field] = str(val) if not isinstance(val, str) else val
        row['tier'] = 'deep'
        row['enriched_at'] = now_iso()
        applied += 1

    if applied:
        write_enriched(rows)
    print(f'apply_deep_enrichment: upgraded {applied} rows to tier=deep')
    if skipped:
        print(f'  skipped {len(skipped)} unknown/invalid ids: '
              f'{", ".join(skipped[:8])}{" ..." if len(skipped) > 8 else ""}',
              file=sys.stderr)


if __name__ == '__main__':
    main()
