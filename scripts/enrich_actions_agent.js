'use strict';
/**
 * Military Actions Enrichment Agent
 *
 * Source: data/intel_feed.csv  (unified tweets, filtered to category=military)
 * Output: appends to data/incidents.csv  (24-col schema)
 *
 * Deduplication strategy:
 *   - Incident ID = ma-{YYYYMMDD}-{op-slug}-{location-slug}
 *   - Multiple tweets about the same event on the same day → same ID → INSERT OR IGNORE
 *   - Curated incident IDs (source_type=curated) are never overwritten
 *
 * Usage (from project root):
 *   ANTHROPIC_API_KEY=sk-ant-... node scripts/enrich_actions_agent.js
 *
 * Optional env vars:
 *   BATCH_SIZE   — tweets per API call (default 10)
 *   MAX_ACTIONS  — cap total rows processed, for testing (default 0 = unlimited)
 *   RESUME       — set to "false" to reprocess everything (default true = resume)
 *
 * After completion:
 *   python scripts/build_db.py
 */

const fs   = require('fs');
const path = require('path');
const { parse }     = require('csv-parse/sync');
const { stringify } = require('csv-stringify/sync');
const Anthropic = require('@anthropic-ai/sdk');

// ── Config ────────────────────────────────────────────────────────────────────
const ROOT          = path.resolve(__dirname, '..');
const INTEL_FEED_CSV = path.join(ROOT, 'data', 'intel_feed.csv');
const INCIDENTS_CSV  = path.join(ROOT, 'data', 'incidents.csv');
const OPS_CSV        = path.join(ROOT, 'data', 'operations.csv');

const BATCH_SIZE     = parseInt(process.env.BATCH_SIZE  || '10', 10);
const MAX_ACTIONS    = parseInt(process.env.MAX_ACTIONS || '0',  10);
const RESUME         = process.env.RESUME !== 'false';
const BATCH_DELAY_MS = 300;
const RETRY_DELAY_MS = 3000;
const MODEL          = 'claude-haiku-4-5-20251001';

// Incident CSV column order (mirrors new incidents.csv schema)
const OUT_COLS = [
  'incident_id','operation_name','incident_title',
  'date','incident_type','strike_type','confirmed',
  'origin_lat','origin_lng','origin_label','origin_sublabel',
  'target_lat','target_lng','target_label','target_sublabel',
  'summary','target_type','platform_or_unit','result_outcome',
  'tags','source_type',
  'is_retaliation','is_covert','is_first_use','disputed',
];

// ── Geocoding ─────────────────────────────────────────────────────────────────
const GEO = {
  'Tehran':           [35.68, 51.39], 'Fordow':            [34.88, 50.50],
  'Natanz':           [33.72, 51.73], 'Isfahan':           [32.65, 51.67],
  'Bushehr':          [28.97, 50.84], 'Kharg Island':      [29.23, 50.33],
  'Tel Aviv':         [32.08, 34.78], 'Jerusalem':         [31.77, 35.21],
  'Haifa':            [32.82, 34.99], 'Beer Sheva':        [31.25, 34.79],
  'Eilat':            [29.55, 34.95], 'Dimona':            [30.99, 35.04],
  'Gaza':             [31.52, 34.46], 'Rafah':             [31.28, 34.25],
  'Khan Younis':      [31.34, 34.30], 'Ramallah':          [31.90, 35.20],
  'Beirut':           [33.89, 35.49], "Sana'a":            [15.36, 44.19],
  'Hodeidah':         [14.80, 42.95], 'Aden':              [12.78, 45.03],
  'Marib':            [15.46, 45.32],
  'Strait of Hormuz': [26.56, 56.25], 'Gulf of Oman':      [22.00, 58.00],
  'Red Sea':          [20.00, 38.00], 'Gulf of Aden':      [12.00, 47.00],
  'Persian Gulf':     [26.00, 52.00], 'Arabian Sea':       [18.00, 65.00],
  'Riyadh':           [24.68, 46.72], 'Doha':              [25.28, 51.53],
  'Dubai':            [25.20, 55.27], 'Abu Dhabi':         [24.45, 54.37],
  'Baghdad':          [33.34, 44.40], 'Erbil':             [36.19, 44.01],
  'Damascus':         [33.51, 36.29], 'Aleppo':            [36.20, 37.16],
  'Diego Garcia':     [-7.32, 72.42], 'Islamabad':         [33.72, 73.04],
  'Kyiv':             [50.45, 30.52], 'Moscow':            [55.75, 37.62],
  'Sudzha':           [51.19, 35.27], 'Kharkiv':           [49.99, 36.23],
  'Zaporizhzhia':     [47.84, 35.14], 'Odessa':            [46.47, 30.73],
  'Manila':           [14.59, 120.98],'Taipei':            [25.04, 121.51],
  'South China Sea':  [12.00, 115.00],'2nd Thomas Shoal':  [9.73, 115.52],
  'Scarborough':      [15.13, 117.77],'Fiery Cross':       [9.55, 114.23],
  'Mischief Reef':    [9.90, 115.53], 'Hong Kong':         [22.30, 114.10],
  'Caracas':          [10.48, -66.90],'Venezuela':         [8.00, -66.00],
  'Israel':           [31.50, 34.90], 'Iran':              [33.00, 53.00],
  'Yemen':            [15.50, 47.50], 'Lebanon':           [33.90, 35.50],
  'Syria':            [35.00, 38.00], 'Iraq':              [33.00, 44.00],
  'Ukraine':          [49.00, 32.00], 'Russia':            [61.00, 60.00],
  'Philippines':      [13.00, 122.00],
};

