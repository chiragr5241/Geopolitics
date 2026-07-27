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

  // Merge local + server stories, PRESERVING the local array order — that order
  // is the user's manual priority (drives the main-page tile sizes and the
  // tracker rail). Local rows keep their slot; the newer record's *content*
  // wins; server-only stories append at the end.
  function mergeStories(a, b) {
    var bById = {};
    (b || []).forEach(function (s) { bById[s.story_id] = s; });
    var out = [];
    var seen = {};
    (a || []).forEach(function (s) {
      if (seen[s.story_id]) return;
      seen[s.story_id] = 1;
      var other = bById[s.story_id];
      if (!other) { out.push(s); return; }
      var aTime = s.last_update_at || s.marked_at || '';
      var bTime = other.last_update_at || other.marked_at || '';
      // Take the newer record's content but hold the local slot. Carry the
      // local `order`/position implicitly by pushing here.
      //
      // Ties go to the SERVER: a data-only edit (a new hero image, a reworded
      // title) doesn't move last_update_at, so a strict `>` pinned the stale
      // local copy forever for anyone who'd already cached the story.
      // A genuine local edit stamps `edited_at` and outranks that.
      if (s.edited_at && s.edited_at > bTime) { out.push(s); return; }
      out.push((bTime >= aTime) ? other : s);
    });
    (b || []).forEach(function (s) {
      if (seen[s.story_id]) return;
      seen[s.story_id] = 1;
      out.push(s);
    });
    return out;
  }

  function init(serverStories) {
    var local = loadLocal();
    var merged = mergeStories((local && local.stories) || [], serverStories || []);
    doc = { version: 1, updated_at: nowIso(), stories: merged };
    saveLocal();
    return doc;
  }

  function slugify(text) {
    var s = (text || '').toLowerCase().split(/[;,]/)[0]
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    // Cap length so a headline-derived id stays readable and stable.
    if (s.length > 48) s = s.slice(0, 48).replace(/-+$/, '');
    return s || 'story';
  }

  // A stable story id for a feed item. Tweets keep the coarse
  // day+location/country bucket (each tweet is its own seed anyway, via
  // findByTweet). Wire / no-tweet_id items MUST derive from the headline: a
  // country-only id collapsed every same-day, same-country item into one
  // bucket, so starring one appeared to star its siblings and unstarring
  // couldn't target just one (the "can't remove the cockroach headline" bug).
  function storyIdFor(item) {
    var day = (item.created_at || '').slice(0, 10).replace(/-/g, '');
    var slugSource;
    if (item.tweet_id) {
      slugSource = (item.entities_locations || item.countries || '').split(';')[0] ||
        item.summary || item.full_text;
    } else {
      slugSource = item.summary || item.full_text ||
        (item.entities_locations || item.countries || '').split(';')[0];
    }
    return 'st-' + (day || '00000000') + '-' + slugify(slugSource);
  }

  function findByTweet(item) {
    return doc.stories.filter(function (s) {
      return s.seed && s.seed.tweet_id && item.tweet_id && s.seed.tweet_id === item.tweet_id;
    })[0];
  }

  function byId(id) {
    return doc.stories.filter(function (s) { return s.story_id === id; })[0];
  }

  function hasId(id) {
    return !!byId(id);
  }

  // A feed item counts as "marked" if either its tweet is the seed of a story
  // or a story already exists for the story_id it would generate — so the Feed
  // star and the Tracker catalog stay in sync on the same underlying story.
  function isMarked(item) {
    return !!findByTweet(item) || hasId(storyIdFor(item));
  }

  // Build a full watchlist story record from a feed/enriched item.
  function buildStory(item) {
    var countries = (item.countries || '').split(';').map(function (c) { return c.trim(); }).filter(Boolean);
    var keywords = [];
    (item.entities_locations || '').split(';').forEach(function (l) { if (l.trim()) keywords.push(l.trim().toLowerCase()); });
    (item.entities_orgs || '').split(';').forEach(function (o) { if (o.trim()) keywords.push(o.trim().toLowerCase()); });
    return {
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
      image: '',
      parent_id: null,
    };
  }

  // Track a feed/suggested item. Idempotent by story_id — re-tracking a story
  // that already exists just returns the existing record.
  function trackItem(item) {
    var existing = findByTweet(item) || byId(storyIdFor(item));
    if (existing) return existing;
    var story = buildStory(item);
    doc.stories.push(story);
    doc.updated_at = nowIso();
    saveLocal();
    return story;
  }

  // Sub-track: seed a CHILD story from a feed item, linked to a parent story via
  // `parent_id`. Barebones scaffolding for a future "sub-thread" feature — a child
  // is a normal tracked story that also records which story it branched from.
  // Idempotent by story_id (re-seeding the same item returns the existing child).
  function addSubTrack(parentId, item) {
    var existing = findByTweet(item) || byId(storyIdFor(item));
    if (existing) {
      if (!existing.parent_id) existing.parent_id = parentId;
      return existing;
    }
    var story = buildStory(item);
    story.parent_id = parentId;
    doc.stories.push(story);
    doc.updated_at = nowIso();
    saveLocal();
    return story;
  }

  // All stories that branched from a given parent story.
  function childrenOf(parentId) {
    return doc.stories.filter(function (s) { return s.parent_id === parentId; });
  }

  // Create a fully custom tracked story from a small form. Generates a stable
  // story_id from the title (+ today), de-duplicating on collision.
  function addCustom(fields) {
    fields = fields || {};
    var title = (fields.title || '').trim();
    if (!title) return null;
    var day = nowIso().slice(0, 10).replace(/-/g, '');
    var base = 'st-' + day + '-' + slugify(title);
    var id = base;
    var n = 2;
    while (hasId(id)) { id = base + '-' + n; n++; }
    var countries = (fields.countries || '')
      .split(/[,;]/).map(function (c) { return c.trim().toUpperCase(); }).filter(Boolean);
    var keywords = (fields.keywords || '')
      .split(/[,;]/).map(function (k) { return k.trim().toLowerCase(); }).filter(Boolean);
    var story = {
      story_id: id,
      status: 'active',
      title: title.slice(0, 120),
      marked_at: nowIso(),
      seed: {
        created_at: nowIso().replace('T', ' ').replace('Z', ''),
        tweet_id: '',
        text: (fields.text || '').trim(),
        category: (fields.category || '').trim(),
        countries: countries,
        lat: null,
        lng: null,
      },
      query_hints: [title],
      keywords: keywords.slice(0, 8),
      last_update_at: nowIso().slice(0, 10),
      update_count: 0,
      resolved_at: null,
      notes: '',
      custom: true,
      image: (fields.image || '').trim(),
      parent_id: null,
    };
    doc.stories.push(story);
    doc.updated_at = nowIso();
    saveLocal();
    return story;
  }

  function removeById(id) {
    doc.stories = doc.stories.filter(function (s) { return s.story_id !== id; });
    doc.updated_at = nowIso();
    saveLocal();
  }

  function indexOf(id) {
    for (var i = 0; i < doc.stories.length; i++) {
      if (doc.stories[i].story_id === id) return i;
    }
    return -1;
  }

  // Priority reorder. Array position IS the priority (top = highest), so both
  // the ▲/▼ nudge and drag-to-index just splice the array and persist.
  function moveBy(id, delta) {
    var i = indexOf(id);
    if (i < 0) return;
    var j = i + delta;
    if (j < 0 || j >= doc.stories.length) return;
    var tmp = doc.stories[i];
    doc.stories[i] = doc.stories[j];
    doc.stories[j] = tmp;
    doc.updated_at = nowIso();
    saveLocal();
  }

  function moveTo(id, index) {
    var i = indexOf(id);
    if (i < 0) return;
    var item = doc.stories.splice(i, 1)[0];
    index = Math.max(0, Math.min(index, doc.stories.length));
    doc.stories.splice(index, 0, item);
    doc.updated_at = nowIso();
    saveLocal();
  }

  // Edit a tracked story's user-facing fields (title, seed text, keywords,
  // country codes). Keywords/countries drive story-linking and image matching,
  // so they're split on comma/semicolon and normalised the same way as addCustom.
  function updateStory(id, fields) {
    var s = byId(id);
    if (!s) return null;
    fields = fields || {};
    if (fields.title != null) s.title = String(fields.title).trim().slice(0, 140);
    if (fields.text != null) {
      s.seed = s.seed || {};
      s.seed.text = String(fields.text).trim();
    }
    if (fields.keywords != null) {
      s.keywords = String(fields.keywords).split(/[,;]/)
        .map(function (k) { return k.trim().toLowerCase(); }).filter(Boolean).slice(0, 12);
    }
    if (fields.countries != null) {
      s.seed = s.seed || {};
      s.seed.countries = String(fields.countries).split(/[,;]/)
        .map(function (c) { return c.trim().toUpperCase(); }).filter(Boolean);
    }
    // A URL or a data: base64 string. Empty string clears the custom image.
    if (fields.image != null) s.image = String(fields.image).trim();
    // Marks this record as user-authored so mergeStories won't let a same-day
    // server record clobber it.
    s.edited_at = nowIso();
    doc.updated_at = nowIso();
    saveLocal();
    return s;
  }

  function unmark(item) {
    var story = findByTweet(item) || byId(storyIdFor(item));
    if (!story) return;
    removeById(story.story_id);
  }

  function toggle(item) {
    return isMarked(item) ? (unmark(item), false) : (trackItem(item), true);
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
    mark: trackItem,
    trackItem: trackItem,
    unmark: unmark,
    removeById: removeById,
    addSubTrack: addSubTrack,
    childrenOf: childrenOf,
    moveBy: moveBy,
    moveTo: moveTo,
    updateStory: updateStory,
    addCustom: addCustom,
    storyIdFor: storyIdFor,
    hasId: hasId,
    byId: byId,
    setStatus: setStatus,
    all: all,
    exportFile: exportFile,
  };
})();
