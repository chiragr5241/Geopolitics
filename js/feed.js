'use strict';

/* Feed page — full intel feed with filters + mark-important star.
   Reuses DataLayer, WatchlistStore, and FeedItem (shared expand / deep-link). */

(function () {
  var ALL_CATEGORIES = [
    'military', 'diplomatic', 'economic', 'nuclear', 'energy', 'humanitarian',
    'political', 'cyber', 'trade', 'terrorism', 'intelligence', 'legal', 'social',
  ];

  // Categories where a confirmation status ("unconfirmed") is meaningful — a
  // kinetic/security claim you'd want corroborated. Elsewhere the tag is noise.
  var CONFIRM_CATEGORIES = new Set(['military', 'nuclear', 'terrorism', 'cyber']);

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

  var fmtTime = Util.fmtTime;

  function sevDots(sev) {
    sev = parseInt(sev, 10) || 0;
    var out = '<span class="sev-dots">';
    for (var i = 1; i <= 5; i++) out += '<span class="sev-dot ' + (i <= sev ? 'on' : '') + '"></span>';
    return out + '</span>';
  }

  function pillClass(category) {
    return 'pill pill-' + (category || 'social').toLowerCase();
  }

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

  function cardHtml(item, reveal) {
    var key = FeedItem.itemKey(item);
    var starred = WatchlistStore.isMarked(item);
    var isOpen = expanded.has(key);
    var hasExpand = FeedItem.hasDetails(item);
    var focused = focusKey && key === focusKey;
    var thumb = FeedItem.imageHtml(item, creditByUrl);

    return (
      '<div class="card feed-card ' + (reveal ? 'animate-on-scroll ' : '') +
        (item.is_breaking === 'TRUE' ? 'breaking ' : '') +
        (starred ? 'starred ' : '') +
        (thumb ? 'has-img ' : '') +
        (focused ? 'feed-card-focus ' : '') +
        '" data-key="' + FeedItem.esc(key) + '" id="feed-item-' + FeedItem.esc(key) + '">' +
        thumb +
        '<div class="feed-card-body">' +
          '<div class="feed-card-top">' +
            '<span class="' + pillClass(item.category) + '">' + (item.category || 'social') + '</span>' +
            (item.confirmation_status && CONFIRM_CATEGORIES.has((item.category || '').toLowerCase()) ? '<span class="pill" style="color:var(--text);border-color:var(--border2);background:var(--bg1);">' + item.confirmation_status + '</span>' : '') +
            sevDots(item.severity) +
            '<span class="feed-time">' + fmtTime(item.created_at) + '</span>' +
            '<button class="star-btn ' + (starred ? 'on' : '') + '" title="Mark important" data-action="star">' + (starred ? '★' : '☆') + '</button>' +
          '</div>' +
          FeedItem.sourceBadgeHtml(item) +
          '<div class="feed-text">' + (item.summary || item.full_text || '') + '</div>' +
          FeedItem.storyTagsHtml(item) +
          (hasExpand ? FeedItem.toggleBtnHtml(isOpen) : '') +
          '<div class="feed-expand ' + (isOpen ? 'open' : '') + '">' + FeedItem.expandHtml(item) + '</div>' +
        '</div>' +
      '</div>'
    );
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
        visible = [focused].concat(visible);
      } else if (focused) {
        // Already in the list but possibly past the current page — page up to it.
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
