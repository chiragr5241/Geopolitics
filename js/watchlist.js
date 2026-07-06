'use strict';

/* =========================================================
   WATCHLIST STORE — "mark important" persistence.

   The site is static (GitHub Pages), so there is no server to write to.
   Marks are saved instantly to localStorage, and merged on load with
   whatever data/watchlist.json shipped in the last deploy (union by
   story_id; the newer marked_at/resolved_at/last_update_at wins). To get
   marks into the repo (so the scheduled enrichment task can prioritize
   and track them), use the "Export watchlist.json" button on the Feed or
   Tracker page, then place the downloaded file at data/watchlist.json and
   commit/push (or hand it to Claude Code to do so).
   ========================================================= */

var WatchlistStore = (function () {
  var LS_KEY = 'geo.watchlist.v1';
  var doc = null; // { version, updated_at, stories: [] }

  function nowIso() {
    return new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  }

  function loadLocal() {
    try {
      var raw = localStorage.getItem(LS_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function saveLocal() {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(doc));
    } catch (e) { /* storage full or unavailable — marks still work in-session */ }
  }

  function mergeStories(a, b) {
    var byId = {};
    (a || []).forEach(function (s) { byId[s.story_id] = s; });
    (b || []).forEach(function (s) {
      var existing = byId[s.story_id];
      if (!existing) { byId[s.story_id] = s; return; }
      // Newer marked_at/last_update_at wins for the whole record — simplest
      // rule that avoids clobbering server-side tracker updates with a
      // stale local copy, or vice versa.
      var aTime = existing.last_update_at || existing.marked_at || '';
      var bTime = s.last_update_at || s.marked_at || '';
      byId[s.story_id] = (bTime > aTime) ? s : existing;
    });
    return Object.keys(byId).map(function (k) { return byId[k]; });
  }

  function init(serverStories) {
    var local = loadLocal();
    var merged = mergeStories((local && local.stories) || [], serverStories || []);
    doc = { version: 1, updated_at: nowIso(), stories: merged };
    saveLocal();
    return doc;
  }

  function slugify(text) {
    return (text || '').toLowerCase().split(/[;,]/)[0]
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'story';
  }

  function storyIdFor(item) {
    var day = (item.created_at || '').slice(0, 10).replace(/-/g, '');
    var slugSource = (item.entities_locations || item.countries || '').split(';')[0];
    return 'st-' + (day || '00000000') + '-' + slugify(slugSource || item.summary);
  }

  function findByTweet(item) {
    return doc.stories.filter(function (s) {
      return s.seed && s.seed.tweet_id && item.tweet_id && s.seed.tweet_id === item.tweet_id;
    })[0];
  }

  function isMarked(item) {
    return !!findByTweet(item);
  }

  function mark(item) {
    if (isMarked(item)) return findByTweet(item);
    var countries = (item.countries || '').split(';').map(function (c) { return c.trim(); }).filter(Boolean);
    var keywords = [];
    (item.entities_locations || '').split(';').forEach(function (l) { if (l.trim()) keywords.push(l.trim().toLowerCase()); });
    (item.entities_orgs || '').split(';').forEach(function (o) { if (o.trim()) keywords.push(o.trim().toLowerCase()); });
    var story = {
      story_id: storyIdFor(item),
      status: 'active',
      title: (item.summary || item.full_text || '').slice(0, 100),
      marked_at: nowIso(),
      seed: {
        created_at: item.created_at,
        tweet_id: item.tweet_id || '',
        text: item.full_text || item.summary || '',
        category: item.category || '',
        countries: countries,
        lat: item.lat ? parseFloat(item.lat) : null,
        lng: item.lng ? parseFloat(item.lng) : null,
      },
      query_hints: [
        [countries.join(' '), item.subcategory || item.category].filter(Boolean).join(' '),
        [(item.entities_locations || '').split(';')[0], 'latest'].filter(Boolean).join(' '),
      ].filter(Boolean),
      keywords: keywords.slice(0, 8),
      last_update_at: (item.created_at || '').slice(0, 10),
      update_count: 0,
      resolved_at: null,
      notes: '',
    };
    doc.stories.push(story);
    doc.updated_at = nowIso();
    saveLocal();
    return story;
  }

  function unmark(item) {
    var story = findByTweet(item);
    if (!story) return;
    doc.stories = doc.stories.filter(function (s) { return s.story_id !== story.story_id; });
    doc.updated_at = nowIso();
    saveLocal();
  }

  function toggle(item) {
    return isMarked(item) ? (unmark(item), false) : (mark(item), true);
  }

  function setStatus(storyId, status) {
    var story = doc.stories.filter(function (s) { return s.story_id === storyId; })[0];
    if (!story) return;
    story.status = status;
    if (status === 'resolved') story.resolved_at = nowIso();
    if (status === 'active') story.resolved_at = null;
    doc.updated_at = nowIso();
    saveLocal();
  }

  function all() {
    return doc ? doc.stories : [];
  }

  function exportFile() {
    var blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'watchlist.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  return {
    init: init,
    isMarked: isMarked,
    toggle: toggle,
    mark: mark,
    unmark: unmark,
    setStatus: setStatus,
    all: all,
    exportFile: exportFile,
  };
})();
