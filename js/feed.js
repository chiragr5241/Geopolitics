'use strict';

/* Feed page — full intel feed with filters, a Track toggle, and flags.
   Reuses DataLayer, WatchlistStore, FlagStore, and FeedItem (shared expand /
   deep-link). */

(function () {
  var ALL_CATEGORIES = [
    'military', 'diplomatic', 'economic', 'nuclear', 'energy', 'humanitarian',
    'political', 'cyber', 'trade', 'terrorism', 'intelligence', 'legal', 'social',
  ];

  var activeCategories = new Set(ALL_CATEGORIES);
  // Flag is a tag, not a category — it filters on its own axis (AND-ed with
  // the category pills) rather than joining the category set.
  var flaggedOnly = false;
  var query = '';       // free-text search, AND-ed with the pills
  var queryTerms = [];  // parsed terms; "quoted phrases" stay one term
  var items = [];
  var creditByUrl = {};
  var expanded = new Set();
  var focusKey = FeedItem.readQueryItem();
  var PAGE = 50;        // page size for the "load more" pager
  var shown = PAGE;     // how many items are currently rendered
  var lastVisibleCount = 0; // post-filter count, for the search result readout
  // Reveal on scroll only for the first paint — re-renders from filtering or
  // starring should update in place, not re-fade the whole list.
  var initialRender = true;

  /* ── Search ───────────────────────────────────────────────────────────
     Free-text over the card's own words: headline/summary, the full tweet or
     wire text, the extracted entities, country codes, category and source.
     Terms are AND-ed (all must match) and "a quoted phrase" stays one term,
     so `iran strike` narrows while `"strait of hormuz"` stays exact. */

  var SEARCH_FIELDS = [
    'summary', 'full_text', 'entities_locations', 'entities_people',
    'entities_orgs', 'entities_weapons', 'countries', 'category',
    'subcategory', 'source', 'perspective', 'linked_operation',
  ];

  // Built once per item and cached on it — the blob is rebuilt only if the
  // daily data reload replaces the objects.
  function searchBlob(item) {
    if (item.__blob != null) return item.__blob;
    var parts = [];
    for (var i = 0; i < SEARCH_FIELDS.length; i++) {
      var v = item[SEARCH_FIELDS[i]];
      if (v) parts.push(String(v));
    }
    item.__blob = parts.join(' • ').toLowerCase();
    return item.__blob;
  }

  function parseQuery(raw) {
    var terms = [];
    var re = /"([^"]+)"|(\S+)/g;
    var m;
    while ((m = re.exec(raw || '')) !== null) {
      var t = (m[1] || m[2] || '').trim().toLowerCase();
      if (t) terms.push(t);
    }
    return terms;
  }

  function matchesQuery(item) {
    if (!queryTerms.length) return true;
    var blob = searchBlob(item);
    for (var i = 0; i < queryTerms.length; i++) {
      if (blob.indexOf(queryTerms[i]) === -1) return false;
    }
    return true;
  }

  // Keep ?q= in the URL so a search is shareable / survives a refresh, without
  // adding a history entry per keystroke.
  function syncQueryParam() {
    if (!window.history || !history.replaceState) return;
    var url = new URL(location.href);
    if (query) url.searchParams.set('q', query);
    else url.searchParams.delete('q');
    history.replaceState(null, '', url.toString());
  }

  function applyQuery(raw) {
    query = raw;
    queryTerms = parseQuery(raw);
    shown = PAGE; // a new search starts from the top
    syncQueryParam();
    renderList();
    updateSearchUi();
  }

  function updateSearchUi() {
    var box = document.getElementById('feed-search');
    if (box) box.classList.toggle('has-query', !!query);
    var count = document.getElementById('feed-search-count');
    if (count) count.textContent = query ? (lastVisibleCount + ' match' + (lastVisibleCount === 1 ? '' : 'es')) : '';
  }

  function renderSearchBar() {
    var el = document.getElementById('feed-search');
    if (!el) return;
    el.innerHTML =
      '<div class="feed-search__box">' +
        '<svg class="feed-search__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.6-3.6"/></svg>' +
        '<input type="search" id="feed-search-input" class="feed-search__input" autocomplete="off" spellcheck="false"' +
          ' placeholder="Search" aria-label="Search the feed">' +
        '<button type="button" class="feed-search__clear" id="feed-search-clear" title="Clear search" aria-label="Clear search">&times;</button>' +
      '</div>' +
      '<span class="feed-search__count" id="feed-search-count"></span>';

    var input = document.getElementById('feed-search-input');
    input.value = query;
    var timer = null;
    input.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(function () { applyQuery(input.value.trim()); }, 140);
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { input.value = ''; clearTimeout(timer); applyQuery(''); }
      if (e.key === 'Enter') { clearTimeout(timer); applyQuery(input.value.trim()); }
    });
    document.getElementById('feed-search-clear').addEventListener('click', function () {
      input.value = '';
      applyQuery('');
      input.focus();
    });

    // "/" focuses the search from anywhere on the page.
    document.addEventListener('keydown', function (e) {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
      var t = e.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      e.preventDefault();
      input.focus();
      input.select();
    });
  }

  function renderFilterBar() {
    var el = document.getElementById('filter-bar');
    var n = FlagStore.count();
    // The flag leads the bar — it's the first tag, so it's the first filter.
    var flagPill = '<span class="filter-pill flag-filter ' + (flaggedOnly ? 'on' : '') +
      '" data-flag="1" title="Show only flagged items">' + FeedItem.flagSvg(flaggedOnly) +
      'Flagged' + (n ? ' <span class="filter-count">' + n + '</span>' : '') + '</span>';

    el.innerHTML = flagPill + '<span class="filter-sep"></span>' + ALL_CATEGORIES.map(function (c) {
      return '<span class="filter-pill ' + (activeCategories.has(c) ? '' : 'off') + '" data-cat="' + c + '">' + c + '</span>';
    }).join('');

    el.querySelectorAll('.filter-pill[data-cat]').forEach(function (pill) {
      pill.addEventListener('click', function () {
        var c = pill.dataset.cat;
        if (activeCategories.has(c)) activeCategories.delete(c); else activeCategories.add(c);
        shown = PAGE; // a new filter starts from the top
        renderFilterBar();
        renderList();
      });
    });
    var flagEl = el.querySelector('.filter-pill[data-flag]');
    if (flagEl) {
      flagEl.addEventListener('click', function () {
        flaggedOnly = !flaggedOnly;
        shown = PAGE;
        renderFilterBar();
        renderList();
      });
    }
  }

  // Feed card = the shared FeedItem.cardHtml with the Track button + flag.
  function cardHtml(item, reveal) {
    var key = FeedItem.itemKey(item);
    return FeedItem.cardHtml(item, {
      control: 'track',
      controlOn: WatchlistStore.isMarked(item),
      flag: true,
      reveal: reveal,
      focused: focusKey && key === focusKey,
      expandedOpen: expanded.has(key),
      creditByUrl: creditByUrl,
    });
  }

  function scrollToFocus() {
    if (!focusKey) return;
    var el = document.getElementById('feed-item-' + focusKey);
    if (!el) return;
    // Wait a frame so layout is settled after the list paint.
    requestAnimationFrame(function () {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }

  function renderList() {
    var wrap = document.getElementById('feed-list');
    var visible = items.filter(function (it) {
      if (flaggedOnly && !FlagStore.isFlagged(it)) return false;
      if (!matchesQuery(it)) return false;
      return activeCategories.has((it.category || 'social').toLowerCase());
    });
    lastVisibleCount = visible.length;

    // Ensure a deep-linked item is visible even if its category filter is off.
    if (focusKey) {
      var focused = FeedItem.findByKey(items, focusKey);
      if (focused && visible.indexOf(focused) === -1) {
        // Filtered out entirely — prepend it so it's always shown at the top.
        visible = [focused].concat(visible);
      } else if (focused) {
        // Already in the list but possibly past the current page — auto-load
        // pages (in PAGE-sized steps) until the item is included.
        var fi = visible.indexOf(focused);
        if (fi >= shown) shown = Math.ceil((fi + 1) / PAGE) * PAGE;
      }
    }

    if (!visible.length) {
      var note;
      if (query) note = 'No items match “' + FeedItem.esc(query) + '”.';
      else if (flaggedOnly && !FlagStore.count()) note = 'Nothing flagged yet — use the flag on a card to save it here.';
      else note = 'No items match the current filters.';
      wrap.innerHTML = '<div class="empty-note">' + note + '</div>';
      return;
    }

    var page = visible.slice(0, shown);
    var remaining = visible.length - page.length;
    var reveal = initialRender;
    wrap.innerHTML = page.map(function (it) { return cardHtml(it, reveal); }).join('') +
      (remaining > 0
        ? '<button class="tracker-btn load-more-btn" id="feed-load-more">Load ' +
            Math.min(PAGE, remaining) + ' more (' + remaining + ' remaining)</button>'
        : '');
    if (reveal && window.Reveal) window.Reveal.scan(wrap);
    initialRender = false;

    var moreBtn = document.getElementById('feed-load-more');
    if (moreBtn) {
      moreBtn.addEventListener('click', function () {
        shown += PAGE;
        renderList();
      });
    }

    wrap.querySelectorAll('[data-action="track"]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var key = btn.closest('.feed-card').dataset.key;
        var item = FeedItem.findByKey(items, key);
        if (item) WatchlistStore.toggle(item);
        renderList();
      });
    });
    wrap.querySelectorAll('[data-action="flag"]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var key = btn.closest('.feed-card').dataset.key;
        if (key) FlagStore.toggle(key);
        // The count in the filter bar moves with every flag.
        renderFilterBar();
        renderList();
      });
    });
    wrap.querySelectorAll('[data-action="toggle"]').forEach(function (el) {
      el.addEventListener('click', function () {
        var key = el.closest('.feed-card').dataset.key;
        if (expanded.has(key)) expanded.delete(key); else expanded.add(key);
        renderList();
      });
    });

    if (focusKey) scrollToFocus();
  }

  DataLayer.loadFeed().then(function (data) {
    WatchlistStore.init(data.watchlist);
    (data.storyImages || []).forEach(function (r) {
      if (r && r.url) creditByUrl[r.url] = r.credit || '';
    });
    items = (data.tweetEnriched || []).slice().sort(function (a, b) {
      return (b.created_at || '').localeCompare(a.created_at || '');
    });

    if (focusKey) {
      var hit = FeedItem.findByKey(items, focusKey);
      if (hit) {
        expanded.add(focusKey);
        // Turn on the item's category so filters don't hide it.
        var cat = (hit.category || 'social').toLowerCase();
        if (!activeCategories.has(cat)) activeCategories.add(cat);
      }
    }

    // A shared ?q= link opens straight into that search.
    try {
      query = (new URL(location.href)).searchParams.get('q') || '';
      queryTerms = parseQuery(query);
    } catch (e) { /* ignore a malformed URL — just start unfiltered */ }

    renderSearchBar();
    renderFilterBar();
    renderList();
    updateSearchUi();

    // Owner-only: see the note in js/watchlist.js exportFile().
    var exportBtn = document.getElementById('export-watchlist-btn');
    if (exportBtn) {
      if (typeof Session !== 'undefined' && !Session.isOwner()) exportBtn.hidden = true;
      else exportBtn.addEventListener('click', function () { WatchlistStore.exportFile(); });
    }
  }).catch(function (err) {
    console.error('Failed to load feed data:', err);
    document.getElementById('feed-list').innerHTML =
      '<div class="empty-note">Failed to load data: ' + err.message + '</div>';
  });
})();
