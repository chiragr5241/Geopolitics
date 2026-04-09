'use strict';
/**
 * AI-powered tweet enrichment using Claude.
 * Robust for ANY geopolitical news — not locked to a single conflict.
 *
 * Usage (from project root):
 *   ANTHROPIC_API_KEY=sk-ant-... node scripts/enrich-tweets.js
 *
 * Resumable: if data/tweet_enriched.csv already exists, it skips already-
 * processed created_at values and appends new rows.
 *
 * Dependencies:
 *   cd scripts && npm install
 */

const fs   = require('fs');
const path = require('path');
const { parse }     = require('csv-parse/sync');
const { stringify } = require('csv-stringify/sync');
const Anthropic = require('@anthropic-ai/sdk');

// ── Config ────────────────────────────────────────────────────────────────────
const INPUT_CSV      = path.resolve(__dirname, '../data/raw_data/spectator_raw.csv');
const OUTPUT_CSV     = path.resolve(__dirname, '../data/intel_feed.csv');
const BATCH_SIZE     = parseInt(process.env.BATCH_SIZE, 10) || 15;
const BATCH_DELAY_MS = 200;
const RETRY_DELAY_MS = 3000;
const MAX_RETRIES    = 3;
const MODEL          = process.env.ENRICH_MODEL || 'claude-haiku-4-5-20251001';

const OUTPUT_COLUMNS = [
  'created_at','full_text',
  'category','subcategory','countries',
  'sentiment','severity','is_breaking',
  'lat','lng','location_confidence',
  'linked_operation','linked_incident_ids',
  'entities_people','entities_orgs','entities_weapons','entities_locations',
  'summary',
];

