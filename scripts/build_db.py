#!/usr/bin/env python3
"""
Build SQLite database from the 5 canonical CSVs and export data/database.json.

Usage (from project root):
  python scripts/build_db.py

Reads:  data/incidents.csv         (24-col core incidents)
        data/incident_details.csv  (19-col overflow details for curated rows)
        data/operations.csv        (operation metadata)
        data/imagery.csv           (per-incident imagery)
        data/intel_feed.csv        (unified tweet intelligence)

Exports: data/database.json  (single file for the frontend DataLayer)
         data/geopolitics.db (SQLite for backend queries / agent reads)
"""

import csv
import json
import os
import sqlite3
from datetime import datetime

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data')
DB_PATH  = os.path.join(DATA_DIR, 'geopolitics.db')
OUT_PATH = os.path.join(DATA_DIR, 'database.json')


# ── Helpers ───────────────────────────────────────────────────────────────────

def read_csv(path):
    if not os.path.exists(path):
        print(f'  SKIP (not found): {path}')
        return []
    with open(path, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            if row.get(reader.fieldnames[0]) == reader.fieldnames[0]:
                continue
            rows.append(dict(row))
    return rows


def date_to_sort_value(ts_str):
    """
    Map a date string to the TL_MARKS date_sort_value scale used by the
    frontend timeline.  Interpolates linearly between known mark points.
    """
    marks = [
        (datetime(2023, 10,  1),  -60),
        (datetime(2024,  4,  1),  -35),
        (datetime(2024,  8,  1),  -25),
        (datetime(2024, 11,  1),  -15),
        (datetime(2025,  6,  1),    0),
        (datetime(2025,  9,  1),   18),
        (datetime(2025, 12,  1),   32),
        (datetime(2026,  1,  1),   45),
        (datetime(2026,  2, 28),   65),
        (datetime(2026,  3,  1),   82),
        (datetime(2026,  3, 24),  100),
    ]

    if not ts_str:
        return 0

    # Normalize various date formats
    ts_str = ts_str.replace('T', ' ').replace('Z', '').split('+')[0].strip()

    dt = None
    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%b %d, %Y', '%B %Y']:
        try:
            dt = datetime.strptime(ts_str[:19].strip(), fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return 0

    for i in range(len(marks) - 1):
        lo_dt, lo_v = marks[i]
        hi_dt, hi_v = marks[i + 1]
        if lo_dt <= dt <= hi_dt:
            span = (hi_dt - lo_dt).total_seconds()
            frac = (dt - lo_dt).total_seconds() / span
            return round(lo_v + frac * (hi_v - lo_v), 2)
    return -60 if dt < marks[0][0] else 100


def compute_badge_colors(row):
    """Derive badge_colors from tags and is_retaliation (matches frontend logic)."""
    tags = (row.get('tags', '') or '').split(';')
    strike_type = (row.get('strike_type', '') or '').lower()
    colors = []

    type_color_map = {
        'bomber': 'blue', 'fighter': 'blue', 'missile': 'red',
        'naval': 'teal', 'drone': 'orange', 'artillery': 'brown',
        'special_ops': 'green', 'sof': 'green', 'nuclear': 'gold',
        'nuke': 'gold', 'retaliation': 'amber', 'intel': 'purple',
        'maritime': 'teal', 'strike': 'red',
    }

    # Operation color
    if row.get('operation_name') and row['operation_name'] != 'Independent Actions':
        colors.append('op')

    # Strike type color
    if strike_type in type_color_map:
        colors.append(type_color_map[strike_type])

    # Retaliation flag
    if (row.get('is_retaliation', '') or '').upper() == 'TRUE':
        colors.append('amber')

    # Tag-based extras
    for tag in tags:
        tag_up = tag.strip().upper()
        if 'NUCLEAR' in tag_up or 'NUKE' in tag_up:
            colors.append('gold')
        elif 'FIRST USE' in tag_up:
            colors.append('gold')

    # Deduplicate while preserving order
    seen = set()
    result = []
    for c in colors:
        if c not in seen:
            seen.add(c)
            result.append(c)

    return ';'.join(result)


# ── Database schemas ──────────────────────────────────────────────────────────

INCIDENTS_SCHEMA = '''
CREATE TABLE IF NOT EXISTS incidents (
    incident_id             TEXT PRIMARY KEY,
    operation_name          TEXT,
    operation_color         TEXT,
    incident_title          TEXT,
    date                    TEXT,
    date_sort_value         REAL,
    incident_type           TEXT,
    strike_type             TEXT,
    confirmed               TEXT,
    origin_lat              TEXT,
    origin_lng              TEXT,
    origin_label            TEXT,
    origin_sublabel         TEXT,
    target_lat              TEXT,
    target_lng              TEXT,
    target_label            TEXT,
    target_sublabel         TEXT,
    summary                 TEXT,
    assessment              TEXT,
    platform_or_unit        TEXT,
    munitions_weapons       TEXT,
    munitions_quantity      TEXT,
    range_km                TEXT,
    target_type             TEXT,
    target_depth_hardening  TEXT,
    military_kia_friendly   TEXT,
    military_kia_enemy      TEXT,
    civilian_kia            TEXT,
    military_wia_friendly   TEXT,
    personnel_deployed      TEXT,
    aircraft_deployed       TEXT,
    naval_vessels           TEXT,
    result_outcome          TEXT,
    nuclear_setback_assessment TEXT,
    economic_impact         TEXT,
    intercepted_munitions   TEXT,
    key_intelligence_notes  TEXT,
    osint_sources           TEXT,
    press_sources           TEXT,
    think_tank_sources      TEXT,
    tags                    TEXT,
    badge_colors            TEXT,
    is_retaliation          TEXT,
    is_covert               TEXT,
    is_first_use            TEXT,
    disputed                TEXT,
    source_type             TEXT DEFAULT 'curated'
)'''

# The full column list for the SQLite incidents table (includes computed + detail cols)
INCIDENT_DB_COLS = [
    'incident_id', 'operation_name', 'operation_color', 'incident_title', 'date',
    'date_sort_value', 'incident_type', 'strike_type', 'confirmed',
    'origin_lat', 'origin_lng', 'origin_label', 'origin_sublabel',
    'target_lat', 'target_lng', 'target_label', 'target_sublabel',
    'summary', 'assessment', 'platform_or_unit', 'munitions_weapons',
    'munitions_quantity', 'range_km', 'target_type', 'target_depth_hardening',
    'military_kia_friendly', 'military_kia_enemy', 'civilian_kia',
    'military_wia_friendly', 'personnel_deployed', 'aircraft_deployed',
    'naval_vessels', 'result_outcome', 'nuclear_setback_assessment',
    'economic_impact', 'intercepted_munitions', 'key_intelligence_notes',
    'osint_sources', 'press_sources', 'think_tank_sources',
    'tags', 'badge_colors', 'is_retaliation', 'is_covert', 'is_first_use',
    'disputed', 'source_type',
]

TWEETS_SCHEMA = '''
CREATE TABLE IF NOT EXISTS tweets (
    created_at          TEXT PRIMARY KEY,
    full_text           TEXT,
    category            TEXT,
    subcategory         TEXT,
    countries           TEXT,
    sentiment           TEXT,
    severity            TEXT,
    is_breaking         TEXT,
    lat                 TEXT,
    lng                 TEXT,
    location_confidence TEXT,
    linked_operation    TEXT,
    linked_incident_ids TEXT,
    entities_people     TEXT,
    entities_orgs       TEXT,
    entities_weapons    TEXT,
    entities_locations  TEXT,
    summary             TEXT
)'''

TWEET_DB_COLS = [
    'created_at', 'full_text', 'category', 'subcategory', 'countries',
    'sentiment', 'severity', 'is_breaking',
    'lat', 'lng', 'location_confidence',
    'linked_operation', 'linked_incident_ids',
    'entities_people', 'entities_orgs', 'entities_weapons',
    'entities_locations', 'summary',
]


# ── Build ─────────────────────────────────────────────────────────────────────

def build():
    # Remove old DB to rebuild from scratch
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ── Create tables ─────────────────────────────────────────────────────────
    c.execute(INCIDENTS_SCHEMA)
    c.execute('''
    CREATE TABLE IF NOT EXISTS operations (
        operation_name TEXT PRIMARY KEY,
        color          TEXT,
        countries      TEXT,
        period         TEXT,
        dashed         TEXT
    )''')
    c.execute('''
    CREATE TABLE IF NOT EXISTS imagery (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        incident_id TEXT,
        label       TEXT,
        url         TEXT,
        caption     TEXT,
        source      TEXT
    )''')
    c.execute(TWEETS_SCHEMA)
    conn.commit()

    # ── Import operations ─────────────────────────────────────────────────────
    ops = read_csv(os.path.join(DATA_DIR, 'operations.csv'))
    for r in ops:
        c.execute(
            'INSERT OR REPLACE INTO operations VALUES (?,?,?,?,?)',
            [r.get('operation_name', ''), r.get('color', ''),
             r.get('countries', ''),      r.get('period', ''),
             r.get('dashed', '')]
        )
    print(f'  Operations: {len(ops)} rows')

    # Build ops lookup: name → color
    ops_color = {r.get('operation_name', ''): r.get('color', '') for r in ops}

    # ── Import imagery ────────────────────────────────────────────────────────
    imgs = read_csv(os.path.join(DATA_DIR, 'imagery.csv'))
    for r in imgs:
        c.execute(
            'INSERT INTO imagery (incident_id,label,url,caption,source) VALUES (?,?,?,?,?)',
            [r.get('incident_id', ''), r.get('label', ''),
             r.get('url', ''),         r.get('caption', ''),
             r.get('source', '')]
        )
    print(f'  Imagery: {len(imgs)} rows')

    # ── Import incidents (new 24-col CSV) + inline details ────────────────────
    incidents = read_csv(os.path.join(DATA_DIR, 'incidents.csv'))
    details = read_csv(os.path.join(DATA_DIR, 'incident_details.csv'))

    # Index details by incident_id
    details_by_id = {r.get('incident_id', ''): r for r in details}

    for r in incidents:
        iid = r.get('incident_id', '')

        # Compute derived fields
        r['operation_color'] = ops_color.get(r.get('operation_name', ''), '#9e9e9e')
        r['date_sort_value'] = date_to_sort_value(r.get('date', ''))
        r['badge_colors'] = compute_badge_colors(r)

        # Inline detail fields (if this incident has details)
        detail = details_by_id.get(iid, {})
        for col in [
            'assessment', 'munitions_weapons', 'munitions_quantity', 'range_km',
            'target_depth_hardening', 'military_kia_friendly', 'military_kia_enemy',
            'civilian_kia', 'military_wia_friendly', 'personnel_deployed',
            'aircraft_deployed', 'naval_vessels', 'nuclear_setback_assessment',
            'economic_impact', 'intercepted_munitions', 'key_intelligence_notes',
            'osint_sources', 'press_sources', 'think_tank_sources',
        ]:
            if col not in r or not r.get(col):
                r[col] = detail.get(col, '')

        vals = [r.get(col, '') for col in INCIDENT_DB_COLS]
        c.execute(
            f'INSERT OR REPLACE INTO incidents VALUES ({",".join(["?"] * len(INCIDENT_DB_COLS))})',
            vals
        )

    curated_count = sum(1 for r in incidents if r.get('source_type') == 'curated')
    enriched_count = len(incidents) - curated_count
    print(f'  Incidents: {curated_count} curated + {enriched_count} enriched = {len(incidents)} total')

    # ── Import intel feed tweets ──────────────────────────────────────────────
    tweets = read_csv(os.path.join(DATA_DIR, 'intel_feed.csv'))
    inserted = 0
    for r in tweets:
        try:
            vals = [r.get(col, '') for col in TWEET_DB_COLS]
            c.execute(
                f'INSERT OR IGNORE INTO tweets VALUES ({",".join(["?"] * len(TWEET_DB_COLS))})',
                vals
            )
            inserted += 1
        except Exception:
            pass
    print(f'  Tweets: {inserted} rows')

    conn.commit()

    # ── Export JSON ────────────────────────────────────────────────────────────
    export_json(conn, OUT_PATH)
    conn.close()
    print(f'\nDatabase: {DB_PATH}')
    print(f'Export:   {OUT_PATH}')


def export_json(conn, out_path):
    def query(sql, params=()):
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    incidents  = query('SELECT * FROM incidents ORDER BY CAST(date_sort_value AS REAL)')
    operations = query('SELECT * FROM operations')
    imagery    = query('SELECT * FROM imagery')
    tweets     = query('SELECT * FROM tweets ORDER BY created_at DESC LIMIT 2000')

    curated  = [i for i in incidents if i.get('source_type') == 'curated']
    enriched = [i for i in incidents if i.get('source_type') == 'enriched']

    data = {
        '_meta': {
            'generated': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'version':   3,
            'counts': {
                'incidents_curated':  len(curated),
                'incidents_enriched': len(enriched),
                'incidents_total':    len(incidents),
                'operations':         len(operations),
                'imagery':            len(imagery),
                'tweets':             len(tweets),
            }
        },
        'incidents':  incidents,
        'operations': operations,
        'imagery':    imagery,
        'tweets':     tweets,
    }

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

    print(f'\nExported:')
    print(f'  {len(curated)} curated + {len(enriched)} enriched = {len(incidents)} total incidents')
    print(f'  {len(operations)} operations, {len(imagery)} imagery, {len(tweets)} tweets')
    size_kb = os.path.getsize(out_path) // 1024
    print(f'  database.json: {size_kb} KB')


if __name__ == '__main__':
    print('Building database...')
    build()
    print('\nDone.')
