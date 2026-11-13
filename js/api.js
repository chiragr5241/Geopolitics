'use strict';

/* =========================================================
   API CLIENT — the read API in api/ (FastAPI over Neo4j).

   The DataLayer (js/data.js) and speeches.js ask the API first and fall back
   to the static files (data/feed.json, data/database.json, ...) whenever it is
   not configured, unreachable, slow, or errors. So the site works the same with
   or without a server; the API just makes the data live.

   Which API:
     - on localhost / 127.0.0.1  → LOCAL_BASE (uvicorn on :8787)
     - anywhere else             → PRODUCTION_BASE ('' = none yet: static files)
   Overrides (stored per browser, in localStorage):
     ?api=off    always use the static files
     ?api=prod   use PRODUCTION_BASE even on localhost
     ?api=local  use LOCAL_BASE
     ?api=auto   forget the override
     ?api=<url>  any URL — honoured on localhost only, so nobody can hand a
                 visitor of the live site a link that points it at another server.

   A failed call (network error, timeout, 5xx) marks the API down for this tab
   for 5 minutes, so later page loads don't wait on it again.
   ========================================================= */

var Api = (function () {
  // Set this to the hosted API's origin once it is deployed, e.g.
  // 'https://geopolitics-api.fly.dev'. Empty = the live site uses static files.
  var PRODUCTION_BASE = '';
  var LOCAL_BASE = 'http://127.0.0.1:8787';

  var KEY = 'geo.apiBase';
  var DOWN_KEY = 'geo.apiDownUntil';
  var DOWN_MS = 5 * 60 * 1000;
  var isLocal = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);

  function resolveBase() {
    var choice = null;
    try {
      var p = new URLSearchParams(location.search).get('api');
      if (p !== null) {
        var allowed = p === 'off' || p === 'prod' || p === 'local' || (isLocal && /^https?:\/\//.test(p));
        if (allowed) localStorage.setItem(KEY, p);
        else localStorage.removeItem(KEY);        // 'auto', '' or a refused URL
        sessionStorage.removeItem(DOWN_KEY);
      }
      choice = localStorage.getItem(KEY);
    } catch (e) { /* storage blocked — use the default */ }

    if (choice === 'off') return '';
    if (choice === 'prod') return PRODUCTION_BASE;
    if (choice === 'local') return LOCAL_BASE;
    if (choice && isLocal) return choice.replace(/\/+$/, '');
    return isLocal ? LOCAL_BASE : PRODUCTION_BASE;
  }

  var BASE = resolveBase();

  function isDown() {
    try { return Date.now() < Number(sessionStorage.getItem(DOWN_KEY) || 0); } catch (e) { return false; }
  }
  function markDown() {
    try { sessionStorage.setItem(DOWN_KEY, String(Date.now() + DOWN_MS)); } catch (e) { /* ignore */ }
  }

  // GET a JSON endpoint. Rejects (never hangs) so callers can fall back.
  function get(path, timeoutMs) {
    if (!BASE) return Promise.reject(new Error('no API configured'));
    if (isDown()) return Promise.reject(new Error('API marked down for this tab'));
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, timeoutMs || 10000) : null;
    var notFound = false;
    return fetch(BASE + path, ctrl ? { signal: ctrl.signal } : {})
      .then(function (res) {
        if (res.status === 404) notFound = true;
        if (!res.ok) throw new Error('API ' + res.status + ' for ' + path);
        return res.json();               // the timeout also covers the body
      })
      .then(function (data) {
        clearTimeout(timer);
        return data;
      }, function (err) {
        clearTimeout(timer);
        if (!notFound) markDown();       // a 404 is an answer, not an outage
        throw err;
      });
  }

  function qs(params) {
    var parts = [];
    Object.keys(params || {}).forEach(function (k) {
      var v = params[k];
      if (v !== undefined && v !== null && v !== '') parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(v));
    });
    return parts.length ? '?' + parts.join('&') : '';
  }

  return {
    base: BASE,
    enabled: function () { return !!BASE && !isDown(); },
    get: get,
    // The bootstrap payloads: same shape as data/feed.json / data/database.json.
    bootstrap: function (scope) {
      return get('/api/bootstrap?scope=' + (scope === 'full' ? 'full' : 'feed'), scope === 'full' ? 20000 : 12000);
    },
    // Paged feed, newest first. opts: {before, limit, q, story}; pass the
    // response's `next` as `before` to get the following page.
    feedPage: function (opts) { return get('/api/feed' + qs(opts)); },
    stories: function () { return get('/api/stories'); },
    // A story's whole merged timeline (every linked row, not just the newest 2000).
    storyTimeline: function (storyId) { return get('/api/stories/' + encodeURIComponent(storyId) + '/timeline'); },
    speeches: function (session) { return get('/api/speeches/' + encodeURIComponent(session)); },
  };
})();