// ── Expanded geocoding lookup ────────────────────────────────────────────────
// Covers major world cities, conflict zones, and strategic locations.
// Claude returns primary_location; we match it here. If no match, Claude's
// own lat/lng from the response is used as fallback.
const GEO = {
  // Middle East & Iran theater
  'Tehran':            [35.68, 51.39],  'Fordow':           [34.88, 50.50],
  'Natanz':            [33.72, 51.73],  'Isfahan':          [32.65, 51.67],
  'Bushehr':           [28.97, 50.84],  'Kharg Island':     [29.23, 50.33],
  'Shiraz':            [29.59, 52.58],  'Qom':              [34.64, 50.88],
  'Tabriz':            [38.08, 46.29],  'Bandar Abbas':     [27.18, 56.27],
  'Asaluyeh':          [27.47, 52.61],  'Abadan':           [30.34, 48.30],
  'Ahvaz':             [31.32, 48.67],  'Kerman':           [30.28, 57.08],
  'Mashhad':           [36.30, 59.60],  'Chabahar':         [25.29, 60.64],
  // Israel / Palestine / Lebanon
  'Tel Aviv':          [32.08, 34.78],  'Jerusalem':        [31.77, 35.21],
  'Haifa':             [32.79, 34.99],  'Gaza':             [31.52, 34.46],
  'Beirut':            [33.89, 35.49],  'Eilat':            [29.55, 34.95],
  'Dimona':            [30.99, 35.04],  'Arad':             [31.26, 35.21],
  'Rafah':             [31.30, 34.25],  'Khan Younis':      [31.35, 34.30],
  'Nablus':            [32.22, 35.25],  'Ramallah':         [31.90, 35.20],
  'Golan Heights':     [33.00, 35.80],
  // Gulf States
  'Riyadh':            [24.68, 46.72],  'Doha':             [25.28, 51.53],
  'Dubai':             [25.20, 55.27],  'Abu Dhabi':        [24.45, 54.37],
  'Kuwait City':       [29.37, 47.98],  'Manama':           [26.23, 50.59],
  'Muscat':            [23.59, 58.54],
  // Wider Middle East
  'Baghdad':           [33.34, 44.40],  'Damascus':         [33.51, 36.29],
  'Amman':             [31.95, 35.93],  'Ankara':           [39.93, 32.85],
  'Istanbul':          [41.01, 28.98],  'Cairo':            [30.04, 31.24],
  "Sana'a":            [15.36, 44.19],  'Aden':             [12.79, 45.04],
  'Strait of Hormuz':  [26.56, 56.25],  'Suez Canal':       [30.46, 32.35],
  'Bab el-Mandeb':     [12.58, 43.33],
  // South / Central Asia
  'Islamabad':         [33.72, 73.04],  'Kabul':            [34.53, 69.17],
  'New Delhi':         [28.61, 77.21],  'Mumbai':           [19.08, 72.88],
  // East Asia / Pacific
  'Beijing':           [39.90, 116.40], 'Taipei':           [25.03, 121.57],
  'Tokyo':             [35.68, 139.69], 'Seoul':            [37.57, 126.98],
  'Pyongyang':         [39.02, 125.75], 'Manila':           [14.60, 120.98],
  'South China Sea':   [15.00, 115.00], 'Scarborough Shoal':[15.23, 117.76],
  'Spratly Islands':   [10.00, 114.00], 'Taiwan Strait':    [24.50, 119.50],
  // Russia / Ukraine / Europe
  'Moscow':            [55.75, 37.62],  'Kyiv':             [50.45, 30.52],
  'Kharkiv':           [49.99, 36.23],  'Odesa':            [46.48, 30.73],
  'Zaporizhzhia':      [47.84, 35.14],  'Crimea':           [44.95, 34.10],
  'Donetsk':           [48.00, 37.80],  'Luhansk':          [48.57, 39.31],
  'Minsk':             [53.90, 27.57],  'Warsaw':           [52.23, 21.01],
  'Brussels':          [50.85, 4.35],   'London':           [51.51, -0.13],
  'Paris':             [48.86, 2.35],   'Berlin':           [52.52, 13.41],
  // Americas
  'Washington':        [38.91, -77.04], 'New York':         [40.71, -74.01],
  'Caracas':           [10.49, -66.88], 'Bogota':           [4.71, -74.07],
  'Mexico City':       [19.43, -99.13], 'Havana':           [23.11, -82.37],
  // Africa
  'Khartoum':          [15.50, 32.56],  'Addis Ababa':      [9.02, 38.75],
  'Mogadishu':         [2.05, 45.32],   'Tripoli':          [32.89, 13.18],
  'Lagos':             [6.52, 3.37],    'Nairobi':          [-1.29, 36.82],
  // Strategic bases
  'Diego Garcia':      [-7.32, 72.42],  'Al Udeid':         [25.12, 51.31],
  'Incirlik':          [37.00, 35.43],  'Ramstein':         [49.44, 7.60],
};

