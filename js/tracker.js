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
  var creditByUrl = {};   // url → credit, for feed-card thumbnails in the timeline
  var feedItems = [];
  var lastSuggestions = [];
  var selectedId = null;
  var panelOpen = false;
  var editingId = null;   // story currently open in the inline edit form
  var dragId = null;      // story being dragged in the reorder list
  var renderSeq = 0;      // bumped each renderMain — in-flight chunk loops abort
                          // when it changes (story switched mid-stream)

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

  // Merged timeline (curated beats + linked feed tweets) for a story — shared
  // with js/home.js via Util so both pages always agree on "how many updates".
  function buildEntries(story) {
    return Util.buildStoryEntries(story, storyUpdates, feedItems);
  }

  function countEntries(story) {
    return Util.countStoryEntries(story, storyUpdates, feedItems);
  }

  // Live filter of the OPEN timeline (the selected story's own updates). Pure
  // show/hide on the already-rendered nodes so the input keeps focus while
  // typing — no re-render. Matches on each cell's visible text.
  function filterTimeline(main, q) {
    q = (q || '').trim().toLowerCase();
    var thread = main.querySelector('.timeline-thread');
    if (!thread) return;
    var shown = 0;
    thread.querySelectorAll('.timeline-node').forEach(function (n) {
      var match = !q || n.textContent.toLowerCase().indexOf(q) !== -1;
      n.style.display = match ? '' : 'none';
      if (match) shown++;
    });
    var note = thread.querySelector('.timeline-search-empty');
    if (q && shown === 0) {
      if (!note) {
        note = document.createElement('div');
        note.className = 'empty-note timeline-search-empty';
        thread.appendChild(note);
      }
      note.textContent = 'No updates in this story match “' + q + '”.';
      note.style.display = '';
    } else if (note) {
      note.style.display = 'none';
    }
  }

  // Nested sub-thread indicator shown under a news cell that has been
  // sub-tracked into its own child story. Barebones: a link into the child's
  // timeline (deep-link via ?story=). `child` may be null (not sub-tracked yet).
  function subthreadHtml(child, isSub) {
    if (!isSub || !child) return '';
    var count = countEntries(child);
    return '<div class="subthread">' +
      '<a class="subthread-link" href="tracker.html?story=' + encodeURIComponent(child.story_id) + '">' +
        '<span class="subthread-branch">⑂</span>' +
        '<span class="subthread-title">' + esc(child.title) + '</span>' +
        '<span class="subthread-count">' + count + ' update' + (count === 1 ? '' : 's') + '</span>' +
      '</a>' +
    '</div>';
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
    // Array order IS the user's manual priority (set via drag/▲▼ in Manage
    // stories — see WatchlistStore.moveBy/moveTo) — same convention as the
    // main page's hero tiles. Don't re-sort by date; that silently discarded
    // the order the user set.
    var stories = WatchlistStore.all();
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

    // Build the HTML for one timeline entry. Called per-chunk during the
    // progressive append below rather than all at once, so a big story
    // (hundreds of linked feed rows) never blocks the main thread in one shot.
    function nodeHtml(e) {
      // Feed-backed entries render as the SHARED feed card (identical to the
      // Feed page) but with a sub-track control instead of the star, and the
      // whole card deep-links to the matching feed item.
      if (e.feed) {
        var childId = WatchlistStore.storyIdFor(e.feed);
        var childStory = WatchlistStore.byId(childId);
        var isSub = !!(childStory && childStory.parent_id === story.story_id);
        var card = FeedItem.cardHtml(e.feed, {
          control: 'subtrack',
          controlOn: isSub,
          feedUrl: FeedItem.feedUrl(e.feed),
          creditByUrl: creditByUrl,
        });
        return '<div class="timeline-node animate-on-scroll">' + card + subthreadHtml(childStory, isSub) + '</div>';
      }

      // Curated-only beats (hand/agent-authored story_updates with no matching
      // feed row). If the routine captured the source article's own image
      // (story_updates.image, scraped from the update URL) show it — otherwise
      // no thumbnail. NEVER substitute a keyword-matched stock image here.
      var beatThumb = e.image
        ? '<div class="feed-card-thumb"><img src="' + esc(e.image) + '" alt="" loading="lazy" ' +
            'onerror="var c=this.closest(\'.feed-card\');if(c){c.classList.remove(\'has-img\');}' +
            'if(this.parentNode){this.parentNode.remove();}"></div>'
        : '';
      return (
        '<div class="timeline-node animate-on-scroll">' +
        '<div class="card feed-card' + (beatThumb ? ' has-img' : '') + '">' +
          beatThumb +
          '<div class="feed-card-body">' +
            '<div class="feed-card-top">' +
              '<span class="origin-tag">' + esc(e.origin) + '</span>' +
              (e.status ? '<span class="pill" style="color:var(--text);border-color:var(--border2);background:var(--bg1);">' + esc(e.status) + '</span>' : '') +
              '<span class="feed-time">' + esc(e.date) + '</span>' +
            '</div>' +
            '<div class="feed-text"><strong>' + esc(e.headline) + '</strong></div>' +
            (e.summary ? '<div class="feed-text">' + esc(e.summary) + '</div>' : '') +
            (e.source_name || e.url ?
              '<div class="timeline-node-source">' +
                (e.url ? '<a href="' + esc(e.url) + '" target="_blank" rel="noopener">' + esc(e.source_name || e.url) + '</a>' : esc(e.source_name)) +
              '</div>' : '') +
          '</div>' +
        '</div>' +
        '</div>'
      );
    }

    // Seed pinned at the bottom — the story's origin anchor. Rendered in the
    // feed-card family; deep-links to its feed row when one exists. No sub-track
    // control (it is already this story's own seed).
    var seedUrl = (seedFeed && FeedItem.hasDetails(seedFeed)) ? FeedItem.feedUrl(seedFeed) : '';
    var seedHtml = '<div class="timeline-node seed">' +
      '<div class="card feed-card' + (seedUrl ? ' clickable' : '') + '"' +
        (seedUrl ? ' data-feed-url="' + esc(seedUrl) + '" title="Open in Feed"' : '') + '>' +
        '<div class="feed-card-body">' +
          '<div class="feed-card-top">' +
            '<span class="origin-tag">seed</span>' +
            '<span class="feed-time">' + esc((story.seed.created_at || story.marked_at || '').slice(0, 16)) + '</span>' +
          '</div>' +
          '<div class="feed-text"><strong>Marked important</strong></div>' +
          // Preserve blank-line paragraph breaks (e.g. an appended "AI suggestion:"
          // paragraph) — the raw description can be multi-paragraph.
          '<div class="feed-text" style="white-space:pre-line;">' + esc(story.seed.text || '') + '</div>' +
        '</div>' +
      '</div>' +
    '</div>';

    // Per-story timeline search — sits between the story header and its thread,
    // filters only THIS story's updates (see filterTimeline).
    var searchBar =
      '<div class="tracker-search timeline-search">' +
        '<svg class="tracker-search-icon" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">' +
          '<circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"></circle>' +
          '<line x1="16.5" y1="16.5" x2="21" y2="21" stroke="currentColor" stroke-width="2" stroke-linecap="round"></line>' +
        '</svg>' +
        '<input type="search" id="timeline-search-input" class="tracker-search-input" ' +
          'placeholder="Search this story’s updates…" autocomplete="off">' +
      '</div>';

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
          // Which sources feed this story, editable in place. Deselecting one
          // here is what stops the routine using it from the next run on.
          SourcePicker.html(SourceRegistry.selectionFor(story), {
            compact: true,
            title: 'Sources',
          }) +
        '</div>' +
      '</div>' +
      searchBar +
      // Thread starts EMPTY and is filled in chunks below so the header + search
      // paint immediately even for a story with hundreds of updates. The loading
      // indicator sits after the thread until the last chunk lands.
      '<div class="timeline-thread"></div>' +
      '<div class="timeline-loading" id="timeline-loading">' +
        '<span class="timeline-loading-dot"></span>Loading updates…</div>';

    // Wire the per-story search (show/hide only — keeps input focus).
    var tlSearch = main.querySelector('#timeline-search-input');
    if (tlSearch) {
      tlSearch.addEventListener('input', function () { filterTimeline(main, tlSearch.value); });
    }

    // Broken hero image → drop it and reflow. (Feed-card thumbnails inside the
    // thread self-heal via the inline onerror in FeedItem.imageHtml.)
    main.querySelectorAll('.tracker-story-hero img').forEach(function (el) {
      el.addEventListener('error', function () {
        var hero = el.closest('.tracker-story-hero');
        if (hero) {
          var header = hero.closest('.tracker-story-header');
          if (header) header.classList.remove('has-hero');
          hero.remove();
        }
      });
    });

    // Source picker in the header — persists on every toggle. No Save button
    // on purpose: this is a switch, not a form, and a half-edited selection
    // that silently reverts on navigation would be worse than saving early.
    var headerPicker = main.querySelector('.tracker-story-header .source-picker');
    if (headerPicker) {
      SourcePicker.wire(headerPicker, function (sel) {
        WatchlistStore.setSources(story.story_id, sel);
      });
    }

    main.querySelectorAll('.tracker-story-actions [data-action]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var action = btn.dataset.action;
        var status = action === 'resolve' ? 'resolved' : action === 'reactivate' ? 'active' : 'archived';
        WatchlistStore.setStatus(story.story_id, status);
        renderRail();
        renderMain();
      });
    });

    var thread = main.querySelector('.timeline-thread');
    if (thread) {
      // Delegated handler for the whole thread: sub-track toggle, "Show details"
      // expander, and card → Feed deep-link. One listener covers every cell.
      thread.addEventListener('click', function (e) {
        var card = e.target.closest('.feed-card');
        if (!card) return;

        // Sub-track control — seed / un-seed a child story from this news item.
        var subBtn = e.target.closest('[data-action="subtrack"]');
        if (subBtn) {
          e.stopPropagation();
          var it = FeedItem.findByKey(feedItems, card.dataset.key);
          if (!it) return;
          var childId = WatchlistStore.storyIdFor(it);
          var existing = WatchlistStore.byId(childId);
          if (existing && existing.parent_id === story.story_id) {
            WatchlistStore.removeById(childId);
          } else {
            WatchlistStore.addSubTrack(story.story_id, it);
          }
          refreshAll();
          return;
        }

        // "Show details" expander (inline, no navigation).
        var toggle = e.target.closest('[data-action="toggle"]');
        if (toggle) {
          e.stopPropagation();
          var exp = card.querySelector('.feed-expand');
          if (!exp) return;
          var open = exp.classList.toggle('open');
          toggle.textContent = open ? 'Hide details −' : 'Show details +';
          return;
        }

        // Any other click on a deep-linkable card → open it on the Feed page.
        // Ignore inner links (source URLs) and the sub-thread link.
        if (e.target.closest('a')) return;
        if (card.dataset.feedUrl) window.location.href = card.dataset.feedUrl;
      });
    }

    // ── Progressive (chunked) thread fill ──────────────────────────────
    // Append the timeline a batch at a time, yielding to the browser between
    // batches with requestAnimationFrame. The user watches the thread stream
    // in (so it's obviously loading, not crashed), and the main thread is never
    // blocked building/parsing hundreds of nodes in one synchronous shot.
    var loadingEl = main.querySelector('#timeline-loading');
    var CHUNK = 20;
    var idx = 0;
    var seq = ++renderSeq;      // this render's token — a newer renderMain wins

    function renderChunk() {
      // Superseded (user picked another story) — stop appending stale nodes.
      if (seq !== renderSeq || !thread) return;

      if (idx >= entries.length) {
        // All entries in — pin the seed at the bottom and drop the indicator.
        thread.insertAdjacentHTML('beforeend', seedHtml);
        if (loadingEl) loadingEl.remove();
        if (window.Reveal) window.Reveal.scan(thread);
        return;
      }

      var slice = entries.slice(idx, idx + CHUNK);
      idx += CHUNK;
      thread.insertAdjacentHTML('beforeend', slice.map(nodeHtml).join(''));
      // Bind the freshly-appended .animate-on-scroll nodes (scan is idempotent —
      // already-bound nodes are skipped via their data-revealBound flag).
      if (window.Reveal) window.Reveal.scan(thread);
      requestAnimationFrame(renderChunk);
    }

    renderChunk();
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
          SourcePicker.html(SourceRegistry.selectionFor(s), {
            compact: true,
            title: 'Sources',
          }) +
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

    // Published stories this profile doesn't follow. Every user's page is
    // their own selection out of the shared catalog, so there has to be a way
    // back to the stories they've dropped — and to ones published since.
    var available = WatchlistStore.catalogAvailable();
    var catalogHtml = available.length ? available.map(function (s) {
      var cs = ((s.seed && s.seed.countries) || []).join(' · ');
      return (
        '<div class="catalog-row" data-id="' + esc(s.story_id) + '">' +
          '<span class="tracker-status ' + esc(s.status || 'active') + '">' + esc(s.status || 'active') + '</span>' +
          '<span class="manage-row-title">' + esc(s.title) +
            (cs ? ' <span class="catalog-countries">' + esc(cs) + '</span>' : '') + '</span>' +
          '<button class="tracker-btn primary" data-cact="follow">+ Follow</button>' +
        '</div>'
      );
    }).join('') : '<div class="manage-empty">You\'re following every published story.</div>';

    panel.innerHTML =
      '<div class="manage-inner">' +
        '<div class="manage-section">' +
          '<div class="manage-head">Your stories (' + tracked.length + ')</div>' +
          '<div class="manage-list">' + trackedHtml + '</div>' +
        '</div>' +
        '<div class="manage-section">' +
          '<div class="manage-head">Story catalog (' + available.length + ' not followed)</div>' +
          '<div class="manage-list catalog-list">' + catalogHtml + '</div>' +
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
            // Sources for the new story — everything pre-selected, plus a field
            // for typing in one we don't carry yet.
            SourcePicker.html(SourceRegistry.defaultSelection(), {
              compact: true,
              title: 'Sources to research this story with',
            }) +
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
      SourcePicker.wire(box);
      box.querySelectorAll('[data-mact]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          if (btn.dataset.mact === 'save') {
            WatchlistStore.updateStory(id, {
              title: (box.querySelector('[data-ef="title"]') || {}).value,
              text: (box.querySelector('[data-ef="text"]') || {}).value,
              keywords: (box.querySelector('[data-ef="keywords"]') || {}).value,
              countries: (box.querySelector('[data-ef="countries"]') || {}).value,
              image: (box.querySelector('[data-ef="image"]') || {}).value,
              sources: SourcePicker.read(box),
            });
          }
          editingId = null;
          refreshAll();
        });
      });
    });

    // Catalog "Follow" buttons — adds a published story to this profile's list
    panel.querySelectorAll('.catalog-row').forEach(function (row) {
      var id = row.dataset.id;
      var btn = row.querySelector('[data-cact="follow"]');
      if (!btn) return;
      btn.addEventListener('click', function () {
        WatchlistStore.follow(id);
        if (!selectedId) selectedId = id;
        refreshAll();
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
      SourcePicker.wire(form);
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var fd = new FormData(form);
        var story = WatchlistStore.addCustom({
          title: fd.get('title'),
          text: fd.get('text'),
          keywords: fd.get('keywords'),
          countries: fd.get('countries'),
          image: fd.get('image'),
          sources: SourcePicker.read(form),
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
    // Sources first: WatchlistStore seeds a new story's selection from the
    // registry, so it has to be loaded before init().
    SourceRegistry.init(data.sources);
    WatchlistStore.init(data.watchlist);
    storyUpdates = data.storyUpdates || [];
    storyImages = data.storyImages || [];
    (data.storyImages || []).forEach(function (r) {
      if (r && r.url) creditByUrl[r.url] = r.credit || '';
    });
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

    // Publishing the catalog is an owner action — a member's personal list is
    // their own view, and committing it would prune everyone else's stories.
    var exportBtn = document.getElementById('export-watchlist-btn');
    if (exportBtn) {
      if (typeof Session !== 'undefined' && !Session.isOwner()) exportBtn.hidden = true;
      else exportBtn.addEventListener('click', function () { WatchlistStore.exportFile(); });
    }

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