function geoLookup(loc) {
  if (!loc) return null;
  const clean = loc.trim();
  if (GEO[clean]) return GEO[clean];
  const lower = clean.toLowerCase();
  for (const [name, coords] of Object.entries(GEO)) {
    if (lower.includes(name.toLowerCase()) || name.toLowerCase().includes(lower)) {
      return coords;
    }
  }
  return null;
}

// ── TL_MARKS interpolation ────────────────────────────────────────────────────
const TL_MARKS = [
  [new Date('2023-10-01'), -60], [new Date('2024-04-01'), -35],
  [new Date('2024-08-01'), -25], [new Date('2024-11-01'), -15],
  [new Date('2025-06-01'),   0], [new Date('2025-09-01'),  18],
  [new Date('2025-12-01'),  32], [new Date('2026-01-01'),  45],
  [new Date('2026-02-28'),  65], [new Date('2026-03-01'),  82],
  [new Date('2026-03-24'), 100],
];

function dateSortValue(tsStr) {
  const dt = new Date(tsStr.replace(' ', 'T'));
  if (isNaN(dt)) return 0;
  for (let i = 0; i < TL_MARKS.length - 1; i++) {
    const [lo, loV] = TL_MARKS[i];
    const [hi, hiV] = TL_MARKS[i + 1];
    if (dt >= lo && dt <= hi) {
      const frac = (dt - lo) / (hi - lo);
      return Math.round((loV + frac * (hiV - loV)) * 100) / 100;
    }
  }
  return dt < TL_MARKS[0][0] ? -60 : 100;
}

function formatDate(tsStr) {
  const dt = new Date(tsStr.replace(' ', 'T'));
  if (isNaN(dt)) return tsStr;
  return dt.toLocaleDateString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' });
}

function slugify(str) {
  return (str || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 25);
}

// Dedup ID: date + operation + location (so same event on same day = same ID)
function makeId(tsStr, opName, location) {
  const dt = new Date(tsStr.replace(' ', 'T'));
  const dateStr = isNaN(dt) ? '00000000' : dt.toISOString().slice(0, 10).replace(/-/g, '');
  const opSlug  = slugify(opName || 'standalone');
  const locSlug = slugify(location || 'unknown');
  return `ma-${dateStr}-${opSlug}-${locSlug}`;
}

// ── Subcategory → strike_type fallback ───────────────────────────────────────
const SUBCAT_TYPE = {
  airstrike: 'fighter', drone_strike: 'drone',
  ballistic_missile_attack: 'missile', cruise_missile_attack: 'missile',
  naval_incident: 'naval', special_operation: 'sof',
  nuclear: 'nuke', maritime_incident: 'maritime',
  artillery: 'missile', rocket_attack: 'retaliation',
  proxy_attack: 'retaliation', ground_operation: 'sof',
};

// ── Helpers ───────────────────────────────────────────────────────────────────
const sleep = ms => new Promise(r => setTimeout(r, ms));

function readCSV(p) {
  if (!fs.existsSync(p)) return [];
  try {
    return parse(fs.readFileSync(p, 'utf8'), {
      columns: true, skip_empty_lines: true, relax_quotes: true,
    });
  } catch (e) {
    console.warn(`Warning: could not parse ${p}: ${e.message}`);
    return [];
  }
}

