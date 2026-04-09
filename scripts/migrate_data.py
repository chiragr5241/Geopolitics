#!/usr/bin/env python3
"""
One-time migration: reorganize data/ from 11 CSVs into 5 clean CSVs.

Usage (from project root):
    python scripts/migrate_data.py

Reads:  data/incidents.csv (old, 46-col curated)
        data/enriched_actions.csv (46-col enriched)
        data/spectator_tweets_classified.csv
        data/tweet_enriched.csv
        data/operations.csv (untouched)
        data/imagery.csv (untouched)

Writes: data/incidents.csv (new, 24-col merged)
        data/incident_details.csv (new, 19-col overflow)
        data/intel_feed.csv (new, 17-col unified tweets)
        data/archive/  (old files moved here)
"""

import csv
import os
import re
import shutil
from datetime import datetime

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data')
ARCHIVE  = os.path.join(DATA_DIR, 'archive')


# ── Helpers ──────────────────────────────────────────────────────────────────

def read_csv(path):
    if not os.path.exists(path):
        print(f"  SKIP (not found): {path}")
        return []
    with open(path, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            if row.get(reader.fieldnames[0]) == reader.fieldnames[0]:
                continue  # skip duplicate header rows
            rows.append(dict(row))
    print(f"  Read {len(rows)} rows from {os.path.basename(path)}")
    return rows


def write_csv(path, fieldnames, rows):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore',
                           quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)
    print(f"  Wrote {len(rows)} rows to {os.path.basename(path)}")


# ── Incident type classification ─────────────────────────────────────────────

DIPLOMATIC_RE = re.compile(
    r'(?:ceasefire|peace talk|negotiat|diplomat|sanction|treaty|agreement|'
    r'condemn|warn|urge|call[sed]* (?:for|on)|statement|summit|'
    r'foreign (?:minister|secretary)|ambassador|UN |G7 |NATO |EU |'
    r'announce[sd]* .*(?:aid|assistance|package)|billion.*aid|'
    r'military aid|security assistance|approve[sd]* transfer)',
    re.IGNORECASE
)

ECONOMIC_RE = re.compile(
    r'(?:stock|market|crude|oil|gold|GDP|inflation|recession|economic|'
    r'trade|tariff|brent|barrel|percent|%.*(?:fall|rise|drop|gain)|'
    r'billion.*(?:dollar|USD)|trillion|Wall Street|S&P|Dow|Nasdaq|'
    r'supply chain|shipping|commodity|price)',
    re.IGNORECASE
)

HUMANITARIAN_RE = re.compile(
    r'(?:civilian[s]? (?:killed|dead|wounded|injured|displaced)|'
    r'humanitarian|refugee|evacuat|famine|siege|blockade|'
    r'hospital.*(?:hit|struck|destroy)|school.*(?:hit|struck)|'
    r'casualt(?:y|ies)|death toll|missing person)',
    re.IGNORECASE
)

INTEL_RE = re.compile(
    r'(?:intelligence|espionage|surveillance|cyber|hack|intercept|'
    r'covert|classified|spy|defect|mole)',
    re.IGNORECASE
)

# Patterns that indicate this is NOT an actual incident/event — pure commentary
NOISE_RE = re.compile(
    r'^(?:OPINION|ANALYSIS|EDITORIAL|COMMENTARY|REVIEW)',
    re.IGNORECASE
)

STRIKE_TYPES = {
    'bomber', 'fighter', 'missile', 'naval', 'drone', 'artillery',
    'special_ops', 'retaliation', 'sof', 'maritime', 'nuke', 'nuclear',
    'strike',
}


def classify_incident_type(row):
    """Classify an enriched row into incident_type."""
    summary = row.get('summary', '') or ''
    title = row.get('incident_title', '') or ''
    text = f"{title} {summary}"
    strike_type = (row.get('strike_type', '') or '').strip().lower()
    tags = (row.get('tags', '') or '').upper()

    # Pure noise filter
    if NOISE_RE.match(text.strip()):
        return None  # filter out

    # Check tags and keywords for non-strike types
    if ECONOMIC_RE.search(text):
        return 'economic'
    if HUMANITARIAN_RE.search(text) and strike_type not in STRIKE_TYPES:
        return 'humanitarian'
    if DIPLOMATIC_RE.search(text) and strike_type not in STRIKE_TYPES:
        return 'diplomatic'
    if INTEL_RE.search(text) and strike_type not in STRIKE_TYPES:
        return 'intel'

    # If it has a recognized strike_type, it's a strike
    if strike_type in STRIKE_TYPES:
        return 'strike'

    # Default: diplomatic catch-all for enriched rows that don't match above
    if DIPLOMATIC_RE.search(text):
        return 'diplomatic'

    # Anything left with actual content is kept as strike (most enriched data)
    return 'strike'


