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

  function esc(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function daysSince(dateStr) {
    if (!dateStr) return Infinity;
    var d = new Date(dateStr);
    if (isNaN(d.getTime())) return Infinity;
    return Math.floor((Date.now() - d.getTime()) / 86400000);
  }

  function statusFor(story) {
    if (story.status === 'resolved') return 'resolved';
    if (story.status === 'archived') return 'archived';
    if (daysSince(story.last_update_at) > STALE_DAYS) return 'stale';
    return 'active';
  }

  // ── Image matching (mirrors home.js findImage) ───────────
  // story_images.csv rows are ordered most-specific first; match on
  // keyword substrings found in the supplied text.
  function findImage(text, usedUrls) {
    var hay = (text || '').toLowerCase();
    for (var i = 0; i < storyImages.length; i++) {
      if (usedUrls && usedUrls.indexOf(storyImages[i].url) !== -1) continue;
      var keys = (storyImages[i].keywords || '').toLowerCase().split(';');
      for (var j = 0; j < keys.length; j++) {
        var k = keys[j].trim();
        if (k && hay.indexOf(k) !== -1) return storyImages[i];
      }
    }
    return null;
  }

  function storyMatchText(story) {
    var kw = (story.keywords || []).join(' ');
    var countries = (story.seed && story.seed.countries || []).join(' ');
    return (story.title + ' ' + ((story.seed && story.seed.text) || '') + ' ' + kw + ' ' + countries).toLowerCase();
  }

  // ── Suggested-story detection (clusters from the intel feed) ──────────
  // Mirrors js/home.js hero selection: rank breaking / high-severity recent
  // feed items, dedupe by overlapping country-set or shared subcategory, and
  // drop anything already tracked. Produces a catalog of stories the user can
  // one-click track from the Manage panel.
  function countrySet(it) {
    return (it.countries || '').split(';').map(function (c) { return c.trim(); }).filter(Boolean);
  }

  function jaccard(a, b) {
    if (!a.length || !b.length) return 0;
    var inter = a.filter(function (x) { return b.indexOf(x) !== -1; }).length;
    return inter / (a.length + b.length - inter);
  }

  function sameStory(a, b) {
    if (a.subcategory && a.subcategory === b.subcategory) return true;
    return jaccard(countrySet(a), countrySet(b)) >= 0.5;
  }

  function ageDays(ts) {
    var d = new Date((ts || '').replace(' ', 'T') + 'Z');
    if (isNaN(d.getTime())) return 999;
    return (Date.now() - d.getTime()) / 86400000;
  }

  function score(it) {
    var sev = parseInt(it.severity, 10) || 0;
    return sev * 2 + (it.is_breaking === 'TRUE' ? 3 : 0) - ageDays(it.created_at) * 0.6;
  }

  function buildSuggestions() {
    // Country-set / subcategory stand-ins for everything already tracked, so
    // suggestions never duplicate an existing story.
    var trackedPseudo = WatchlistStore.all().map(function (s) {
      return { subcategory: '', countries: ((s.seed && s.seed.countries) || []).join(';') };
    });

    var candidates = feedItems
      .filter(function (it) { return it.is_breaking === 'TRUE' || (parseInt(it.severity, 10) || 0) >= 4; })
      .slice().sort(function (a, b) { return score(b) - score(a); });

    var picked = [];
    candidates.forEach(function (it) {
      if (picked.length >= SUGGEST_COUNT) return;
      if (WatchlistStore.hasId(WatchlistStore.storyIdFor(it))) return;
      var dup = picked.concat(trackedPseudo).some(function (p) { return sameStory(p, it); });
      if (!dup) picked.push(it);
    });
    return picked;
  }

  function refreshAll() {
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
      var count = storyUpdates.filter(function (u) { return u.story_id === s.story_id; }).length;
      return (
        '<div class="card tracker-story-item ' + (s.story_id === selectedId ? 'selected' : '') + '" data-id="' + esc(s.story_id) + '">' +
          '<span class="tracker-status ' + st + '">' + st + '</span>' +
          '<div class="story-mini-title" style="margin-top:6px;">' + esc(s.title) + '</div>' +
          '<div class="story-mini-meta"><span>' + count + ' update' + (count === 1 ? '' : 's') + '</span><span>last: ' + (s.last_update_at || '—') + '</span></div>' +
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
    var updates = storyUpdates
      .filter(function (u) { return u.story_id === story.story_id; })
      .sort(function (a, b) { return (a.date || '').localeCompare(b.date || ''); });

    // Header hero image — the most representative image for the whole story.
    var heroImg = findImage(storyMatchText(story), []);

    // Node thumbnails may repeat down a long timeline, but never on two
    // adjacent nodes (or right under the hero), so the thread stays lively
    // without a wall of the same photo.
    var prevUrl = heroImg ? heroImg.url : null;

    var nodes = '<div class="timeline-node seed"><div class="card timeline-node-card">' +
      '<div class="timeline-node-meta"><span class="origin-tag">seed</span><span>' + esc(story.seed.created_at || story.marked_at || '') + '</span></div>' +
      '<div class="timeline-node-headline">Marked important</div>' +
      '<div class="timeline-node-summary">' + esc(story.seed.text || '') + '</div>' +
    '</div></div>';

    nodes += updates.map(function (u) {
      var img = findImage(((u.headline || '') + ' ' + (u.summary || '')), prevUrl ? [prevUrl] : []);
      if (img) prevUrl = img.url;
      return (
        '<div class="timeline-node"><div class="card timeline-node-card' + (img ? ' has-img' : '') + '">' +
          (img ?
            '<div class="timeline-node-thumb">' +
              '<img src="' + esc(img.url) + '" alt="' + esc(img.label) + '" loading="lazy">' +
            '</div>' : '') +
          '<div class="timeline-node-content">' +
            '<div class="timeline-node-meta">' +
              '<span class="origin-tag">' + esc(u.origin || 'update') + '</span>' +
              '<span>' + esc(u.date) + '</span>' +
              (u.status ? '<span>· ' + esc(u.status) + '</span>' : '') +
            '</div>' +
            '<div class="timeline-node-headline">' + esc(u.headline) + '</div>' +
            '<div class="timeline-node-summary">' + esc(u.summary || '') + '</div>' +
            (u.source_name || u.url ?
              '<div class="timeline-node-source">' +
                (u.url ? '<a href="' + esc(u.url) + '" target="_blank" rel="noopener">' + esc(u.source_name || u.url) + '</a>' : esc(u.source_name)) +
              '</div>' : '') +
          '</div>' +
        '</div></div>'
      );
    }).join('');

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
          '<div class="story-mini-meta"><span>' + updates.length + ' update' + (updates.length === 1 ? '' : 's') + '</span><span>marked ' + esc((story.marked_at || '').slice(0, 10)) + '</span></div>' +
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

    main.querySelectorAll('[data-action]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var action = btn.dataset.action;
        var status = action === 'resolve' ? 'resolved' : action === 'reactivate' ? 'active' : 'archived';
        WatchlistStore.setStatus(story.story_id, status);
        renderRail();
        renderMain();
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

    var tracked = WatchlistStore.all().slice().sort(function (a, b) {
      return (b.marked_at || '').localeCompare(a.marked_at || '');
    });
    lastSuggestions = buildSuggestions();
    var suggestions = lastSuggestions;

    var trackedHtml = tracked.length ? tracked.map(function (s) {
      var st = statusFor(s);
      return (
        '<div class="manage-row" data-id="' + esc(s.story_id) + '">' +
          '<span class="tracker-status ' + st + '">' + st + '</span>' +
          '<span class="manage-row-title">' + esc(s.title) + (s.custom ? ' <span class="manage-tag">custom</span>' : '') + '</span>' +
          '<span class="manage-row-actions">' +
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
            '<button type="submit" class="tracker-btn primary">+ Add story</button>' +
          '</form>' +
        '</div>' +
      '</div>';

    // Tracked-row actions
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
          }
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
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var fd = new FormData(form);
        var story = WatchlistStore.addCustom({
          title: fd.get('title'),
          text: fd.get('text'),
          keywords: fd.get('keywords'),
          countries: fd.get('countries'),
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

  DataLayer.loadAll().then(function (data) {
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