// ── Claude prompt ─────────────────────────────────────────────────────────────
function buildPrompt(items, operations) {
  const opsList = operations.map(o =>
    `  - "${o.operation_name}" (${o.countries}, ${o.period})`
  ).join('\n');

  const itemsJson = items.map((t, i) => JSON.stringify({
    idx:        i,
    ts:         t.ts,
    text:       t.full_text,
    countries:  t.countries,
    operation:  t.operation,   // pre-matched operation from CSV
    pre_lat:    t.pre_lat,     // from tweet_enriched (may be empty)
    pre_lng:    t.pre_lng,
    pre_loc:    t.pre_loc,
  })).join('\n');

  return `You are an OSINT analyst creating map incident records from military intelligence tweets.

KNOWN OPERATIONS:
${opsList}

For each tweet decide:
1. Is this a MAPPABLE military incident? Must have a real strike/attack location. Skip:
   - Pure commentary, political statements, or troop deployments with no strike location
   - Exact duplicates of another tweet in this same batch (different wording, same event)
2. If mappable, extract:
   - location: most specific place name for the TARGET (city/facility, not country-level if possible)
   - operation_name: from the known operations list above, or "" if standalone
   - title: concise action title <60 chars (e.g. "Iranian Ballistic Missile Strike: Tel Aviv")
   - strike_type: bomber|fighter|missile|naval|sof|drone|retaliation|intel|maritime|island|nuke
   - is_retaliation: true if this is a retaliatory or proxy strike
   - tags: 2-4 UPPERCASE keywords joined with "; "

If "operation" field is already filled in the input, use that (it's pre-matched).
If "pre_lat"/"pre_lng" are provided, use that location name as the target.

Return JSON array, same length as input, one object per tweet:
{
  "idx": <same idx>,
  "map_this": true|false,
  "location": "city or facility name",
  "operation_name": "...",
  "title": "...",
  "strike_type": "...",
  "is_retaliation": false,
  "tags": "..."
}
If map_this is false, all other fields may be empty strings.

TWEETS:
${itemsJson}`;
}

async function callClaude(client, items, operations) {
  const res = await client.messages.create({
    model: MODEL, max_tokens: 4096,
    system: 'You are an OSINT analyst. Return ONLY valid JSON array, no prose.',
    messages: [{ role: 'user', content: buildPrompt(items, operations) }],
  });
  const text = res.content[0].text.trim()
    .replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  return JSON.parse(text);
}

async function callWithRetry(client, items, operations) {
  try { return await callClaude(client, items, operations); }
  catch (e) {
    console.warn(`  API error: ${e.message}. Retrying in ${RETRY_DELAY_MS}ms...`);
    await sleep(RETRY_DELAY_MS);
    try { return await callClaude(client, items, operations); }
    catch (e2) { console.warn(`  Retry failed: ${e2.message}. Skipping batch.`); return null; }
  }
}

// ── Build one incident row ────────────────────────────────────────────────────
function buildRow(t, cls) {
  const location = cls.location || t.pre_loc || '';
  const opName   = cls.operation_name || t.operation || '';
  const iid      = makeId(t.ts, opName, location);

  // Resolve coordinates: pre-computed > geo lookup from Claude location
  let lat = t.pre_lat || '';
  let lng = t.pre_lng || '';
  if ((!lat || !lng) && location) {
    const coords = geoLookup(location);
    if (coords) { lat = String(coords[0]); lng = String(coords[1]); }
  }

  const strikeType = cls.strike_type || SUBCAT_TYPE[t.subcategory] || 'missile';

  const row = {};
  OUT_COLS.forEach(col => { row[col] = ''; });
  Object.assign(row, {
    incident_id:     iid,
    operation_name:  opName,
    incident_title:  cls.title || t.full_text.slice(0, 80),
    date:            formatDate(t.ts),
    incident_type:   'strike',
    strike_type:     strikeType,
    confirmed:       'FALSE',
    target_lat:      lat,
    target_lng:      lng,
    target_label:    location,
    target_sublabel: (t.countries || '').replace(/;/g, ', '),
    summary:         t.full_text,
    target_type:     cls.target_type || '',
    platform_or_unit: cls.platform_or_unit || '',
    tags:            (cls.tags || '').trim(),
    source_type:     'enriched',
    is_retaliation:  cls.is_retaliation ? 'TRUE' : 'FALSE',
    is_covert:       'FALSE',
    is_first_use:    'FALSE',
    disputed:        'FALSE',
  });

  return row;
}