# ── New schemas ──────────────────────────────────────────────────────────────

INCIDENTS_COLS = [
    'incident_id', 'operation_name', 'incident_title', 'date',
    'incident_type', 'strike_type', 'confirmed',
    'origin_lat', 'origin_lng', 'origin_label', 'origin_sublabel',
    'target_lat', 'target_lng', 'target_label', 'target_sublabel',
    'summary', 'target_type', 'platform_or_unit', 'result_outcome',
    'tags', 'source_type',
    'is_retaliation', 'is_covert', 'is_first_use', 'disputed',
]

DETAILS_COLS = [
    'incident_id',
    'assessment',
    'munitions_weapons', 'munitions_quantity',
    'range_km', 'target_depth_hardening',
    'military_kia_friendly', 'military_kia_enemy', 'civilian_kia',
    'military_wia_friendly',
    'personnel_deployed', 'aircraft_deployed', 'naval_vessels',
    'nuclear_setback_assessment', 'economic_impact', 'intercepted_munitions',
    'key_intelligence_notes',
    'osint_sources', 'press_sources', 'think_tank_sources',
]

INTEL_FEED_COLS = [
    'created_at', 'full_text',
    'category', 'subcategory', 'countries',
    'sentiment', 'severity', 'is_breaking',
    'lat', 'lng', 'location_confidence',
    'linked_operation', 'linked_incident_ids',
    'entities_people', 'entities_orgs', 'entities_weapons',
    'entities_locations',
    'summary',
]


# ── Migration logic ──────────────────────────────────────────────────────────

