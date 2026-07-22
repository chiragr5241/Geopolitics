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

  // Short, chip-friendly story label: the part before the first colon, else a
  // truncated title.
  function shortStoryTitle(t) {
    t = String(t || '');
    var i = t.indexOf(':');
    if (i > 2 && i <= 40) return t.slice(0, i);
    return t.length > 34 ? t.slice(0, 32) + '…' : t;
  }

  // Story tag chips for an item, from its `linked_story_ids`. Active stories
  // render coloured; resolved/archived render greyed; a story that no longer
  // exists in the watchlist (removed) simply produces no chip. Requires
  // WatchlistStore to be initialised.
  function storyTagsHtml(item) {
    if (!item || typeof WatchlistStore === 'undefined' || !WatchlistStore.byId) return '';
    var ids = String(item.linked_story_ids || '').split(';');
    var chips = [];
    for (var i = 0; i < ids.length; i++) {
      var id = ids[i];
      if (!id) continue;
      var s = WatchlistStore.byId(id);
      if (!s) continue; // removed from watchlist → no tag
      var muted = (s.status === 'resolved' || s.status === 'archived');
      var title = s.title || id;
      chips.push(
        '<a class="story-tag' + (muted ? ' muted' : '') + '" href="tracker.html?story=' +
        encodeURIComponent(id) + '" title="' + esc(title) + (muted ? ' — ' + esc(s.status) : '') + '">' +
        '<span class="story-tag-dot"></span>' + esc(shortStoryTitle(title)) + '</a>'
      );
    }
    return chips.length ? '<div class="story-tags">' + chips.join('') + '</div>' : '';
  }

  // Source / perspective badge for wire items (pull_wires.py). Spectator tweets
  // carry no badge — they're the implicit default. `perspective` drives the
  // colour (see .persp-* in site.css) so a Russian-sourced and a Gulf-sourced
  // take on the same event read as visibly different viewpoints.
  var PERSPECTIVE_LABEL = {
    'western-uk': 'UK', 'german': 'DE', 'gulf': 'Gulf', 'institutional': 'UN',
    'humanitarian': 'Aid', 'wire-fast': 'Wire', 'russia': 'RU view',
    'chinese': 'CN view', 'iranian': 'IR view',
  };

  function sourceBadgeHtml(item) {
    if (!item) return '';
    var src = String(item.source || '');
    if (!src || src === 'spectator') return '';
    var persp = String(item.perspective || '');
    var label = PERSPECTIVE_LABEL[persp] || persp;
    var cls = 'source-badge' + (persp ? ' persp-' + persp : '');
    var inner = '<span class="source-badge-name">' + esc(src) + '</span>' +
      (label ? '<span class="source-badge-persp">' + esc(label) + '</span>' : '');
    return item.source_url
      ? '<a class="' + cls + '" href="' + esc(item.source_url) + '" target="_blank" rel="noopener" title="Open original">' + inner + '</a>'
      : '<span class="' + cls + '">' + inner + '</span>';
  }

  // First image URL for an item. `images` is a semicolon-separated list
  // (deterministic keyword match at base tier, or agent-supplied at deep tier).
  function firstImage(item) {
    if (!item || !item.images) return '';
    var first = String(item.images).split(';')[0];
    return first ? first.trim() : '';
  }

  // Thumbnail markup for a feed card, or '' when the item has no image. On load
  // error the thumb removes itself and drops the card's has-img layout —
  // mirroring the graceful degradation in home.js / tracker.js.
  function imageHtml(item, creditByUrl) {
    var url = firstImage(item);
    if (!url) return '';
    var credit = (creditByUrl && creditByUrl[url]) || '';
    return '<div class="feed-card-thumb">' +
      '<img src="' + esc(url) + '" alt="" loading="lazy" ' +
      'onerror="var c=this.closest(\'.feed-card\');if(c){c.classList.remove(\'has-img\');}' +
      'if(this.parentNode){this.parentNode.remove();}">' +
      (credit ? '<span class="feed-card-credit">' + esc(credit) + '</span>' : '') +
      '</div>';
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
    storyTagsHtml: storyTagsHtml,
    sourceBadgeHtml: sourceBadgeHtml,
    firstImage: firstImage,
    imageHtml: imageHtml,
    readQueryItem: readQueryItem,
  };
})();