// ── Main ──────────────────────────────────────────────────────────────────────
async function main() {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) { console.error('ERROR: ANTHROPIC_API_KEY not set.'); process.exit(1); }
  const client = new Anthropic({ apiKey });

  // Load operations
  const operations  = readCSV(OPS_CSV);
  console.log(`Operations: ${operations.length}`);

  // Load existing incident IDs from incidents.csv (curated are protected, enriched for resume)
  const existingIncidents = readCSV(INCIDENTS_CSV);
  const curatedIds = new Set(
    existingIncidents.filter(r => r.source_type === 'curated').map(r => r.incident_id).filter(Boolean)
  );
  const doneIds = new Set();
  if (RESUME) {
    existingIncidents.forEach(r => { if (r.incident_id) doneIds.add(r.incident_id); });
  }
  console.log(`Curated incidents (protected): ${curatedIds.size}`);
  console.log(`Already in incidents.csv (resuming): ${doneIds.size} unique IDs`);

  // Load intel_feed.csv — filter to military category
  const allTweets = readCSV(INTEL_FEED_CSV);
  const sourceTweets = allTweets.filter(r =>
    (r.category || '').toLowerCase() === 'military'
  );
  console.log(`Intel feed: ${allTweets.length} total, ${sourceTweets.length} military tweets`);

  // Build merged input items from intel_feed (already has enrichment data inline)
  let items = sourceTweets.map(t => ({
    ts:         t.created_at,
    full_text:  t.full_text || '',
    countries:  t.countries || '',
    operation:  t.linked_operation || '',
    subcategory: t.subcategory || '',
    pre_lat:    t.lat || '',
    pre_lng:    t.lng || '',
    pre_loc:    t.entities_locations || '',
  }));

  // Pre-filter: skip tweets that have no location signal at all and look non-kinetic
  const NON_KINETIC = /\b(says|statement|warns|threatens|condemns|demands|calls|urges|agrees|reports|confirms|denies|claims|announces|pledges|vows|spokesman|minister|official|president|trump|netanyahu|biden|khamenei|diplomacy|ceasefire|negotiations|talks|deal|sanctions|vote|resolution|meeting)\b/i;
  const hasLocationSignal = (t) => t.pre_lat || t.pre_lng || t.operation ||
    /\b(strike|attack|bomb|missile|launch|hit|target|destroy|kill|intercept|fire|barrage|airstrike|drone|explosion|blast|rocket)\b/i.test(t.full_text);

  // Only skip if no location signal AND looks purely non-kinetic
  items = items.filter(t => hasLocationSignal(t) || !NON_KINETIC.test(t.full_text));
  console.log(`After pre-filter: ${items.length} candidate tweets`);

  // Skip items whose dedup ID is already done (need a tentative ID for this)
  // We use a rough pre-ID check: date + operation slug
  // (Full ID needs location from Claude, so we can't perfectly prefilter here)

  if (MAX_ACTIONS > 0) items = items.slice(0, MAX_ACTIONS);
  console.log(`Processing: ${items.length} tweets\n`);

  // Append to incidents.csv (it already has a header from migration)
  const out = fs.createWriteStream(INCIDENTS_CSV, { flags: 'a' });

  let totalMapped   = 0;
  let totalSkipped  = 0;
  let totalDupe     = 0;
  const seenIds     = new Set(doneIds); // track within this run too
  const totalBatches = Math.ceil(items.length / BATCH_SIZE);

  for (let b = 0; b < totalBatches; b++) {
    const batch = items.slice(b * BATCH_SIZE, (b + 1) * BATCH_SIZE);
    const pct   = Math.round(((b * BATCH_SIZE) / items.length) * 100);
    process.stdout.write(`  [${pct}%] batch ${b + 1}/${totalBatches}...`);

    const results = await callWithRetry(client, batch, operations);
    let batchMapped = 0;

    for (let i = 0; i < batch.length; i++) {
      const t   = batch[i];
      const cls = (results && results[i]) || { map_this: false };

      if (!cls.map_this) { totalSkipped++; continue; }

      const location = cls.location || t.pre_loc || '';
      const opName   = cls.operation_name || t.operation || '';
      const iid      = makeId(t.ts, opName, location);

      // Skip duplicates (curated or already seen this run)
      if (curatedIds.has(iid) || seenIds.has(iid)) { totalDupe++; continue; }
      seenIds.add(iid);

      const row = buildRow(t, cls);
      out.write(stringify([OUT_COLS.map(col => row[col] ?? '')]));
      batchMapped++;
      totalMapped++;
    }

    process.stdout.write(` +${batchMapped} incidents\n`);
    if (b < totalBatches - 1) await sleep(BATCH_DELAY_MS);
  }

  out.end();
  console.log(`\n${'─'.repeat(50)}`);
  console.log(`Mapped:   ${totalMapped} new incidents → incidents.csv`);
  console.log(`Skipped:  ${totalSkipped} (not mappable)`);
  console.log(`Dupes:    ${totalDupe} (same event, same day)`);
  console.log(`\nNext: python scripts/build_db.py`);
}

main().catch(e => { console.error('Fatal:', e); process.exit(1); });
