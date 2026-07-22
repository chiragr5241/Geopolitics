'use strict';

/* Feed page — full intel feed with filters + mark-important star.
   Reuses DataLayer for data and WatchlistStore for marking; rendering
   is a fresh implementation (not a refactor of js/app.js's tweet list)
   since feed cards show more (context/implications/sources) and need
   the star control that the map sidebar never had. */

(function () {
  var ALL_CATEGORIES = [
    'military', 'diplomatic', 'economic', 'nuclear', 'energy', 'humanitarian',
    'political', 'cyber', 'trade', 'terrorism', 'intelligence', 'legal', 'social',
  ];

  var activeCategories = new Set(ALL_CATEGORIES);
  var items = [];
  var expanded = new Set();

  function fmtTime(ts) {
    if (!ts) return '';
    var d = new Date((ts || '').replace(' ', 'T') + 'Z');
    if (isNaN(d.getTime())) return ts;
    return d.toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  }

  function sevDots(sev) {
    sev = parseInt(sev, 10) || 0;
    var out = '<span class="sev-dots">';
    for (var i = 1; i <= 5; i++) out += '<span class="sev-dot ' + (i <= sev ? 'on' : '') + '"></span>';
    return out + '</span>';
  }

  function pillClass(category) {
    return 'pill pill-' + (category || 'social').toLowerCase();
  }

  function parseSources(json) {
    if (!json) return [];
    try {
      var arr = JSON.parse(json);
      return Array.isArray(arr) ? arr : [];
    } catch (e) { return []; }
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
        renderFilterBar();
        renderList();
      });
    });
  }

  function cardHtml(item) {
    var starred = WatchlistStore.isMarked(item);
    var sources = parseSources(item.sources_json);
    var isOpen = expanded.has(item._key);
    var hasExpand = item.context || item.implications || sources.length;

    var expandHtml = '';
    if (item.context) expandHtml += '<div class="feed-expand-row"><div class="feed-expand-k">Context</div><div class="feed-expand-v">' + item.context + '</div></div>';
    if (item.implications) expandHtml += '<div class="feed-expand-row"><div class="feed-expand-k">Implications</div><div class="feed-expand-v">' + item.implications + '</div></div>';
    if (sources.length) {
      expandHtml += '<div class="feed-expand-row"><div class="feed-expand-k">Sources (' + sources.length + ')</div><div class="feed-expand-v">' +
        sources.map(function (s) {
          var label = (s.name || 'Source') + (s.title ? ': ' + s.title : '');
          return s.url ? '<a href="' + s.url + '" target="_blank" rel="noopener">' + label + '</a>' : label;
        }).join('<br>') + '</div></div>';
    }

    return (
      '<div class="card feed-card ' + (item.is_breaking === 'TRUE' ? 'breaking' : '') + ' ' + (starred ? 'starred' : '') + '" data-key="' + item._key + '">' +
        '<div class="feed-card-top">' +
          '<span class="' + pillClass(item.category) + '">' + (item.category || 'social') + '</span>' +
          (item.confirmation_status ? '<span class="pill" style="color:var(--text);border-color:var(--border2);background:var(--bg1);">' + item.confirmation_status + '</span>' : '') +
          sevDots(item.severity) +
          '<span class="feed-time">' + fmtTime(item.created_at) + '</span>' +
          '<button class="star-btn ' + (starred ? 'on' : '') + '" title="Mark important" data-action="star">' + (starred ? '★' : '☆') + '</button>' +
        '</div>' +
        '<div class="feed-text">' + (item.summary || item.full_text || '') + '</div>' +
        (hasExpand ? '<div class="feed-toggle-more" data-action="toggle">' + (isOpen ? 'Hide details −' : 'Show details +') + '</div>' : '') +
        '<div class="feed-expand ' + (isOpen ? 'open' : '') + '">' + expandHtml + '</div>' +
      '</div>'
    );
  }

  function renderList() {
    var wrap = document.getElementById('feed-list');
    var visible = items.filter(function (it) { return activeCategories.has((it.category || 'social').toLowerCase()); });
    if (!visible.length) {
      wrap.innerHTML = '<div class="empty-note">No items match the current filters.</div>';
      return;
    }
    wrap.innerHTML = visible.slice(0, 300).map(cardHtml).join('');

    wrap.querySelectorAll('[data-action="star"]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var key = btn.closest('.feed-card').dataset.key;
        var item = items.filter(function (it) { return it._key === key; })[0];
        WatchlistStore.toggle(item);
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
  }

  DataLayer.loadFeed().then(function (data) {
    WatchlistStore.init(data.watchlist);
    items = (data.tweetEnriched || []).map(function (r, i) {
      r._key = (r.tweet_id || r.created_at || 'row') + '-' + i;
      return r;
    }).sort(function (a, b) { return (b.created_at || '').localeCompare(a.created_at || ''); });

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