def migrate():
    print("=== Reading source files ===")
    curated     = read_csv(os.path.join(DATA_DIR, 'incidents.csv'))
    enriched    = read_csv(os.path.join(DATA_DIR, 'enriched_actions.csv'))
    classified  = read_csv(os.path.join(DATA_DIR, 'spectator_tweets_classified.csv'))
    tweet_enr   = read_csv(os.path.join(DATA_DIR, 'tweet_enriched.csv'))

    # ── 1. Build incidents.csv ────────────────────────────────────────────────
    print("\n=== Building incidents.csv ===")
    new_incidents = []

    # Curated rows — classify based on strike_type
    for row in curated:
        st = (row.get('strike_type', '') or '').strip().lower()
        if st in STRIKE_TYPES:
            row['incident_type'] = 'strike'
        else:
            row['incident_type'] = classify_incident_type(row)
        row['source_type'] = 'curated'
        new_incidents.append(row)
    print(f"  Curated: {len(curated)} rows")

    # Enriched rows — classify and filter
    kept = 0
    filtered_out = 0
    type_counts = {}
    for row in enriched:
        itype = classify_incident_type(row)
        if itype is None:
            filtered_out += 1
            continue
        row['incident_type'] = itype
        row['source_type'] = 'enriched'
        row['confirmed'] = 'FALSE'  # enriched data is never confirmed
        type_counts[itype] = type_counts.get(itype, 0) + 1
        new_incidents.append(row)
        kept += 1
    print(f"  Enriched: {kept} kept, {filtered_out} filtered out")
    print(f"  Type breakdown: {type_counts}")

    write_csv(os.path.join(DATA_DIR, 'incidents_new.csv'), INCIDENTS_COLS, new_incidents)

    # ── 2. Build incident_details.csv ─────────────────────────────────────────
    print("\n=== Building incident_details.csv ===")
    detail_fields = DETAILS_COLS[1:]  # all except incident_id
    details = []
    for row in curated:
        has_data = any(
            (row.get(f, '') or '').strip()
            and (row.get(f, '') or '').strip() != '0'
            for f in detail_fields
        )
        if has_data:
            details.append(row)
    write_csv(os.path.join(DATA_DIR, 'incident_details.csv'), DETAILS_COLS, details)

    # ── 3. Build intel_feed.csv ───────────────────────────────────────────────
    print("\n=== Building intel_feed.csv ===")

    # Index enriched tweets by created_at
    enr_by_ts = {}
    for row in tweet_enr:
        ts = row.get('created_at', '').strip()
        if ts:
            enr_by_ts[ts] = row

    # Index classified tweets by created_at
    cls_by_ts = {}
    for row in classified:
        ts = row.get('created_at', '').strip()
        if ts:
            cls_by_ts[ts] = row

    # All timestamps from both sources
    all_ts = set(enr_by_ts.keys()) | set(cls_by_ts.keys())
    print(f"  Classified: {len(cls_by_ts)}, Enriched: {len(enr_by_ts)}, Union: {len(all_ts)}")

    feed = []
    for ts in sorted(all_ts, reverse=True):
        cls_row = cls_by_ts.get(ts, {})
        enr_row = enr_by_ts.get(ts, {})

        merged = {
            'created_at': ts,
            'full_text': cls_row.get('full_text', '') or enr_row.get('summary', ''),
            'category': enr_row.get('category', '') or '',
            'subcategory': enr_row.get('subcategory', '') or '',
            'countries': enr_row.get('countries', '') or cls_row.get('countries', ''),
            'sentiment': enr_row.get('sentiment', ''),
            'severity': enr_row.get('severity', ''),
            'is_breaking': enr_row.get('is_breaking', ''),
            'lat': enr_row.get('lat', ''),
            'lng': enr_row.get('lng', ''),
            'location_confidence': enr_row.get('location_confidence', ''),
            'linked_operation': enr_row.get('linked_operation', '') or cls_row.get('operations', ''),
            'linked_incident_ids': enr_row.get('linked_incident_ids', ''),
            'entities_people': enr_row.get('entities_people', ''),
            'entities_orgs': enr_row.get('entities_orgs', ''),
            'entities_weapons': enr_row.get('entities_weapons', ''),
            'entities_locations': enr_row.get('entities_locations', ''),
            'summary': enr_row.get('summary', ''),
        }
        feed.append(merged)

    write_csv(os.path.join(DATA_DIR, 'intel_feed.csv'), INTEL_FEED_COLS, feed)

    # ── 4. Archive old files ──────────────────────────────────────────────────
    print("\n=== Archiving old files ===")
    os.makedirs(ARCHIVE, exist_ok=True)

    files_to_archive = [
        'spectator_tweets_classified.csv',
        'tweet_enriched.csv',
        'enriched_actions.csv',
        'tweets_military_operations.csv',
        'tweets_diplomacy_negotiations.csv',
        'tweets_nuclear.csv',
        'tweets_casualties_humanitarian.csv',
    ]
    for fname in files_to_archive:
        src = os.path.join(DATA_DIR, fname)
        dst = os.path.join(ARCHIVE, fname)
        if os.path.exists(src):
            shutil.move(src, dst)
            print(f"  Archived: {fname}")

    # Move spectator_media.csv to raw_data/
    sm_src = os.path.join(DATA_DIR, 'spectator_media.csv')
    sm_dst = os.path.join(DATA_DIR, 'raw_data', 'spectator_media_from_data.csv')
    if os.path.exists(sm_src):
        shutil.move(sm_src, sm_dst)
        print(f"  Moved spectator_media.csv to raw_data/")

    # Rename incidents_new.csv → incidents.csv (replace old)
    old_inc = os.path.join(DATA_DIR, 'incidents.csv')
    new_inc = os.path.join(DATA_DIR, 'incidents_new.csv')
    if os.path.exists(old_inc):
        shutil.move(old_inc, os.path.join(ARCHIVE, 'incidents_curated.csv'))
        print(f"  Archived: incidents.csv (curated original)")
    shutil.move(new_inc, old_inc)
    print(f"  Renamed: incidents_new.csv → incidents.csv")

    # ── 5. Summary ────────────────────────────────────────────────────────────
    print("\n=== Migration complete ===")
    print(f"  incidents.csv:        {len(new_incidents)} rows, {len(INCIDENTS_COLS)} cols")
    print(f"  incident_details.csv: {len(details)} rows, {len(DETAILS_COLS)} cols")
    print(f"  intel_feed.csv:       {len(feed)} rows, {len(INTEL_FEED_COLS)} cols")
    print(f"  operations.csv:       unchanged")
    print(f"  imagery.csv:          unchanged")
    print(f"  Archived {len(files_to_archive)} old files to data/archive/")


if __name__ == '__main__':
    migrate()
