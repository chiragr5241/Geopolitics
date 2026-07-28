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
     DataLayer.loadAll() → Promise<{ incidents, operations, imagery, storyImages,
                                     tweets, tweetEnriched, watchlist, storyUpdates, meta }>
       incidents     : Array of raw incident row objects (curated + enriched)
       operations    : Array of raw operation row objects
       imagery       : Array of raw imagery row objects
       storyImages   : Array of keyword→hero-image rows (data/story_images.csv)
       tweets        : Array of raw tweet row objects (created_at + full_text)
       tweetEnriched : Array of enriched tweet row objects (intel feed; includes
                       tweet_id/context/implications/sources_json/confirmation_status
                       when database.json is the source)
       watchlist     : Array of watchlist story objects (data/watchlist.json)
       storyUpdates  : Array of story_updates rows (data/story_updates.csv)
       sources       : Array of source registry rows (data/sources.csv)
       meta          : database.json._meta (timeline marks, counts, generated ts) or {}
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

  // Note: we deliberately do NOT append a cache-busting query string.
  // These data files are large (database.json is several MB); busting the
  // cache on every load forced a full re-download on every navigation and
  // reload. GitHub Pages serves them with ETag/Last-Modified, so the browser
  // revalidates cheaply (304) and only re-downloads when the file actually
  // changes — which is exactly the behaviour we want.

  function fetchCSV(url) {
    return fetch(url)
      .then(function (res) {
        if (!res.ok) throw new Error('Fetch failed for ' + url + ': ' + res.status);
        return res.text();
      })
      .then(parseCSV);
  }

  function fetchCSVOptional(url) {
    return fetch(url)
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

  // ── Shape a parsed db/feed JSON object into the DataLayer contract ──
  // Works for both the full database.json and the lightweight feed.json
  // (which simply omits incidents/operations/imagery — the map-only data).
  function shapeDb(db) {
    var meta = db._meta || {};
    // Intel feed tweets include full_text directly.
    // Synthesise raw tweet rows for app.js merge compatibility.
    var enrichedTweets = (db.tweets || []).map(normaliseRow);
    var syntheticRaw   = enrichedTweets.map(function (e) {
      return { created_at: e.created_at, full_text: e.full_text || e.summary || '' };
    });
    return {
      incidents:     (db.incidents  || []).map(normaliseRow),
      operations:    (db.operations || []).map(normaliseRow),
      imagery:       (db.imagery    || []).map(normaliseRow),
      storyImages:   (db.story_images || []).map(normaliseRow),
      tweets:        syntheticRaw,
      tweetEnriched: enrichedTweets,
      watchlist:     db.watchlist     || [],
      storyUpdates:  (db.story_updates || []).map(normaliseRow),
      sources:       (db.sources || []).map(normaliseRow),
      meta:          meta,
    };
  }

  // ── Load from unified database.json (full dataset, incl. incidents) ──
  function loadFromDatabase(url) {
    return fetch(url)
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
        return shapeDb(db);
      });
  }

  // ── Load the lightweight feed.json (news pages: no incident payload) ──
  function loadFromFeed(url) {
    return fetch(url)
      .then(function (res) {
        if (!res.ok) throw new Error('feed.json not found (' + res.status + ')');
        return res.json();
      })
      .then(shapeDb);
  }

  // ── CSV fallback (for local dev without database.json) ───
  function loadFromCSVs() {
    console.warn('[DataLayer] database.json not found — falling back to CSV files.');
    return Promise.all([
      fetchCSV(DATA_SOURCES.incidents),
      fetchCSV(DATA_SOURCES.operations),
      fetchCSV(DATA_SOURCES.imagery),
      fetchCSVOptional(DATA_SOURCES.intelFeed),
      fetchCSVOptional(DATA_SOURCES.storyImages),
      fetchCSVOptional(DATA_SOURCES.sources),
    ]).then(function (results) {
      var intelFeed = results[3];
      // Synthesise raw tweet rows for app.js merge compatibility
      var syntheticRaw = intelFeed.map(function (e) {
        return { created_at: e.created_at, full_text: e.full_text || e.summary || '' };
      });
      return {
        incidents:     results[0],
        operations:    results[1],
        imagery:       results[2],
        storyImages:   results[4],
        tweets:        syntheticRaw,
        tweetEnriched: intelFeed,
        watchlist:     [],
        storyUpdates:  [],
        sources:       results[5],
        meta:          {},
      };
    });
  }

  // ── Public API ────────────────────────────────────────────
  return {
    // Full dataset (incidents/operations/imagery + feed). Used by the map.
    loadAll: function () {
      // Prefer unified database.json; fall back to individual CSVs.
      return loadFromDatabase(DATA_SOURCES.database || 'data/database.json')
        .catch(function () { return loadFromCSVs(); });
    },
    // Lightweight feed-only payload for the news pages (index/feed/tracker).
    // These pages never touch incidents/operations/imagery, so shipping the
    // full multi-MB database.json to them was pure waste. Falls back to the
    // full database (then CSVs) if feed.json hasn't been generated yet.
    loadFeed: function () {
      return loadFromFeed(DATA_SOURCES.feed || 'data/feed.json')
        .catch(function () {
          return loadFromDatabase(DATA_SOURCES.database || 'data/database.json');
        })
        .catch(function () { return loadFromCSVs(); });
    },
  };

})();
