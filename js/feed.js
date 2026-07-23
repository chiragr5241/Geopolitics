'use strict';

/* Feed page — full intel feed with filters + mark-important star.
   Reuses DataLayer, WatchlistStore, and FeedItem (shared expand / deep-link). */

(function () {
  var ALL_CATEGORIES = [
    'military', 'diplomatic', 'economic', 'nuclear', 'energy', 'humanitarian',
    'political', 'cyber', 'trade', 'terrorism', 'intelligence', 'legal', 'social',
  ];

  var activeCategories = new Set(ALL_CATEGORIES);
  var items = [];
  var creditByUrl = {};
  var expanded = new Set();
  var focusKey = FeedItem.readQueryItem();
  var PAGE = 50;        // page size for the "load more" pager
  var shown = PAGE;     // how many items are currently rendered
  // Reveal on scroll only for the first paint — re-renders from filtering or
  // starring should update in place, not re-fade the whole list.
  var initialRender = true;

  function renderFilterBar() {
    var el = document.getElementById('filter-bar');
    el.innerHTML = ALL_CATEGORIES.map(function (c) {
      return '<span class="filter-pill ' + (activeCategories.has(c) ? '' : 'off') + '" data-cat="' + c + '">' + c + '</span>';
    }).join('');
    el.querySelectorAll('.filter-pill').forEach(function (pill) {
      pill.addEventListener('click', function () {
        var c = pill.dataset.cat;
        if (activeCategories.has(c)) activeCategories.delete(c); else activeCategories.add(c);
        shown = PAGE; // a new filter starts from the top
        renderFilterBar();
        renderList();
      });
    });
  }

  // Feed card = the shared FeedItem.cardHtml with a star control.
  function cardHtml(item, reveal) {
    var key = FeedItem.itemKey(item);
    return FeedItem.cardHtml(item, {
      control: 'star',
      controlOn: WatchlistStore.isMarked(item),
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
      return activeCategories.has((it.category || 'social').toLowerCase());
    });

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
      wrap.innerHTML = '<div class="empty-note">No items match the current filters.</div>';
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

    wrap.querySelectorAll('[data-action="star"]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var key = btn.closest('.feed-card').dataset.key;
        var item = FeedItem.findByKey(items, key);
        if (item) WatchlistStore.toggle(item);
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

    renderFilterBar();
    renderList();

    var exportBtn = document.getElementById('export-watchlist-btn');
    if (exportBtn) exportBtn.addEventListener('click', function () { WatchlistStore.exportFile(); });
  }).catch(function (err) {
    console.error('Failed to load feed data:', err);
    document.getElementById('feed-list').innerHTML =
      '<div class="empty-note">Failed to load data: ' + err.message + '</div>';
  });
})();
