#!/usr/bin/env python3
"""
Tier 1 (base) enrichment — deterministic, no network, ALWAYS run.

For every raw tweet not yet in data/spectator_enriched.csv, append a base-tier
row with keyword-derived category / countries / severity (see enrich_lib.py).
This guarantees the raw->enriched delta returns to ~0 on every run, so the
ingestion backlog that used to spiral for days can no longer accumulate.

Also performs a one-time migration: if the enriched CSV predates the `tier`
column, existing rows are rewritten with tier='deep' (they were all
agent-researched historically).

Idempotent: re-running never duplicates or overwrites existing rows.

Usage (from project root):
    python3 scripts/base_enrich.py            # write base rows
    python3 scripts/base_enrich.py --preview  # report counts, write nothing
"""

import sys

from enrich_lib import base_record, is_noise, load_enriched, load_raw, write_enriched


def main():
    preview = '--preview' in sys.argv

    raw = load_raw()
    rows, by_id = load_enriched()
    existing_ids = set(by_id)

    missing = [r for r in raw if r.get('id') and r.get('id') not in existing_ids]
    # Oldest first, so partial writes are chronologically coherent.
    missing.sort(key=lambda r: r.get('pub_date', ''))

    new_rows = [base_record(r) for r in missing]
    noise_n = sum(1 for r in missing if is_noise(r.get('text', '')))

    # Detect the one-time tier migration (any legacy row already present but the
    # file had no explicit tier -> load_enriched already filled 'deep'; writing
    # back persists the new column).
    needs_migration = bool(rows) and 'tier' not in _header_of_file()

    print(f'base enrichment: {len(raw)} raw, {len(existing_ids)} already enriched, '
          f'{len(missing)} new ({noise_n} noise-filtered)')
    if needs_migration:
        print('  + migrating existing rows to add `tier` column (legacy -> deep)')

    if preview:
        for r in new_rows[:10]:
            print(f"    {r['pub_date'][:16]}  sev{r['severity']} {r['category']:11s} "
                  f"{r['subcategory']:14s} {r['summary'][:60]}")
        if len(new_rows) > 10:
            print(f'    ... and {len(new_rows) - 10} more')
        return

    if not new_rows and not needs_migration:
        print('  nothing to do')
        return

    write_enriched(rows + new_rows)
    print(f'  wrote {len(new_rows)} base rows -> data/spectator_enriched.csv')


def _header_of_file():
    """Return the raw header line's column names, or [] if the file is absent."""
    import csv
    import os
    from enrich_lib import ENRICHED_CSV
    if not os.path.exists(ENRICHED_CSV):
        return []
    with open(ENRICHED_CSV, newline='', encoding='utf-8') as f:
        try:
            return next(csv.reader(f))
        except StopIteration:
            return []


if __name__ == '__main__':
    main()