function geoLookup(loc, fallbackLat, fallbackLng) {
  if (!loc) {
    if (fallbackLat && fallbackLng) {
      return { lat: fallbackLat, lng: fallbackLng, location_confidence: 'model_estimate' };
    }
    return { lat: '', lng: '', location_confidence: 'none' };
  }
  // Exact match
  if (GEO[loc]) return { lat: GEO[loc][0], lng: GEO[loc][1], location_confidence: 'exact' };
  // Fuzzy substring match
  const locLower = loc.toLowerCase();
  for (const [name, coords] of Object.entries(GEO)) {
    const nameLower = name.toLowerCase();
    if (locLower.includes(nameLower) || nameLower.includes(locLower)) {
      return { lat: coords[0], lng: coords[1], location_confidence: 'approximate' };
    }
  }
  // Use Claude's own estimate if provided
  if (fallbackLat && fallbackLng) {
    return { lat: fallbackLat, lng: fallbackLng, location_confidence: 'model_estimate' };
  }
  return { lat: '', lng: '', location_confidence: 'none' };
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const sleep = ms => new Promise(r => setTimeout(r, ms));

function buildPrompt(tweets) {
  const numbered = tweets.map((t, i) => `${i + 1}. [${t.pub_date || t.created_at}] ${t.text || t.full_text}`).join('\n');
  return `Extract structured intelligence from these news tweets. Return a JSON array with one object per tweet in the SAME order.

For each tweet return:
{
  "category": one of "military"|"diplomatic"|"economic"|"humanitarian"|"nuclear"|"energy"|"political"|"cyber"|"trade"|"climate"|"terrorism"|"intelligence"|"legal"|"social",
  "subcategory": specific type (e.g. "airstrike", "sanctions", "ceasefire", "election", "cyberattack", "trade deal", "naval incident", etc.),
  "countries": "ISO-2 codes semicolon-separated (e.g. US;IR;IL)",
  "entities_people": "names semicolon-separated or empty",
  "entities_orgs": "org names semicolon-separated or empty",
  "entities_weapons": "weapons/military systems semicolon-separated or empty",
  "entities_locations": "all place names semicolon-separated or empty",
  "primary_location": "single most specific place name or empty",
  "lat": approximate latitude of primary_location (number or null),
  "lng": approximate longitude of primary_location (number or null),
  "sentiment": "escalatory"|"de-escalatory"|"neutral"|"mixed",
  "severity": 1-5 (1=routine, 2=notable, 3=significant, 4=major, 5=critical/breaking),
  "summary": "one sentence, max 140 chars, capturing the key intelligence"
}

Rules:
- Country codes MUST be valid ISO 3166-1 alpha-2
- If the tweet mentions a news source (Reuters, AP, WSJ, etc.), include it in entities_orgs
- If a location is mentioned but you're unsure of coordinates, provide your best estimate for lat/lng
- severity 5 = active military engagement, leadership killed, major infrastructure destroyed
- severity 4 = missile launches, significant policy shifts, major casualties
- severity 3 = sanctions, diplomatic statements with consequences, notable incidents
- severity 2 = routine diplomatic activity, minor updates, market movements
- severity 1 = commentary, analysis, polls, minor updates

Tweets:
${numbered}`;
}

function parseJsonResponse(text) {
  // Strip markdown code fences if present
  let cleaned = text.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
  // Try parsing directly
  try { return JSON.parse(cleaned); } catch (_) {}
  // Try extracting array from surrounding text
  const arrMatch = cleaned.match(/\[[\s\S]*\]/);
  if (arrMatch) {
    try { return JSON.parse(arrMatch[0]); } catch (_) {}
  }
  // Try fixing common issues: trailing commas
  cleaned = cleaned.replace(/,\s*([\]}])/g, '$1');
  try { return JSON.parse(cleaned); } catch (_) {}
  return null;
}

async function callClaude(client, tweets) {
  const res = await client.messages.create({
    model: MODEL, max_tokens: 4096,
    system: 'You are a senior intelligence analyst extracting structured data from breaking news tweets covering global geopolitics, conflicts, economics, and diplomacy. Return ONLY a valid JSON array — no markdown, no prose, no explanation.',
    messages: [{ role: 'user', content: buildPrompt(tweets) }],
  });
  const text = res.content[0].text;
  const parsed = parseJsonResponse(text);
  if (!parsed || !Array.isArray(parsed)) {
    throw new Error(`Failed to parse JSON from model response: ${text.slice(0, 200)}`);
  }
  if (parsed.length !== tweets.length) {
    console.warn(`  Warning: expected ${tweets.length} results, got ${parsed.length}. Padding/trimming.`);
  }
  return parsed;
}

