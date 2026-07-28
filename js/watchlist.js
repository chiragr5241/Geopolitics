'use strict';

/* =========================================================
   WATCHLIST STORE — the story CATALOG plus one user's view of it.

   The v1 store kept a full copy of every story per user, which is what a
   single-user site can get away with and a many-user site cannot: the
   pipeline's work (timeline beats, hero images, linked tweets, enrichment)
   is identical for everyone, so copying it per user duplicates the
   expensive part and makes "which story is this, really" ambiguous.

   So the data splits in two:

     CATALOG  (shared, pipeline-owned — data/watchlist.json → database.json)
       The story records themselves: title, seed, keywords, query_hints,
       image. One copy. update_stories.py / link_stories.py / add_story_*.py
       all keep working against exactly this, unchanged.

     USER DOC (per person, tiny — UserStore, keyed by user id)
       { follows: [story_id…]   ← membership AND priority order
         own:     [story…]      ← stories this user authored, not yet published
         overrides: { story_id: {title?, image?, status?, …} } }

   A user's page is the catalog filtered and ordered by their own doc. That
   is what makes the design scale: adding the ten-thousandth user costs one
   small document of ids, not another copy of every story. It is also what
   makes each page genuinely custom — two users following the same story see
   the same timeline but their own ordering, status, and edits.

   The public API below is unchanged from v1 on purpose, so home.js,
   tracker.js and feed.js didn't need rewriting; `follow`/`unfollow`/
   `catalogAvailable` are the additions the catalog model needs.
   ========================================================= */

