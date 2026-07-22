'use strict';

/* Shared enriched-tweet helpers used by Feed, Tracker (home), and Timelines.
   One stable item key → one feed URL, so "Show details" on any page opens
   the same cell on feed.html. */

var FeedItem = (function () {
  function esc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Prefer tweet_id; fall back to created_at. Stable across pages (no index).
  function itemKey(item) {
    if (!item) return '';
    if (item.tweet_id) return String(item.tweet_id);
    if (item.seed && item.seed.tweet_id) return String(item.seed.tweet_id);
    var ts = item.created_at || (item.seed && item.seed.created_at) || '';
    return ts ? 't-' + String(ts).replace(/\s+/g, '_') : '';
  }

  function matchesKey(item, key) {
    if (!key) return false;
    return itemKey(item) === key;
  }

  function findByKey(items, key) {
    if (!key || !items) return null;
    for (var i = 0; i < items.length; i++) {
      if (matchesKey(items[i], key)) return items[i];
    }
    return null;
  }

  function feedUrl(itemOrKey) {
    var key = typeof itemOrKey === 'string' ? itemOrKey : itemKey(itemOrKey);
    return key ? 'feed.html?item=' + encodeURIComponent(key) : 'feed.html';
  }

  function parseSources(json) {
    if (!json) return [];
    try {
      var arr = JSON.parse(json);
      return Array.isArray(arr) ? arr : [];
    } catch (e) {
      return [];
    }
  }

  function hasDetails(item) {
    if (!item) return false;
    var sources = parseSources(item.sources_json);
    return !!(item.context || item.implications || sources.length);
  }

  function expandHtml(item) {
    if (!hasDetails(item)) return '';
    var sources = parseSources(item.sources_json);
    var html = '';
    if (item.context) {
      html += '<div class="feed-expand-row"><div class="feed-expand-k">Context</div>' +
        '<div class="feed-expand-v">' + item.context + '</div></div>';
    }
    if (item.implications) {
      html += '<div class="feed-expand-row"><div class="feed-expand-k">Implications</div>' +
        '<div class="feed-expand-v">' + item.implications + '</div></div>';
    }
    if (sources.length) {
      html += '<div class="feed-expand-row"><div class="feed-expand-k">Sources (' + sources.length + ')</div>' +
        '<div class="feed-expand-v">' +
        sources.map(function (s) {
          var label = (s.name || 'Source') + (s.title ? ': ' + s.title : '');
          return s.url
            ? '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(label) + '</a>'
            : esc(label);
        }).join('<br>') +
        '</div></div>';
    }
    return html;
  }

  // Inline toggle on the Feed page itself.
  function toggleBtnHtml(isOpen) {
    return '<button type="button" class="feed-details-btn" data-action="toggle">' +
      (isOpen ? 'Hide details −' : 'Show details +') +
      '</button>';
  }

  // Cross-page link that opens the same cell on Feed.
  function linkBtnHtml(item, label) {
    if (!hasDetails(item)) return '';
    return '<a class="feed-details-btn" href="' + feedUrl(item) + '">' +
      esc(label || 'Show details') +
      '</a>';
  }

  function readQueryItem() {
    try {
      var params = new URLSearchParams(window.location.search);
      return params.get('item') || '';
    } catch (e) {
      return '';
    }
  }

  return {
    esc: esc,
    itemKey: itemKey,
    matchesKey: matchesKey,
    findByKey: findByKey,
    feedUrl: feedUrl,
    parseSources: parseSources,
    hasDetails: hasDetails,
    expandHtml: expandHtml,
    toggleBtnHtml: toggleBtnHtml,
    linkBtnHtml: linkBtnHtml,
    readQueryItem: readQueryItem,
  };
})();