async function callWithRetry(client, tweets) {
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      return await callClaude(client, tweets);
    } catch (e) {
      const isRateLimit = e.status === 429 || (e.message && e.message.includes('rate'));
      const delay = isRateLimit ? RETRY_DELAY_MS * attempt * 2 : RETRY_DELAY_MS * attempt;
      if (attempt < MAX_RETRIES) {
        console.warn(`  Attempt ${attempt}/${MAX_RETRIES} failed: ${e.message}. Retrying in ${delay}ms...`);
        await sleep(delay);
      } else {
        console.warn(`  All ${MAX_RETRIES} attempts failed: ${e.message}. Skipping batch.`);
        return null;
      }
    }
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────
async function main() {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) { console.error('ERROR: ANTHROPIC_API_KEY not set.'); process.exit(1); }

  const client = new Anthropic({ apiKey });

  // Support both spectator_raw.csv (pub_date, text) and spectator_index_tweets.csv (created_at, full_text)
  if (!fs.existsSync(INPUT_CSV)) {
    console.error(`ERROR: Input CSV not found: ${INPUT_CSV}`);
    process.exit(1);
  }

  const rawTweets = parse(fs.readFileSync(INPUT_CSV, 'utf8'), {
    columns: true, skip_empty_lines: true, relax_quotes: true, relax_column_count: true,
  });
  console.log(`Loaded ${rawTweets.length} tweets from ${path.basename(INPUT_CSV)}.`);

  // Normalize: ensure created_at and text fields exist
  const tweets = rawTweets.map(t => ({
    ...t,
    created_at: t.created_at || t.pub_date || '',
    text: t.text || t.full_text || '',
  }));

  const processedKeys = new Set();
  let existingRows = [];
  if (fs.existsSync(OUTPUT_CSV)) {
    existingRows = parse(fs.readFileSync(OUTPUT_CSV, 'utf8'), {
      columns: true, skip_empty_lines: true, relax_quotes: true, relax_column_count: true,
    });
    existingRows.forEach(r => processedKeys.add(r.created_at));
    console.log(`Resuming: ${processedKeys.size} already processed.`);
  }

  const todo = tweets.filter(t => !processedKeys.has(t.created_at));
  console.log(`${todo.length} tweets to process.`);
  if (!todo.length) { console.log('Nothing to do.'); return; }

  const isNew = existingRows.length === 0;
  const out = fs.createWriteStream(OUTPUT_CSV, { flags: isNew ? 'w' : 'a' });
  if (isNew) out.write(stringify([OUTPUT_COLUMNS]));

  let written = 0;
  let failed = 0;
  const totalBatches = Math.ceil(todo.length / BATCH_SIZE);

  for (let b = 0; b < totalBatches; b++) {
    const batch = todo.slice(b * BATCH_SIZE, (b + 1) * BATCH_SIZE);
    const processed = b * BATCH_SIZE + processedKeys.size;
    console.log(`Batch ${b + 1}/${totalBatches} (${processed}/${tweets.length} total)...`);

    const results = await callWithRetry(client, batch);

    for (let i = 0; i < batch.length; i++) {
      const tweet = batch[i];
      const r = (results && results[i]) || {};
      const geo = geoLookup(r.primary_location || '', r.lat, r.lng);
      let sev = parseInt(r.severity, 10);
      if (isNaN(sev) || sev < 1) sev = 1; if (sev > 5) sev = 5;
      let summary = (r.summary || '').replace(/\r?\n/g, ' ').trim();
      if (summary.length > 140) summary = summary.slice(0, 137) + '...';

      const tweetText = tweet.text || '';
      const isBreaking = /^(BREAKING|URGENT|FLASH|UPDATE):/i.test(tweetText);

      out.write(stringify([OUTPUT_COLUMNS.map(c => ({
        created_at: tweet.created_at,
        full_text: tweetText,
        category: r.category || '', subcategory: r.subcategory || '',
        countries: r.countries || '',
        sentiment: r.sentiment || '', severity: results ? sev : '',
        is_breaking: isBreaking ? 'TRUE' : 'FALSE',
        lat: geo.lat, lng: geo.lng, location_confidence: geo.location_confidence,
        linked_operation: '', linked_incident_ids: '',
        entities_people: r.entities_people || '',
        entities_orgs: r.entities_orgs || '', entities_weapons: r.entities_weapons || '',
        entities_locations: r.entities_locations || '',
        summary: results ? summary : '[batch failed]',
      }[c] ?? '')]));
      written++;
      if (!results) failed++;
    }
    if (b < totalBatches - 1) await sleep(BATCH_DELAY_MS);
  }

  out.end();
  console.log(`\nDone. Wrote ${written} rows to intel_feed.csv${failed ? ` (${failed} from failed batches)` : ''}`);
}

main().catch(e => { console.error('Fatal:', e); process.exit(1); });
