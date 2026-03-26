'use strict';

/* =========================================================
   DATA LAYER — Unified database.json backend
   All data fetching goes through this module.

   Primary source: data/database.json (built by scripts/build_db.py)
   Falls back to individual CSVs if database.json is not present.

   To swap in a Neo4j or SQL backend later, replace the
   body of loadAll() below. The interface must not change —
   app.js depends only on this contract.

   Contract:
     DataLayer.loadAll() → Promise<{ incidents, operations, imagery, tweets, tweetEnriched }>
       incidents     : Array of raw incident row objects (curated + enriched)
       operations    : Array of raw operation row objects
       imagery       : Array of raw imagery row objects
       tweets        : Array of raw tweet row objects (raw feed, may be empty)
       tweetEnriched : Array of enriched tweet row objects (intel feed)
   ========================================================= */

var DataLayer = (function () {

  // ── CSV Parser (single-pass, kept as fallback) ───────────
  // Handles quoted fields, embedded commas, embedded newlines,
  // and escaped double-quotes ("").

  function parseCSV(text) {
    var allRows  = [];
    var fields   = [];
    var current  = '';
    var inQuotes = false;

    for (var i = 0; i < text.length; i++) {
      var ch = text[i];
      if (ch === '"') {
        if (inQuotes && i + 1 < text.length && text[i + 1] === '"') {
          current += '"';
          i++;
        } else {
          inQuotes = !inQuotes;
        }
      } else if (ch === ',' && !inQuotes) {
        fields.push(current);
        current = '';
      } else if ((ch === '\n' || ch === '\r') && !inQuotes) {
        if (ch === '\r' && i + 1 < text.length && text[i + 1] === '\n') i++;
        fields.push(current);
        current = '';
        if (fields.some(function (f) { return f !== ''; })) allRows.push(fields);
        fields = [];
      } else {
        current += ch;
      }
    }
    fields.push(current);
    if (fields.some(function (f) { return f !== ''; })) allRows.push(fields);

    if (allRows.length < 2) return [];

    var headers = allRows[0];
    var rows = [];
    for (var j = 1; j < allRows.length; j++) {
      var values = allRows[j];
      if (!values[0]) continue;
      var obj = {};
      for (var k = 0; k < headers.length; k++) {
        obj[headers[k]] = (k < values.length) ? values[k] : '';
      }
      if (obj[headers[0]] === headers[0]) continue;
      rows.push(obj);
    }
    return rows;
  }

  function fetchCSV(url) {
    return fetch(url + '?v=' + Date.now())
      .then(function (res) {
        if (!res.ok) throw new Error('Fetch failed for ' + url + ': ' + res.status);
        return res.text();
      })
      .then(parseCSV);
  }

  function fetchCSVOptional(url) {
    return fetch(url + '?v=' + Date.now())
      .then(function (res) { return res.ok ? res.text() : ''; })
      .then(function (text) { return text ? parseCSV(text) : []; })
      .catch(function () { return []; });
  }

  // ── Normalise a database.json row to match the CSV string format ──
  // app.js expects all values as strings (same as CSV parsing).
  function normaliseRow(obj) {
    var out = {};
    Object.keys(obj).forEach(function (k) {
      var v = obj[k];
      out[k] = (v === null || v === undefined) ? '' : String(v);
    });
    return out;
  }

  // ── Load from unified database.json ──────────────────────
  function loadFromDatabase(url) {
    return fetch(url + '?v=' + Date.now())
      .then(function (res) {
        if (!res.ok) throw new Error('database.json not found (' + res.status + ')');
        return res.json();
      })
      .then(function (db) {
        var meta = db._meta || {};
        if (meta.counts) {
          console.info(
            '[DataLayer] database.json v' + (meta.version || 1) +
            ' generated ' + (meta.generated || '?') +
            ' — ' + (meta.counts.incidents_total || 0) + ' incidents' +
            ' (' + (meta.counts.incidents_curated || 0) + ' curated' +
            ' + ' + (meta.counts.incidents_enriched || 0) + ' enriched)'
          );
        }
        // Enriched tweets are the authoritative intel feed.
        // Synthesise a "raw tweet" row (created_at + full_text) from each
        // enriched record so the app.js merge logic still works correctly.
        var enrichedTweets = (db.tweets || []).map(normaliseRow);
        var syntheticRaw   = enrichedTweets.map(function (e) {
          return { created_at: e.created_at, full_text: e.summary || '' };
        });
        return {
          incidents:     (db.incidents  || []).map(normaliseRow),
          operations:    (db.operations || []).map(normaliseRow),
          imagery:       (db.imagery    || []).map(normaliseRow),
          tweets:        syntheticRaw,
          tweetEnriched: enrichedTweets,
        };
      });
  }

  // ── CSV fallback (for local dev without database.json) ───
  function loadFromCSVs() {
    console.warn('[DataLayer] database.json not found — falling back to CSV files.');
    return Promise.all([
      fetchCSV(DATA_SOURCES.incidents),
      fetchCSV(DATA_SOURCES.operations),
      fetchCSV(DATA_SOURCES.imagery),
      fetchCSVOptional(DATA_SOURCES.tweets),
      fetchCSVOptional(DATA_SOURCES.tweetEnriched),
    ]).then(function (results) {
      return {
        incidents:     results[0],
        operations:    results[1],
        imagery:       results[2],
        tweets:        results[3],
        tweetEnriched: results[4],
      };
    });
  }

  // ── Public API ────────────────────────────────────────────
  return {
    loadAll: function () {
      // Prefer unified database.json; fall back to individual CSVs.
      return loadFromDatabase(DATA_SOURCES.database || 'data/database.json')
        .catch(function () { return loadFromCSVs(); });
    },
  };

})();
