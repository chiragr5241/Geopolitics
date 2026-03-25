'use strict';
/**
 * AI-powered tweet enrichment using Claude claude-haiku-4-5-20251001.
 * Replaces the rule-based parse_spectator_tweets.py with higher-quality
 * entity extraction, sentiment, and geocoding via the Claude API.
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
const INPUT_CSV      = path.resolve(__dirname, '../data/spectator_index_tweets.csv');
const OUTPUT_CSV     = path.resolve(__dirname, '../data/tweet_enriched.csv');
const BATCH_SIZE     = 15;
const BATCH_DELAY_MS = 100;
const RETRY_DELAY_MS = 2000;
const MODEL          = 'claude-haiku-4-5-20251001';

const OUTPUT_COLUMNS = [
  'created_at','category','subcategory','countries',
  'entities_people','entities_orgs','entities_weapons','entities_locations',
  'lat','lng','location_confidence',
  'sentiment','severity',
  'linked_incident_ids','linked_operation',
  'is_breaking','summary',
];

// ── Geocoding lookup ──────────────────────────────────────────────────────────
const GEO = {
  'Tehran':           [35.68, 51.39], 'Fordow':          [34.88, 50.50],
  'Natanz':           [33.72, 51.73], 'Isfahan':         [32.65, 51.67],
  'Bushehr':          [28.97, 50.84], 'Kharg Island':    [29.23, 50.33],
  'Tel Aviv':         [32.08, 34.78], 'Jerusalem':       [31.77, 35.21],
  'Riyadh':           [24.68, 46.72], 'Doha':            [25.28, 51.53],
  'Dubai':            [25.20, 55.27], 'Abu Dhabi':       [24.45, 54.37],
  'Diego Garcia':     [-7.32, 72.42], 'Gaza':            [31.52, 34.46],
  'Beirut':           [33.89, 35.49], "Sana'a":          [15.36, 44.19],
  'Strait of Hormuz': [26.56, 56.25], 'Baghdad':         [33.34, 44.40],
  'Eilat':            [29.55, 34.95], 'Arad':            [31.26, 35.21],
  'Dimona':           [30.99, 35.04], 'Moscow':          [55.75, 37.62],
  'Kyiv':             [50.45, 30.52], 'Islamabad':       [33.72, 73.04],
};

function geoLookup(loc) {
  if (!loc) return { lat: '', lng: '', location_confidence: 'none' };
  if (GEO[loc]) return { lat: GEO[loc][0], lng: GEO[loc][1], location_confidence: 'exact' };
  for (const [name, coords] of Object.entries(GEO)) {
    if (loc.toLowerCase().includes(name.toLowerCase()) ||
        name.toLowerCase().includes(loc.toLowerCase())) {
      return { lat: coords[0], lng: coords[1], location_confidence: 'approximate' };
    }
  }
  return { lat: '', lng: '', location_confidence: 'none' };
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const sleep = ms => new Promise(r => setTimeout(r, ms));

function buildPrompt(tweets) {
  const numbered = tweets.map((t, i) => `${i + 1}. ${t.full_text}`).join('\n');
  return `Extract structured intelligence from these tweets. Return a JSON array with one object per tweet in the same order.

For each tweet return:
{
  "category": "military"|"diplomatic"|"economic"|"humanitarian"|"nuclear"|"energy",
  "subcategory": string,
  "countries": "ISO-2 codes semicolon-separated",
  "entities_people": "names semicolon-separated or empty",
  "entities_orgs": "org names semicolon-separated or empty",
  "entities_weapons": "weapons semicolon-separated or empty",
  "entities_locations": "place names semicolon-separated or empty",
  "primary_location": "single most specific place name or empty",
  "sentiment": "escalatory"|"de-escalatory"|"neutral"|"mixed",
  "severity": 1-5,
  "summary": "one sentence max 120 chars"
}

Tweets:
${numbered}`;
}

async function callClaude(client, tweets) {
  const res = await client.messages.create({
    model: MODEL, max_tokens: 4096,
    system: 'You are an intelligence analyst extracting structured data from breaking news tweets about the Iran-Israel-US war. Return ONLY valid JSON, no prose.',
    messages: [{ role: 'user', content: buildPrompt(tweets) }],
  });
  const text = res.content[0].text.trim().replace(/^```(?:json)?\s*/i,'').replace(/\s*```$/,'');
  return JSON.parse(text);
}

async function callWithRetry(client, tweets) {
  try { return await callClaude(client, tweets); }
  catch (e) {
    console.warn(`  API error: ${e.message}. Retrying in ${RETRY_DELAY_MS}ms...`);
    await sleep(RETRY_DELAY_MS);
    try { return await callClaude(client, tweets); }
    catch (e2) { console.warn(`  Retry failed: ${e2.message}. Skipping batch.`); return null; }
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────
async function main() {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) { console.error('ERROR: ANTHROPIC_API_KEY not set.'); process.exit(1); }

  const client = new Anthropic({ apiKey });

  const tweets = parse(fs.readFileSync(INPUT_CSV, 'utf8'), { columns: true, skip_empty_lines: true, relax_quotes: true });
  console.log(`Loaded ${tweets.length} tweets.`);

  const processedKeys = new Set();
  let existingRows = [];
  if (fs.existsSync(OUTPUT_CSV)) {
    existingRows = parse(fs.readFileSync(OUTPUT_CSV, 'utf8'), { columns: true, skip_empty_lines: true, relax_quotes: true });
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
  const totalBatches = Math.ceil(todo.length / BATCH_SIZE);

  for (let b = 0; b < totalBatches; b++) {
    const batch = todo.slice(b * BATCH_SIZE, (b + 1) * BATCH_SIZE);
    console.log(`Processed ${b * BATCH_SIZE + processedKeys.size}/${tweets.length}... (batch ${b+1}/${totalBatches})`);

    const results = await callWithRetry(client, batch);

    for (let i = 0; i < batch.length; i++) {
      const tweet = batch[i];
      const r = (results && results[i]) || {};
      const geo = geoLookup(r.primary_location || '');
      let sev = parseInt(r.severity, 10);
      if (isNaN(sev) || sev < 1) sev = 1; if (sev > 5) sev = 5;
      let summary = (r.summary || '').replace(/\r?\n/g,' ').trim();
      if (summary.length > 120) summary = summary.slice(0,117) + '...';

      out.write(stringify([OUTPUT_COLUMNS.map(c => ({
        created_at: tweet.created_at,
        category: r.category || '', subcategory: r.subcategory || '',
        countries: r.countries || '', entities_people: r.entities_people || '',
        entities_orgs: r.entities_orgs || '', entities_weapons: r.entities_weapons || '',
        entities_locations: r.entities_locations || '',
        lat: geo.lat, lng: geo.lng, location_confidence: geo.location_confidence,
        sentiment: r.sentiment || '', severity: results ? sev : '',
        linked_incident_ids: '', linked_operation: '',
        is_breaking: tweet.full_text.startsWith('BREAKING:') ? 'TRUE' : 'FALSE',
        summary: results ? summary : '[batch failed]',
      }[c] ?? ''))]));
      written++;
    }
    if (b < totalBatches - 1) await sleep(BATCH_DELAY_MS);
  }

  out.end();
  console.log(`\nDone. Wrote ${written} rows to tweet_enriched.csv`);
}

main().catch(e => { console.error('Fatal:', e); process.exit(1); });