var WatchlistStore = (function () {
  var DOC_NAME = 'watchlist';
  var DOC_VERSION = 2;

  var catalog = [];        // shared story records
  var catalogById = {};
  var doc = null;          // this user's overlay
  var ownById = {};
  var userId = null;
  var _resolved = null;    // memoized all(), invalidated on every write

  function nowIso() {
    return new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  }

  function emptyDoc() {
    return {
      version: DOC_VERSION,
      user_id: userId,
      updated_at: nowIso(),
      follows: [],
      own: [],
      overrides: {},
    };
  }

  function save() {
    doc.updated_at = nowIso();
    _resolved = null;
    if (typeof UserStore !== 'undefined') UserStore.save(userId, DOC_NAME, doc);
  }

  function reindexOwn() {
    ownById = {};
    (doc.own || []).forEach(function (s) { if (s && s.story_id) ownById[s.story_id] = s; });
  }

  /* ── Resolving a story = catalog (or own) record + this user's overrides ── */

  function resolve(id) {
    var base = catalogById[id] || ownById[id];
    if (!base) return null;
    var ov = doc.overrides[id];
    if (!ov) return base;
    var out = {};
    for (var k in base) { if (Object.prototype.hasOwnProperty.call(base, k)) out[k] = base[k]; }
    if (ov.title != null) out.title = ov.title;
    if (ov.image != null) out.image = ov.image;
    // An EMPTY override array is not an override — [] is truthy in JS, so the
    // old check let a user who saved the edit box with the keywords field blank
    // pin an empty list on top of the catalog's, which hides the routine's
    // metadata enhancement and (via exportFile → import_watchlist.py) can wipe
    // it from the shared catalog. Empty means "I didn't set this".
    if (ov.keywords && ov.keywords.length) out.keywords = ov.keywords;
    if (ov.status) out.status = ov.status;
    if (ov.resolved_at !== undefined) out.resolved_at = ov.resolved_at;
    if (ov.notes != null) out.notes = ov.notes;
    if (ov.parent_id !== undefined) out.parent_id = ov.parent_id;
    if (ov.edited_at) out.edited_at = ov.edited_at;
    // Which sources this story is researched with is per-person, like the
    // title: one user muting Al Jazeera on a story must not mute it for
    // everyone else following the same story.
    if (ov.sources) out.sources = ov.sources;
    if (ov.text != null || (ov.countries && ov.countries.length)) {
      var seed = {};
      var bs = base.seed || {};
      for (var j in bs) { if (Object.prototype.hasOwnProperty.call(bs, j)) seed[j] = bs[j]; }
      if (ov.text != null) seed.text = ov.text;
      if (ov.countries && ov.countries.length) seed.countries = ov.countries;
      out.seed = seed;
    }
    return out;
  }

  function setOverride(id, patch) {
    var ov = doc.overrides[id] || (doc.overrides[id] = {});
    for (var k in patch) { if (Object.prototype.hasOwnProperty.call(patch, k)) ov[k] = patch[k]; }
    return ov;
  }

  /* ── Migration ─────────────────────────────────────────────────────────
     v1 docs held whole story records. Split each one: keep the id (and its
     position, which is the user's priority) in `follows`, park anything the
     catalog doesn't know about in `own`, and record only what the user
     actually changed as an override. */

  function migrateV1(old) {
    var d = emptyDoc();
    (old.stories || []).forEach(function (s) {
      if (!s || !s.story_id || d.follows.indexOf(s.story_id) !== -1) return;
      d.follows.push(s.story_id);
      var cat = catalogById[s.story_id];
      if (!cat) { d.own.push(s); return; }
      var ov = {};
      if (s.status && s.status !== cat.status) ov.status = s.status;
      if ((s.resolved_at || null) !== (cat.resolved_at || null)) ov.resolved_at = s.resolved_at || null;
      if (s.notes) ov.notes = s.notes;
      if (s.parent_id) ov.parent_id = s.parent_id;
      // Only a genuine local edit (stamped by v1's updateStory) overrides the
      // catalog's own text/image — otherwise a stale copy would pin itself.
      if (s.edited_at) {
        if (s.title !== cat.title) ov.title = s.title;
        if ((s.image || '') !== (cat.image || '')) ov.image = s.image || '';
        if ((s.seed && s.seed.text) !== (cat.seed && cat.seed.text)) ov.text = (s.seed && s.seed.text) || '';
        ov.keywords = s.keywords || [];
        ov.countries = (s.seed && s.seed.countries) || [];
        ov.edited_at = s.edited_at;
      }
      if (Object.keys(ov).length) d.overrides[s.story_id] = ov;
    });
    return d;
  }

  // A brand-new profile starts by following the catalog's active stories, so
  // their first visit shows a working page rather than an empty one. From
  // that moment the list is theirs: unfollowing, reordering and editing
  // affect only them.
  function seedForNewUser() {
    var d = emptyDoc();
    catalog.forEach(function (s) {
      if (s && s.story_id && s.status === 'active') d.follows.push(s.story_id);
    });
    return d;
  }

  /* ── Init ─────────────────────────────────────────────────────────────── */

  function init(catalogStories) {
    catalog = (catalogStories || []).slice();
    catalogById = {};
    catalog.forEach(function (s) { if (s && s.story_id) catalogById[s.story_id] = s; });

    userId = (typeof Session !== 'undefined') ? Session.currentId() : 'local';

    var stored = (typeof UserStore !== 'undefined') ? UserStore.load(userId, DOC_NAME) : null;
    if (stored && stored.version === DOC_VERSION) {
      doc = stored;
      doc.follows = doc.follows || [];
      doc.own = doc.own || [];
      doc.overrides = doc.overrides || {};
    } else if (stored && stored.stories) {
      doc = migrateV1(stored);           // v1 → v2, in place, once
    } else {
      doc = seedForNewUser();
    }
    doc.user_id = userId;

    // A story the user authored that has since been published lives in the
    // catalog now — drop the local copy so the pipeline's enriched version
    // (images, updated fields) wins. Their overrides still apply.
    doc.own = (doc.own || []).filter(function (s) { return s && s.story_id && !catalogById[s.story_id]; });
    reindexOwn();

    // Follows pointing at nothing (story deleted from the catalog upstream)
    // would render as holes — drop them.
    doc.follows = doc.follows.filter(function (id) { return !!(catalogById[id] || ownById[id]); });

    save();
    return doc;
  }

  /* ── Ids ──────────────────────────────────────────────────────────────── */

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

  /* ── Reads ────────────────────────────────────────────────────────────── */

  // The user's stories, in their priority order (array position = priority).
  function all() {
    if (_resolved) return _resolved;
    _resolved = doc.follows.map(resolve).filter(Boolean);
    return _resolved;
  }

  function isFollowing(id) {
    return doc.follows.indexOf(id) !== -1;
  }

  // `hasId` means "on this user's list" — that's what the Feed's Track toggle
  // and the suggestion filter mean by it.
  function hasId(id) {
    return isFollowing(id);
  }

  function byId(id) {
    return isFollowing(id) ? resolve(id) : null;
  }

  // Catalog stories this user isn't following — the discovery list. Without
  // it, anything a user unfollows (or that another user publishes later)
  // would be unreachable from their page.
  function catalogAvailable() {
    return catalog.filter(function (s) {
      return s && s.story_id && !isFollowing(s.story_id);
    });
  }

  function findByTweet(item) {
    return all().filter(function (s) {
      return s.seed && s.seed.tweet_id && item.tweet_id && s.seed.tweet_id === item.tweet_id;
    })[0];
  }

  // A feed item counts as "marked" if either its tweet is the seed of a story
  // or a story already exists for the story_id it would generate — so the Feed
  // star and the Tracker catalog stay in sync on the same underlying story.
  function isMarked(item) {
    return !!findByTweet(item) || hasId(storyIdFor(item));
  }

  /* ── Follow / unfollow ────────────────────────────────────────────────── */

  function follow(id, atTop) {
    if (!id || isFollowing(id)) return false;
    if (!catalogById[id] && !ownById[id]) return false;
    if (atTop) doc.follows.unshift(id); else doc.follows.push(id);
    save();
    return true;
  }

  function unfollow(id) {
    if (!isFollowing(id)) return false;
    doc.follows = doc.follows.filter(function (x) { return x !== id; });
    // A story only this user had is theirs to discard entirely; a catalog
    // story stays in the catalog for everyone else, just off their list.
    if (ownById[id]) {
      doc.own = doc.own.filter(function (s) { return s.story_id !== id; });
      reindexOwn();
      delete doc.overrides[id];
    }
    save();
    return true;
  }

  /* ── Writes ───────────────────────────────────────────────────────────── */

  // Sources for a brand-new story: all of them. An empty block (registry not
  // loaded yet) is equivalent — effectiveFor() treats "no exclusions" as
  // "everything", so nothing is lost either way.
  function defaultSources() {
    if (typeof SourceRegistry === 'undefined') return { selected: [], excluded: [], added: [] };
    return SourceRegistry.defaultSelection();
  }

  // Normalise whatever a form hands us into the stored shape.
  function cleanSources(sel) {
    if (!sel || typeof sel !== 'object') return null;
    return {
      selected: (sel.selected || []).filter(Boolean),
      excluded: (sel.excluded || []).filter(Boolean),
      added: (sel.added || []).filter(function (a) { return a && a.input; })
        .map(function (a) {
          return {
            input: String(a.input),
            source_id: a.source_id || '',
            status: a.status || 'unverified',
            resolved_name: a.resolved_name || '',
          };
        }),
    };
  }

  // Set a story's source selection. Like every other edit, on a catalog story
  // this is a personal override; on the user's own draft it writes through.
  function setSources(id, sel) {
    if (!isFollowing(id)) return null;
    var clean = cleanSources(sel);
    if (!clean) return null;
    var own = ownById[id];
    if (own) own.sources = clean;
    else setOverride(id, { sources: clean });
    save();
    return resolve(id);
  }

  // Build a full story record from a feed/enriched item.
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
      created_by: userId,
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
      // Every source, selected — the same default the Add-story form shows.
      sources: defaultSources(),
    };
  }

  // Track a feed/suggested item. Idempotent — if the story is already in the
  // catalog, this just follows it rather than making a second copy of it.
  function trackItem(item) {
    var existing = findByTweet(item);
    if (existing) return existing;
    var id = storyIdFor(item);
    if (isFollowing(id)) return resolve(id);
    if (catalogById[id]) { follow(id); return resolve(id); }
    var story = buildStory(item);
    doc.own.push(story);
    reindexOwn();
    doc.follows.push(story.story_id);
    save();
    return story;
  }

  // Sub-track: seed a CHILD story from a feed item, linked to a parent story via
  // `parent_id`. Barebones scaffolding for a future "sub-thread" feature — a child
  // is a normal tracked story that also records which story it branched from.
  function addSubTrack(parentId, item) {
    var story = trackItem(item);
    if (!story) return null;
    if (!story.parent_id) setOverride(story.story_id, { parent_id: parentId });
    save();
    return resolve(story.story_id);
  }

  // All stories that branched from a given parent story.
  function childrenOf(parentId) {
    return all().filter(function (s) { return s.parent_id === parentId; });
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
    while (catalogById[id] || ownById[id]) { id = base + '-' + n; n++; }
    var countries = (fields.countries || '')
      .split(/[,;]/).map(function (c) { return c.trim().toUpperCase(); }).filter(Boolean);
    var keywords = (fields.keywords || '')
      .split(/[,;]/).map(function (k) { return k.trim().toLowerCase(); }).filter(Boolean);
    var story = {
      story_id: id,
      status: 'active',
      title: title.slice(0, 120),
      marked_at: nowIso(),
      created_by: userId,
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
      sources: cleanSources(fields.sources) || defaultSources(),
    };
    doc.own.push(story);
    reindexOwn();
    doc.follows.push(id);
    save();
    return story;
  }

  function removeById(id) {
    unfollow(id);
  }

  function indexOf(id) {
    return doc.follows.indexOf(id);
  }

  // Priority reorder. Array position IS the priority (top = highest), so both
  // the ▲/▼ nudge and drag-to-index just splice the list and persist.
  function moveBy(id, delta) {
    var i = indexOf(id);
    if (i < 0) return;
    var j = i + delta;
    if (j < 0 || j >= doc.follows.length) return;
    var tmp = doc.follows[i];
    doc.follows[i] = doc.follows[j];
    doc.follows[j] = tmp;
    save();
  }

  function moveTo(id, index) {
    var i = indexOf(id);
    if (i < 0) return;
    var moved = doc.follows.splice(i, 1)[0];
    index = Math.max(0, Math.min(index, doc.follows.length));
    doc.follows.splice(index, 0, moved);
    save();
  }

  // Edit a story's user-facing fields. On a catalog story this records a
  // personal override — the shared record is untouched, so one user's retitle
  // doesn't rewrite the story for everyone.
  function updateStory(id, fields) {
    if (!isFollowing(id)) return null;
    fields = fields || {};
    var own = ownById[id];
    var patch = {};
    if (fields.title != null) patch.title = String(fields.title).trim().slice(0, 140);
    if (fields.text != null) patch.text = String(fields.text).trim();
    if (fields.keywords != null) {
      patch.keywords = String(fields.keywords).split(/[,;]/)
        .map(function (k) { return k.trim().toLowerCase(); }).filter(Boolean).slice(0, 12);
    }
    if (fields.countries != null) {
      patch.countries = String(fields.countries).split(/[,;]/)
        .map(function (c) { return c.trim().toUpperCase(); }).filter(Boolean);
    }
    // A URL or a data: base64 string. Empty string clears the custom image.
    if (fields.image != null) patch.image = String(fields.image).trim();
    if (fields.sources != null) patch.sources = cleanSources(fields.sources);
    patch.edited_at = nowIso();

    if (own) {
      // The user owns this record outright — write through instead of stacking
      // an override on top of their own draft.
      if (patch.title != null) own.title = patch.title;
      if (patch.image != null) own.image = patch.image;
      if (patch.keywords) own.keywords = patch.keywords;
      if (patch.sources) own.sources = patch.sources;
      if (patch.text != null || patch.countries) {
        own.seed = own.seed || {};
        if (patch.text != null) own.seed.text = patch.text;
        if (patch.countries) own.seed.countries = patch.countries;
      }
      own.edited_at = patch.edited_at;
    } else {
      setOverride(id, patch);
    }
    save();
    return resolve(id);
  }

  function unmark(item) {
    var story = findByTweet(item) || byId(storyIdFor(item));
    if (!story) return;
    unfollow(story.story_id);
  }

  function toggle(item) {
    return isMarked(item) ? (unmark(item), false) : (trackItem(item), true);
  }

  function setStatus(storyId, status) {
    if (!isFollowing(storyId)) return;
    var own = ownById[storyId];
    var resolvedAt = status === 'resolved' ? nowIso() : (status === 'active' ? null : undefined);
    if (own) {
      own.status = status;
      if (resolvedAt !== undefined) own.resolved_at = resolvedAt;
    } else {
      var patch = { status: status };
      if (resolvedAt !== undefined) patch.resolved_at = resolvedAt;
      setOverride(storyId, patch);
    }
    save();
  }

  /* ── Publishing ───────────────────────────────────────────────────────
     Export writes the CATALOG shape the Python pipeline already reads
     (scripts/import_watchlist.py → data/watchlist.json), so none of it has
     to change. It's an owner action: a member's personal list is not the
     shared catalog, and committing one would prune everyone else's stories.
     When the backend lands this goes away — the server owns the catalog and
     writes it directly. */

  function exportFile() {
    var stories = all().map(function (s) {
      var copy = {};
      for (var k in s) { if (Object.prototype.hasOwnProperty.call(s, k)) copy[k] = s[k]; }
      return copy;
    });
    var out = { version: 1, updated_at: nowIso(), stories: stories };
    var blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' });
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
    setSources: setSources,
    addCustom: addCustom,
    storyIdFor: storyIdFor,
    hasId: hasId,
    byId: byId,
    setStatus: setStatus,
    all: all,
    exportFile: exportFile,
    // Catalog model additions
    follow: follow,
    unfollow: unfollow,
    isFollowing: isFollowing,
    catalogAvailable: catalogAvailable,
  };
})();
