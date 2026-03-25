'use strict';

/* =========================================================
   DATA LAYER — CSV-backed data access
   All data fetching goes through this module.

   To swap in a Neo4j or SQL backend later, replace the
   body of each function below with the appropriate API
   call. The interface (function signatures and return
   shapes) must not change — app.js depends only on this
   contract, not on CSVs.

   Contract:
     DataLayer.loadAll() → Promise<{ incidents, operations, imagery }>
       incidents  : Array of raw incident row objects (keys = CSV headers)
       operations : Array of raw operation row objects (keys = CSV headers)
       imagery    : Array of raw imagery row objects   (keys = CSV headers)
   ========================================================= */

var DataLayer = (function () {

  // ── CSV Parser (single-pass) ─────────────────────────────
  // Handles quoted fields, embedded commas, embedded newlines,
  // and escaped double-quotes (""). Does NOT strip quote chars
  // during line-collection — everything is resolved in one pass.

  function parseCSV(text) {
    var allRows  = [];   // array of field arrays
    var fields   = [];   // fields for current row
    var current  = '';   // current field value
    var inQuotes = false;

    for (var i = 0; i < text.length; i++) {
      var ch = text[i];

      if (ch === '"') {
        if (inQuotes && i + 1 < text.length && text[i + 1] === '"') {
          // Escaped double-quote inside a quoted field → emit one "
          current += '"';
          i++;
        } else {
          // Toggle quoted-field mode; do NOT emit the quote char itself
          inQuotes = !inQuotes;
        }
      } else if (ch === ',' && !inQuotes) {
        // Field separator
        fields.push(current);
        current = '';
      } else if ((ch === '\n' || ch === '\r') && !inQuotes) {
        // Row separator (handles \r\n, \n, \r)
        if (ch === '\r' && i + 1 < text.length && text[i + 1] === '\n') i++;
        fields.push(current);
        current = '';
        if (fields.some(function (f) { return f !== ''; })) allRows.push(fields);
        fields = [];
      } else {
        current += ch;
      }
    }
    // Flush last field / row
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
      // Skip accidental duplicate-header rows
      if (obj[headers[0]] === headers[0]) continue;
      rows.push(obj);
    }
    return rows;
  }

  // ── CSV Fetch helper ──────────────────────────────────────

  function fetchCSV(url) {
    return fetch(url + '?v=' + Date.now())
      .then(function (res) {
        if (!res.ok) throw new Error('Fetch failed for ' + url + ': ' + res.status);
        return res.text();
      })
      .then(parseCSV);
  }

  // Like fetchCSV but returns [] instead of throwing on 404.
  // Used for optional data files that may not exist yet.
  function fetchCSVOptional(url) {
    return fetch(url + '?v=' + Date.now())
      .then(function (res) {
        if (!res.ok) return '';
        return res.text();
      })
      .then(function (text) { return text ? parseCSV(text) : []; })
      .catch(function () { return []; });
  }

  // ── Public API ────────────────────────────────────────────
  // Replace the body of loadAll() to swap data sources.
  // The returned shape must remain { incidents, operations, imagery, tweets, tweetEnriched }.

  return {
    loadAll: function () {
      return Promise.all([
        fetchCSV(DATA_SOURCES.incidents),
        fetchCSV(DATA_SOURCES.operations),
        fetchCSV(DATA_SOURCES.imagery),
        fetchCSV(DATA_SOURCES.tweets),
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
    },
  };

})();
