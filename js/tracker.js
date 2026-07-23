'use strict';

/* Tracker page — per-story chronological update timelines for whatever
   has been starred on the Feed page. Reads WatchlistStore (stories) and
   data.storyUpdates (rows appended by scripts/update_stories.py and
   scripts/add_story_update.py) and renders a vertical thread per story. */

(function () {
  var STALE_DAYS = 14;
  var SUGGEST_COUNT = 12;
  var storyUpdates = [];
  var storyImages = [];
  var feedItems = [];
  var lastSuggestions = [];
  var selectedId = null;
  var panelOpen = false;
  var editingId = null;   // story currently open in the inline edit form
  var dragId = null;      // story being dragged in the reorder list

  var esc = Util.esc;

  // Wire an image field group (URL input + file picker + preview + optional
  // Clear) inside a container. File uploads are read as base64 data URLs and
  // written into the URL input, so Save/Add only ever reads one value.
  function wireImageField(container) {
    if (!container) return;
    var urlInput = container.querySelector('[data-ef="image"]');
    var fileInput = container.querySelector('[data-ei="file"]');
    var preview = container.querySelector('[data-ei="preview"]');
    var clearBtn = container.querySelector('[data-ei="clear"]');

    function setPreview(src) {
      if (!preview) return;
      if (src) { preview.src = src; preview.classList.remove('empty'); }
      else { preview.removeAttribute('src'); preview.classList.add('empty'); }
    }

    if (urlInput) {
      urlInput.addEventListener('input', function () { setPreview(urlInput.value.trim()); });
    }
    if (fileInput) {
      fileInput.addEventListener('change', function () {
        var file = fileInput.files && fileInput.files[0];
        if (!file) return;
        var reader = new FileReader();
        reader.onload = function () {
          if (urlInput) urlInput.value = reader.result;
          setPreview(reader.result);
        };
        reader.readAsDataURL(file);
      });
    }
    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        if (urlInput) urlInput.value = '';
        if (fileInput) fileInput.value = '';
        setPreview('');
      });
    }
  }

  function daysSince(dateStr) {
    if (!dateStr) return Infinity;
    var d = new Date(dateStr);
    if (isNaN(d.getTime())) return Infinity;
    return Math.floor((Date.now() - d.getTime()) / 86400000);
  }

  // The date of the most recent NEWS the scrapers actually linked to this story
  // — the newest of its linked feed items and curated updates. This is what
  // staleness should key off (not last_update_at, which the tracker task bumps
  // even when nothing new was found), so a story the feed is actively covering
  // never shows "stale". Memoised per render pass.
  var _lastNewsCache = {};
  function lastNewsAt(story) {
    if (story.story_id in _lastNewsCache) return _lastNewsCache[story.story_id];
    var best = '';
    feedItems.forEach(function (it) {
      if (String(it.linked_story_ids || '').split(';').indexOf(story.story_id) === -1) return;
      var d = (it.created_at || '').slice(0, 10);
      if (d > best) best = d;
    });
    storyUpdates.forEach(function (u) {
      if (u.story_id !== story.story_id) return;
      var d = (u.date || '').slice(0, 10);
      if (d > best) best = d;
    });
    if ((story.last_update_at || '') > best) best = story.last_update_at || '';
    _lastNewsCache[story.story_id] = best;
    return best;
  }

  function statusFor(story) {
    if (story.status === 'resolved') return 'resolved';
    if (story.status === 'archived') return 'archived';
    // Stale ONLY if the scrapers have surfaced nothing for this story in
    // STALE_DAYS — driven by real coverage, not the tracker's bookkeeping.
    if (daysSince(lastNewsAt(story)) > STALE_DAYS) return 'stale';
    return 'active';
  }

  // "3 days ago" / "today" — small provenance tag for a story's freshness.
  function lastNewsLabel(story) {
    var n = daysSince(lastNewsAt(story));
    if (!isFinite(n)) return 'no news yet';
    if (n <= 0) return 'today';
    if (n === 1) return 'yesterday';
    return n + ' days ago';
  }

  // ── Image matching (mirrors home.js findImage) ───────────
  // story_images.csv rows are ordered most-specific first; match on
  // keyword substrings found in the supplied text.
  function findImage(text, usedUrls, countries) {
    var hay = (text || '').toLowerCase();
    var itemCs = (countries || '').toUpperCase().replace(/,/g, ';').split(';')
      .map(function (c) { return c.trim(); }).filter(Boolean);
    for (var i = 0; i < storyImages.length; i++) {
      if (usedUrls && usedUrls.indexOf(storyImages[i].url) !== -1) continue;
      // Country gate (mirrors match_image in enrich_lib.py): a country-tagged
      // image only matches a story sharing one of those countries.
      var rowCs = (storyImages[i].countries || '').toUpperCase().split(';')
        .map(function (c) { return c.trim(); }).filter(Boolean);
      if (rowCs.length && itemCs.length && !rowCs.some(function (c) { return itemCs.indexOf(c) !== -1; })) continue;
      var keys = (storyImages[i].keywords || '').toLowerCase().split(';');
      for (var j = 0; j < keys.length; j++) {
        var k = keys[j].trim();
        if (k && hay.indexOf(k) !== -1) return storyImages[i];
      }
    }
    return null;
  }

  function storyCountries(story) {
    return ((story.seed && story.seed.countries) || []).join(';');
  }

  function storyMatchText(story) {
    var kw = (story.keywords || []).join(' ');
    var countries = (story.seed && story.seed.countries || []).join(' ');
    return (story.title + ' ' + ((story.seed && story.seed.text) || '') + ' ' + kw + ' ' + countries).toLowerCase();
  }

  // Normalise a headline for dedup keys (shared by buildEntries).
  function normHead(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9 ]/g, ' ')
      .replace(/\s+/g, ' ').trim().slice(0, 70);
  }

  // ── Merged story timeline: curated beats + every linked feed tweet ────────
  // Curated story_updates are the hand/agent-authored beats; linked tweets come
  // from linked_story_ids (the whole feed, retroactively) and carry enriched
  // context/sources. We merge, drop near-duplicates (by date|normHead), and sort
  // NEWEST-FIRST. This is the SINGLE source of truth for a story's update list —
  // both the rail count and the timeline header/thread read from it, so the
  // number the rail shows always matches the timeline it opens (previously the
  // rail counted only curated rows and showed 0 for feed-linked-only stories).
  function buildEntries(story) {
    var feedByNorm = {};
    feedItems.forEach(function (it) {
      var fk = (it.created_at || '').slice(0, 10) + '|' + normHead(it.summary || it.full_text);
      if (!feedByNorm[fk]) feedByNorm[fk] = it;
    });

    var seen = {};
    var entries = [];

    // Curated beats first (authoritative — dedup wins over a raw tweet).
    storyUpdates.filter(function (u) { return u.story_id === story.story_id; })
      .forEach(function (u) {
        var head = u.headline || u.summary || '';
        var k = (u.date || '') + '|' + normHead(head);
        if (seen[k]) return;
        seen[k] = 1;
        entries.push({
          date: u.date || '', headline: head, summary: u.summary || '',
          origin: u.origin || 'update', status: u.status || '',
          source_name: u.source_name || '', url: u.url || '',
          feed: (!u.url && feedByNorm[k]) || null,
        });
      });

    // Every linked feed tweet.
    feedItems.filter(function (it) {
      return String(it.linked_story_ids || '').split(';').indexOf(story.story_id) !== -1;
    }).forEach(function (it) {
      var date = (it.created_at || '').slice(0, 10);
      var head = it.summary || it.full_text || '';
      var k = date + '|' + normHead(head);
      if (seen[k]) return;
      seen[k] = 1;
      entries.push({
        date: date, headline: head, summary: '',
        origin: 'feed', status: '', source_name: 'Spectator Index', url: '',
        feed: it,
      });
    });

    // Newest first.
    entries.sort(function (a, b) { return (b.date || '').localeCompare(a.date || ''); });
    return entries;
  }

  function countEntries(story) {
    return buildEntries(story).length;
  }

  // ── Suggested-story detection (clusters from the intel feed) ──────────
  // Mirrors js/home.js hero selection: rank breaking / high-severity recent
  // feed items, dedupe by overlapping country-set or shared subcategory, and
  // drop anything already tracked. Produces a catalog of stories the user can
  // one-click track from the Manage panel. (Ranking helpers live in Util.)

  function buildSuggestions() {
    // Country-set / subcategory stand-ins for everything already tracked, so
    // suggestions never duplicate an existing story.
    var trackedPseudo = WatchlistStore.all().map(function (s) {
      return { subcategory: '', countries: ((s.seed && s.seed.countries) || []).join(';') };
    });

    var candidates = feedItems
      .filter(function (it) { return it.is_breaking === 'TRUE' || (parseInt(it.severity, 10) || 0) >= 4; })
      .slice().sort(function (a, b) { return Util.score(b) - Util.score(a); });

    var picked = [];
    candidates.forEach(function (it) {
      if (picked.length >= SUGGEST_COUNT) return;
      if (WatchlistStore.hasId(WatchlistStore.storyIdFor(it))) return;
      var dup = picked.concat(trackedPseudo).some(function (p) { return Util.sameStory(p, it); });
      if (!dup) picked.push(it);
    });
    return picked;
  }

  function refreshAll() {
    _lastNewsCache = {};
    renderRail();
    renderMain();
    if (panelOpen) renderManagePanel();
  }

  function renderRail() {
    var stories = WatchlistStore.all().slice().sort(function (a, b) {
      return (b.last_update_at || b.marked_at || '').localeCompare(a.last_update_at || a.marked_at || '');
    });
    var rail = document.getElementById('tracker-rail');
    if (!stories.length) {
      rail.innerHTML = '<div class="empty-note">No stories tracked yet.<br>Use <strong>Manage stories</strong> above to add some, or star items on the Feed page.</div>';
      return;
    }
    rail.innerHTML = stories.map(function (s) {
      var st = statusFor(s);
      var count = countEntries(s);
      return (
        '<div class="card tracker-story-item ' + (s.story_id === selectedId ? 'selected' : '') + '" data-id="' + esc(s.story_id) + '">' +
          '<span class="tracker-status ' + st + '">' + st + '</span>' +
          '<div class="story-mini-title" style="margin-top:6px;">' + esc(s.title) + '</div>' +
          '<div class="story-mini-meta"><span>' + count + ' update' + (count === 1 ? '' : 's') + '</span><span class="last-news">news ' + esc(lastNewsLabel(s)) + '</span></div>' +
        '</div>'
      );
    }).join('');
    rail.querySelectorAll('.tracker-story-item').forEach(function (el) {
      el.addEventListener('click', function () {
        selectStory(el.dataset.id, true);
      });
    });
  }

  // Select a story, re-render, and bring its timeline into view. On mobile
  // the rail stacks above the timeline, so clicking a story would otherwise
  // leave the reader looking at the list; scrolling makes the click "go" to
  // the timeline. On desktop it's a no-op scroll (main already visible).
  function selectStory(id, scroll) {
    selectedId = id;
    renderRail();
    renderMain();
    if (scroll) {
      var main = document.getElementById('tracker-main');
      if (main) {
        try { main.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
        catch (e) { main.scrollIntoView(); }
      }
    }
  }

  function renderMain() {
    var main = document.getElementById('tracker-main');
    var story = WatchlistStore.all().filter(function (s) { return s.story_id === selectedId; })[0];
    if (!story) {
      main.innerHTML = '<div class="tracker-empty">Select a tracked story from the left to view its timeline.</div>';
      return;
    }
    var st = statusFor(story);
    // Merged timeline (curated beats + linked feed tweets), newest-first.
    var entries = buildEntries(story);

    // Header hero image — a user-set story.image wins; otherwise the most
    // representative keyword-matched image for the whole story.
    var heroImg = story.image
      ? { url: story.image, label: story.title || '', credit: '' }
      : findImage(storyMatchText(story), [], storyCountries(story));
    // Node thumbnails may repeat down a long timeline, but never on two adjacent
    // nodes (or right under the hero), so the thread stays lively.
    var prevUrl = heroImg ? heroImg.url : null;

    // Resolve the seed back to its enriched feed row so "Show details" opens the
    // same cell on the Feed page.
    var seedFeed = null;
    if (story.seed) {
      seedFeed = FeedItem.findByKey(feedItems, FeedItem.itemKey(story.seed))
        || feedItems.filter(function (it) {
          return (story.seed.tweet_id && it.tweet_id === story.seed.tweet_id)
            || (story.seed.created_at && it.created_at === story.seed.created_at);
        })[0]
        || null;
    }

    var nodes = entries.map(function (e) {
      var nodeCs = (e.feed && e.feed.countries) || storyCountries(story);
      var img = findImage((e.headline || '') + ' ' + (e.summary || ''), prevUrl ? [prevUrl] : [], nodeCs);
      if (img) prevUrl = img.url;
      var det = (e.feed && FeedItem.hasDetails(e.feed)) ? FeedItem.expandHtml(e.feed) : '';
      var sev = (e.feed && e.feed.severity) ? (parseInt(e.feed.severity, 10) || 0) : 0;
      // The whole card jumps to the matching item on the Feed page when this
      // node has a linked feed row.
      var feedUrl = e.feed ? FeedItem.feedUrl(e.feed) : '';
      return (
        '<div class="timeline-node animate-on-scroll"><div class="card timeline-node-card' + (img ? ' has-img' : '') + (feedUrl ? ' clickable' : '') + '"' +
          (feedUrl ? ' data-feed-url="' + esc(feedUrl) + '" title="Open in Feed"' : '') + '>' +
          (img ?
            '<div class="timeline-node-thumb">' +
              '<img src="' + esc(img.url) + '" alt="' + esc(img.label) + '" loading="lazy">' +
            '</div>' : '') +
          '<div class="timeline-node-content">' +
            '<div class="timeline-node-meta">' +
              '<span class="origin-tag">' + esc(e.origin) + '</span>' +
              '<span>' + esc(e.date) + '</span>' +
              (e.status ? '<span>· ' + esc(e.status) + '</span>' : '') +
              (sev >= 4 ? '<span class="node-sev">sev ' + sev + '</span>' : '') +
            '</div>' +
            '<div class="timeline-node-headline">' +
              (e.feed ? '<a class="node-feed-link" href="' + esc(FeedItem.feedUrl(e.feed)) + '" title="Open in Feed">' + esc(e.headline) + '</a>' : esc(e.headline)) +
            '</div>' +
            (e.summary ? '<div class="timeline-node-summary">' + esc(e.summary) + '</div>' : '') +
            (e.source_name || e.url ?
              '<div class="timeline-node-source">' +
                (e.url ? '<a href="' + esc(e.url) + '" target="_blank" rel="noopener">' + esc(e.source_name || e.url) + '</a>' : esc(e.source_name)) +
              '</div>' : '') +
            (det ? FeedItem.toggleBtnHtml(false) + '<div class="feed-expand" data-expand>' + det + '</div>' : '') +
          '</div>' +
        '</div></div>'
      );
    }).join('');

    // Seed pinned at the bottom.
    var seedUrl = (seedFeed && FeedItem.hasDetails(seedFeed)) ? FeedItem.feedUrl(seedFeed) : '';
    nodes += '<div class="timeline-node seed"><div class="card timeline-node-card' + (seedUrl ? ' clickable' : '') + '"' +
      (seedUrl ? ' data-feed-url="' + esc(seedUrl) + '" title="Open in Feed"' : '') + '>' +
      '<div class="timeline-node-meta"><span class="origin-tag">seed</span><span>' + esc(story.seed.created_at || story.marked_at || '') + '</span></div>' +
      '<div class="timeline-node-headline">Marked important</div>' +
      '<div class="timeline-node-summary">' + esc(story.seed.text || '') + '</div>' +
      FeedItem.linkBtnHtml(seedFeed) +
    '</div></div>';

    main.innerHTML =
      '<div class="card tracker-story-header' + (heroImg ? ' has-hero' : '') + '">' +
        (heroImg ?
          '<div class="tracker-story-hero">' +
            '<img src="' + esc(heroImg.url) + '" alt="' + esc(heroImg.label) + '">' +
            (heroImg.credit ? '<span class="tracker-story-hero-credit">' + esc(heroImg.credit) + '</span>' : '') +
          '</div>' : '') +
        '<div class="tracker-story-header-body">' +
          '<span class="tracker-status ' + st + '">' + st + '</span>' +
          '<div class="tracker-story-title">' + esc(story.title) + '</div>' +
          '<div class="story-mini-meta"><span>' + entries.length + ' update' + (entries.length === 1 ? '' : 's') + '</span><span class="last-news">last news ' + esc(lastNewsLabel(story)) + '</span><span>marked ' + esc((story.marked_at || '').slice(0, 10)) + '</span></div>' +
          '<div class="tracker-story-actions">' +
            (story.status !== 'resolved' ? '<button class="tracker-btn" data-action="resolve">Mark resolved</button>' : '<button class="tracker-btn" data-action="reactivate">Reactivate</button>') +
            (story.status !== 'archived' ? '<button class="tracker-btn" data-action="archive">Archive</button>' : '') +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div class="timeline-thread">' + nodes + '</div>';

    // Broken image → drop the thumb/hero and reflow to the text-only layout.
    main.querySelectorAll('.timeline-node-thumb img, .tracker-story-hero img').forEach(function (el) {
      el.addEventListener('error', function () {
        var thumb = el.closest('.timeline-node-thumb');
        if (thumb) {
          var card = thumb.closest('.timeline-node-card');
          if (card) card.classList.remove('has-img');
          thumb.remove();
          return;
        }
        var hero = el.closest('.tracker-story-hero');
        if (hero) {
          var header = hero.closest('.tracker-story-header');
          if (header) header.classList.remove('has-hero');
          hero.remove();
        }
      });
    });

    if (window.Reveal) window.Reveal.scan(main);

    main.querySelectorAll('.tracker-story-actions [data-action]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var action = btn.dataset.action;
        var status = action === 'resolve' ? 'resolved' : action === 'reactivate' ? 'active' : 'archived';
        WatchlistStore.setStatus(story.story_id, status);
        renderRail();
        renderMain();
      });
    });

    // Inline "Show details" expanders on tweet/enriched timeline nodes.
    main.querySelectorAll('.timeline-node .feed-details-btn[data-action="toggle"]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var content = btn.closest('.timeline-node-content');
        var exp = content && content.querySelector('[data-expand]');
        if (!exp) return;
        var open = exp.classList.toggle('open');
        btn.textContent = open ? 'Hide details −' : 'Show details +';
      });
    });

    // Clicking a timeline node opens the matching item on the Feed page.
    // Inner links (source URLs, headline anchor) and the Show-details toggle
    // keep their own behaviour — don't hijack those clicks.
    main.querySelectorAll('.timeline-node-card.clickable').forEach(function (card) {
      card.addEventListener('click', function (e) {
        if (e.target.closest('a, button, .feed-details-btn')) return;
        var url = card.dataset.feedUrl;
        if (url) window.location.href = url;
      });
    });
  }

  // ── Manage-stories panel ─────────────────────────────────────────────
  function statusCycleLabel(status) {
    if (status === 'resolved') return 'Reactivate';
    if (status === 'archived') return 'Reactivate';
    return 'Resolve';
  }

  function renderManagePanel() {
    var panel = document.getElementById('manage-panel');
    if (!panel) return;
    panel.hidden = !panelOpen;
    if (!panelOpen) { panel.innerHTML = ''; return; }

    // Priority order (array position) — this is what the reorder controls and
    // the main page tile sizes follow, so DON'T re-sort here.
    var tracked = WatchlistStore.all().slice();
    lastSuggestions = buildSuggestions();
    var suggestions = lastSuggestions;

    function editFormHtml(s) {
      var kw = (s.keywords || []).join(', ');
      var cs = ((s.seed && s.seed.countries) || []).join(', ');
      var img = s.image || '';
      return (
        '<div class="manage-edit" data-id="' + esc(s.story_id) + '">' +
          '<input type="text" data-ef="title" value="' + esc(s.title) + '" placeholder="Title">' +
          '<textarea data-ef="text" rows="2" placeholder="Seed / what to watch">' + esc((s.seed && s.seed.text) || '') + '</textarea>' +
          '<div class="manage-form-row">' +
            '<input type="text" data-ef="keywords" value="' + esc(kw) + '" placeholder="keywords, comma-separated">' +
            '<input type="text" data-ef="countries" value="' + esc(cs) + '" placeholder="country codes e.g. US, CN">' +
          '</div>' +
          '<div class="manage-image-field">' +
            '<img class="manage-image-preview' + (img ? '' : ' empty') + '" data-ei="preview" src="' + esc(img) + '" alt="">' +
            '<div class="manage-image-inputs">' +
              '<input type="text" data-ef="image" value="' + esc(img) + '" placeholder="Image URL (or upload →)">' +
              '<label class="tracker-btn manage-upload-btn">Upload<input type="file" accept="image/*" data-ei="file" hidden></label>' +
              (img ? '<button type="button" class="tracker-btn" data-ei="clear">Clear</button>' : '') +
            '</div>' +
          '</div>' +
          '<div class="manage-edit-actions">' +
            '<button class="tracker-btn primary" data-mact="save">Save</button>' +
            '<button class="tracker-btn" data-mact="cancel">Cancel</button>' +
          '</div>' +
        '</div>'
      );
    }

    var trackedHtml = tracked.length ? tracked.map(function (s, i) {
      var st = statusFor(s);
      if (editingId === s.story_id) return editFormHtml(s);
      return (
        '<div class="manage-row" data-id="' + esc(s.story_id) + '" draggable="true">' +
          '<span class="drag-handle" title="Drag to reorder">⠿</span>' +
          '<span class="reorder-btns">' +
            '<button class="reorder-btn" data-mact="up" title="Move up"' + (i === 0 ? ' disabled' : '') + '>▲</button>' +
            '<button class="reorder-btn" data-mact="down" title="Move down"' + (i === tracked.length - 1 ? ' disabled' : '') + '>▼</button>' +
          '</span>' +
          '<span class="manage-prio" title="Priority">' + (i + 1) + '</span>' +
          '<span class="tracker-status ' + st + '">' + st + '</span>' +
          '<span class="manage-row-title">' + esc(s.title) + (s.custom ? ' <span class="manage-tag">custom</span>' : '') + '</span>' +
          '<span class="manage-row-actions">' +
            '<button class="tracker-btn" data-mact="edit">Edit</button>' +
            '<button class="tracker-btn" data-mact="status">' + statusCycleLabel(s.status) + '</button>' +
            (s.status !== 'archived' ? '<button class="tracker-btn" data-mact="archive">Archive</button>' : '') +
            '<button class="tracker-btn danger" data-mact="remove">Remove</button>' +
          '</span>' +
        '</div>'
      );
    }).join('') : '<div class="manage-empty">Nothing tracked yet.</div>';

    var suggestHtml = suggestions.length ? suggestions.map(function (it) {
      var id = WatchlistStore.storyIdFor(it);
      var cats = (it.countries || '').split(';').map(function (c) { return c.trim(); }).filter(Boolean).join(' · ');
      return (
        '<div class="suggest-card" data-key="' + esc(id) + '">' +
          '<div class="suggest-meta">' +
            '<span class="' + ('pill pill-' + (it.category || 'social').toLowerCase()) + '">' + esc(it.category || 'social') + '</span>' +
            (it.is_breaking === 'TRUE' ? '<span class="pill pill-military">breaking</span>' : '') +
            (cats ? '<span class="suggest-countries">' + esc(cats) + '</span>' : '') +
          '</div>' +
          '<div class="suggest-title">' + esc(it.summary || it.full_text || '') + '</div>' +
          '<button class="tracker-btn primary" data-sact="track">+ Track this story</button>' +
        '</div>'
      );
    }).join('') : '<div class="manage-empty">No new suggestions right now — everything notable is already tracked.</div>';

    panel.innerHTML =
      '<div class="manage-inner">' +
        '<div class="manage-section">' +
          '<div class="manage-head">Tracked stories (' + tracked.length + ')</div>' +
          '<div class="manage-list">' + trackedHtml + '</div>' +
        '</div>' +
        '<div class="manage-section">' +
          '<div class="manage-head">Suggested from the feed</div>' +
          '<div class="suggest-grid">' + suggestHtml + '</div>' +
        '</div>' +
        '<div class="manage-section">' +
          '<div class="manage-head">Add your own</div>' +
          '<form class="manage-form" id="add-story-form">' +
            '<input type="text" name="title" placeholder="Story title (required)" required>' +
            '<textarea name="text" placeholder="Short description / what to watch (optional)" rows="2"></textarea>' +
            '<div class="manage-form-row">' +
              '<input type="text" name="keywords" placeholder="keywords, comma-separated">' +
              '<input type="text" name="countries" placeholder="country codes e.g. US, CN">' +
            '</div>' +
            '<div class="manage-image-field">' +
              '<img class="manage-image-preview empty" data-ei="preview" src="" alt="">' +
              '<div class="manage-image-inputs">' +
                '<input type="text" name="image" data-ef="image" placeholder="Image URL (or upload →)">' +
                '<label class="tracker-btn manage-upload-btn">Upload<input type="file" accept="image/*" data-ei="file" hidden></label>' +
              '</div>' +
            '</div>' +
            '<button type="submit" class="tracker-btn primary">+ Add story</button>' +
          '</form>' +
        '</div>' +
      '</div>';

    // Tracked-row actions (status / archive / remove / edit / reorder)
    panel.querySelectorAll('.manage-row').forEach(function (row) {
      var id = row.dataset.id;
      row.querySelectorAll('[data-mact]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var act = btn.dataset.mact;
          if (act === 'remove') {
            WatchlistStore.removeById(id);
            if (selectedId === id) selectedId = (WatchlistStore.all()[0] || {}).story_id || null;
          } else if (act === 'archive') {
            WatchlistStore.setStatus(id, 'archived');
          } else if (act === 'status') {
            var s = WatchlistStore.all().filter(function (x) { return x.story_id === id; })[0];
            var next = (s && (s.status === 'active')) ? 'resolved' : 'active';
            WatchlistStore.setStatus(id, next);
          } else if (act === 'up') {
            WatchlistStore.moveBy(id, -1);
          } else if (act === 'down') {
            WatchlistStore.moveBy(id, 1);
          } else if (act === 'edit') {
            editingId = id;
          }
          refreshAll();
        });
      });

      // Drag-and-drop reorder. Dropping onto a row moves the dragged story to
      // that row's index; array position is the persisted priority.
      row.addEventListener('dragstart', function (e) {
        dragId = id;
        row.classList.add('dragging');
        try { e.dataTransfer.effectAllowed = 'move'; } catch (err) { /* noop */ }
      });
      row.addEventListener('dragend', function () {
        dragId = null;
        row.classList.remove('dragging');
      });
      row.addEventListener('dragover', function (e) {
        e.preventDefault();
        row.classList.add('drag-over');
      });
      row.addEventListener('dragleave', function () { row.classList.remove('drag-over'); });
      row.addEventListener('drop', function (e) {
        e.preventDefault();
        row.classList.remove('drag-over');
        if (!dragId || dragId === id) return;
        var ids = WatchlistStore.all().map(function (s) { return s.story_id; });
        WatchlistStore.moveTo(dragId, ids.indexOf(id));
        refreshAll();
      });
    });

    // Inline edit form actions
    panel.querySelectorAll('.manage-edit').forEach(function (box) {
      var id = box.dataset.id;
      wireImageField(box);
      box.querySelectorAll('[data-mact]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          if (btn.dataset.mact === 'save') {
            WatchlistStore.updateStory(id, {
              title: (box.querySelector('[data-ef="title"]') || {}).value,
              text: (box.querySelector('[data-ef="text"]') || {}).value,
              keywords: (box.querySelector('[data-ef="keywords"]') || {}).value,
              countries: (box.querySelector('[data-ef="countries"]') || {}).value,
              image: (box.querySelector('[data-ef="image"]') || {}).value,
            });
          }
          editingId = null;
          refreshAll();
        });
      });
    });

    // Suggestion "Track" buttons
    panel.querySelectorAll('.suggest-card').forEach(function (card) {
      var id = card.dataset.key;
      var btn = card.querySelector('[data-sact="track"]');
      if (!btn) return;
      btn.addEventListener('click', function () {
        // Use the exact item the card was built from (same story_id can map to
        // several feed rows; re-looking-up by id could grab a different one).
        var it = lastSuggestions.filter(function (x) { return WatchlistStore.storyIdFor(x) === id; })[0]
          || feedItems.filter(function (x) { return WatchlistStore.storyIdFor(x) === id; })[0];
        if (!it) return;
        var story = WatchlistStore.trackItem(it);
        selectedId = story.story_id;
        refreshAll();
      });
    });

    // Add-your-own form
    var form = panel.querySelector('#add-story-form');
    if (form) {
      wireImageField(form);
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var fd = new FormData(form);
        var story = WatchlistStore.addCustom({
          title: fd.get('title'),
          text: fd.get('text'),
          keywords: fd.get('keywords'),
          countries: fd.get('countries'),
          image: fd.get('image'),
        });
        if (story) {
          selectedId = story.story_id;
          form.reset();
          refreshAll();
        }
      });
    }
  }

  function toggleManagePanel(force) {
    panelOpen = (typeof force === 'boolean') ? force : !panelOpen;
    var btn = document.getElementById('manage-toggle-btn');
    if (btn) btn.textContent = panelOpen ? 'Close manager' : 'Manage stories';
    renderManagePanel();
  }

  function requestedStoryId() {
    try {
      var params = new URLSearchParams(window.location.search);
      return params.get('story');
    } catch (e) {
      return null;
    }
  }

  DataLayer.loadFeed().then(function (data) {
    WatchlistStore.init(data.watchlist);
    storyUpdates = data.storyUpdates || [];
    storyImages = data.storyImages || [];
    feedItems = (data.tweetEnriched || []).slice().sort(function (a, b) {
      return (b.created_at || '').localeCompare(a.created_at || '');
    });
    var stories = WatchlistStore.all();

    // Deep link: ?story=<id> from a tracked hero tile takes you straight to
    // that story's timeline. Falls back to the most recently updated story.
    var requested = requestedStoryId();
    var deepLinked = requested && stories.some(function (s) { return s.story_id === requested; });

    if (deepLinked) {
      selectedId = requested;
    } else if (stories.length) {
      selectedId = stories.slice().sort(function (a, b) {
        return (b.last_update_at || b.marked_at || '').localeCompare(a.last_update_at || a.marked_at || '');
      })[0].story_id;
    }

    renderRail();
    renderMain();

    // If arrived via deep link, scroll the timeline into view once painted.
    if (deepLinked) {
      requestAnimationFrame(function () {
        var main = document.getElementById('tracker-main');
        if (main) {
          try { main.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
          catch (e) { main.scrollIntoView(); }
        }
      });
    }

    var exportBtn = document.getElementById('export-watchlist-btn');
    if (exportBtn) exportBtn.addEventListener('click', function () { WatchlistStore.exportFile(); });

    var manageBtn = document.getElementById('manage-toggle-btn');
    if (manageBtn) manageBtn.addEventListener('click', function () { toggleManagePanel(); });

    // Open the manager automatically when there's nothing to show yet.
    if (!stories.length) toggleManagePanel(true);
  }).catch(function (err) {
    console.error('Failed to load tracker data:', err);
    document.getElementById('tracker-main').innerHTML =
      '<div class="empty-note">Failed to load data: ' + err.message + '</div>';
  });
})();
