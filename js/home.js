'use strict';

/* Main page (tracker-first): six main stories as large image tiles,
   followed by the rest of the news as a compact list.

   Story selection happens here in selectHeroes() — active tracked
   stories (watchlist) get the first slots, the rest are auto-picked
   from the intel feed by score (severity + breaking + recency) with
   a country-set/subcategory dedupe so six *different* stories surface.
   When the site goes dynamic, a backend can replace selectHeroes()
   and feed the same tile format. */

(function () {
  // No hard cap: every ACTIVE tracked story becomes a tile, in the user's
  // manual priority order (first = biggest). Auto-picked feed stories only
  // backfill up to MIN_TILES so a lightly-used tracker still fills the page;
  // track 2 and you get 2 (+ fill), track 40 and you get 40.
  var MIN_TILES = 6;
  var REST_PAGE = 50;   // initial rest-of-news count; "load more" adds another page
  var restShown = REST_PAGE;
  var restRevealed = 0; // how many rest rows have already faded in (don't re-animate)
  var restObserver = null; // watches the load-more button → auto-loads on scroll

  var esc = Util.esc;
  var fmtTime = Util.fmtTime;

  function pillClass(category) {
    return 'pill pill-' + (category || 'social').toLowerCase();
  }

  // ── Story selection ──────────────────────────────────────

  function selectHeroes(items, storyUpdates) {
    var heroes = [];
    var trackedPseudo = []; // country-set stand-ins so auto picks dedupe against tracked stories

    // Every active tracked story becomes a tile, in manual PRIORITY order
    // (WatchlistStore.all() array order) — no cap, no re-sort. A BRANCH
    // (parent_id) of another active tracked story is the exception: it rides
    // inside its top ancestor's tile as a compact row instead of taking a tile.
    var active = WatchlistStore.all().filter(function (s) { return s.status === 'active'; });
    var byId = {};
    active.forEach(function (s) { byId[s.story_id] = s; });
    function tileOwner(s) {
      var owner = null, cur = s;
      for (var hop = 0; hop < 4 && cur.parent_id && byId[cur.parent_id] && cur.parent_id !== cur.story_id; hop++) {
        owner = byId[cur.parent_id];
        cur = owner;
      }
      return owner;
    }
    var branchesOf = {};
    active.forEach(function (s) {
      var owner = tileOwner(s);
      if (owner) {
        (branchesOf[owner.story_id] = branchesOf[owner.story_id] || []).push({
          title: s.title,
          href: 'tracker.html?story=' + encodeURIComponent(s.story_id),
          updates: Util.countStoryEntries(s, storyUpdates, items),
        });
      }
    });

    active
      .filter(function (s) { return !tileOwner(s); })
      .forEach(function (s) {
        var cs = ((s.seed && s.seed.countries) || []).join(';');
        heroes.push({
          kind: 'tracked',
          title: s.title,
          dek: (s.seed && s.seed.text) || '',
          category: 'tracked',
          countries: cs,
          time: s.last_update_at || s.marked_at || '',
          href: 'tracker.html?story=' + encodeURIComponent(s.story_id),
          matchText: (s.title + ' ' + ((s.seed && s.seed.text) || '')).toLowerCase(),
          // Curated updates + linked feed items over the story's full history
          // (see Util.countStoryEntries). Same helper as the Tracker page's
          // rail count (js/tracker.js countEntries) so the two pages agree.
          updates: Util.countStoryEntries(s, storyUpdates, items),
          image: s.image || '',
          branches: branchesOf[s.story_id] || [],
        });
        trackedPseudo.push({ subcategory: '', countries: cs });
      });

    // Backfill from the feed ONLY up to MIN_TILES, deduped by story.
    if (heroes.length < MIN_TILES) {
      var picked = [];
      var candidates = items
        .filter(function (it) { return it.is_breaking === 'TRUE' || (parseInt(it.severity, 10) || 0) >= 4; })
        .slice().sort(function (a, b) { return Util.score(b) - Util.score(a); });

      candidates.forEach(function (it) {
        if (heroes.length + picked.length >= MIN_TILES) return;
        var dup = picked.concat(trackedPseudo).some(function (p) { return Util.sameStory(p, it); });
        if (!dup) picked.push(it);
      });

      picked.forEach(function (it) {
        heroes.push({
          kind: 'feed',
          item: it,
          title: it.summary || it.full_text || '',
          dek: it.context || it.implications || '',
          category: it.category || 'social',
          countries: it.countries || '',
          time: it.created_at,
          // Deep-link to the same feed cell when enrichment exists.
          href: FeedItem.hasDetails(it) ? FeedItem.feedUrl(it) : 'feed.html',
          matchText: ((it.subcategory || '').replace(/_/g, ' ') + ' ' + (it.summary || '')).toLowerCase(),
        });
      });
    }

    return heroes;
  }

  // ── Hero images ──────────────────────────────────────────

  // First matching row whose image isn't already on another tile —
  // rows in story_images.csv are ordered most-specific first.
  function findImage(hero, storyImages, usedUrls) {
    var itemCs = (hero.countries || '').toUpperCase().split(';')
      .map(function (c) { return c.trim(); }).filter(Boolean);
    for (var i = 0; i < storyImages.length; i++) {
      if (usedUrls.indexOf(storyImages[i].url) !== -1) continue;
      // Country gate (mirrors match_image in enrich_lib.py) — a country-tagged
      // image can't land on a story from a different country.
      var rowCs = (storyImages[i].countries || '').toUpperCase().split(';')
        .map(function (c) { return c.trim(); }).filter(Boolean);
      if (rowCs.length && itemCs.length && !rowCs.some(function (c) { return itemCs.indexOf(c) !== -1; })) continue;
      var keys = (storyImages[i].keywords || '').toLowerCase().split(';');
      for (var j = 0; j < keys.length; j++) {
        var k = keys[j].trim();
        if (k && hero.matchText.indexOf(k) !== -1) return storyImages[i];
      }
    }
    return null;
  }

  // ── Rendering ────────────────────────────────────────────

  // A parent tile's branches: one translucent row each (⑂ title · count),
  // each its own link to the branch's timeline. Past `max`, a "+N more" row
  // opens the parent, where the Timelines page lists them all.
  function branchesHtml(branches, max) {
    if (!branches.length) return '';
    var shown = branches.slice(0, max);
    var more = branches.length - shown.length;
    return '<div class="story-tile-branches">' +
      shown.map(function (b) {
        return '<a class="story-tile-branch" href="' + esc(b.href) + '">' +
          '<span class="story-tile-branch-icon" aria-hidden="true">⑂</span>' +
          '<span class="story-tile-branch-title">' + esc(b.title) + '</span>' +
          '<span class="story-tile-branch-count">' + b.updates + '</span>' +
        '</a>';
      }).join('') +
      (more ? '<span class="story-tile-branch-more">+' + more + ' more branch' + (more === 1 ? '' : 'es') + '</span>' : '') +
    '</div>';
  }

  function renderHeroes(heroes, storyImages) {
    var wrap = document.getElementById('story-hero');
    if (!heroes.length) {
      wrap.innerHTML = '<div class="empty-note">No stories available.</div>';
      return;
    }
    var usedUrls = [];
    wrap.innerHTML = heroes.map(function (h, idx) {
      // A user-set story image wins; otherwise keyword-match from story_images.
      var img = h.image ? { url: h.image, label: h.title || '', credit: '' }
                        : findImage(h, storyImages, usedUrls);
      if (img) usedUrls.push(img.url);
      var lead = idx === 0 ? ' lead' : '';
      var breaking = h.item && h.item.is_breaking === 'TRUE';
      var branches = h.branches || [];
      // The tile is a <div> with a stretched link (not an <a>) so branch rows
      // can be links of their own — anchors can't nest.
      return (
        '<div class="story-tile animate-on-scroll' + lead + (img ? '' : ' no-img') + (branches.length ? ' has-branches' : '') +
          ' tile-cat-' + esc(h.category).toLowerCase() + '">' +
          '<a class="story-tile-link" href="' + h.href + '" aria-label="' + esc(h.title) + '"></a>' +
          (img ? '<img class="story-tile-img" src="' + esc(img.url) + '" alt="' + esc(img.label) + '" loading="lazy" decoding="async">' : '') +
          '<div class="story-tile-scrim"></div>' +
          '<div class="story-tile-body">' +
            '<div class="story-tile-meta">' +
              '<span class="' + pillClass(h.category) + '">' + esc(h.category) + '</span>' +
              (breaking ? '<span class="pill pill-military">breaking</span>' : '') +
              (h.kind === 'tracked' ? '<span class="story-tile-time">' + h.updates + ' update' + (h.updates === 1 ? '' : 's') + '</span>' : '') +
              '<span class="story-tile-time">' + fmtTime(h.time) + '</span>' +
            '</div>' +
            '<div class="story-tile-title">' + esc(h.title) + '</div>' +
            (idx === 0 && h.dek && !branches.length ? '<div class="story-tile-dek">' + esc(h.dek) + '</div>' : '') +
            branchesHtml(branches, idx === 0 ? 3 : 2) +
          '</div>' +
          (img && img.credit ? '<div class="story-tile-credit">' + esc(img.credit) + '</div>' : '') +
        '</div>'
      );
    }).join('');

    // Broken image → fall back to the gradient tile.
    wrap.querySelectorAll('.story-tile-img').forEach(function (el) {
      el.addEventListener('error', function () {
        var tile = el.closest('.story-tile');
        if (tile) {
          tile.classList.add('no-img');
          var credit = tile.querySelector('.story-tile-credit');
          if (credit) credit.remove();
        }
        el.remove();
      });
    });

    if (window.Reveal) window.Reveal.scan(wrap);
  }

  function renderRest(items, heroes) {
    var heroItems = heroes.filter(function (h) { return h.item; }).map(function (h) { return h.item; });
    var all = items.filter(function (it) { return heroItems.indexOf(it) === -1; });
    var wrap = document.getElementById('rest-list');
    if (!all.length) {
      wrap.innerHTML = '<div class="empty-note">Nothing else right now.</div>';
      return;
    }
    var rest = all.slice(0, restShown);
    var remaining = all.length - rest.length;
    wrap.innerHTML = rest.map(function (it, i) {
      // Only newly appended rows animate; already-shown rows stay put.
      var reveal = i >= restRevealed ? ' animate-on-scroll' : ' visible';
      // The whole row deep-links to the same item on the Feed page. Every feed
      // item has a unique key (tweet_id, or a unique created_at fallback), and
      // feed.html?item= focuses/pins that exact cell — so this works for every
      // row, enriched or not (no separate "Show details" button needed).
      return (
        '<a class="card rest-row' + reveal + '" href="' + FeedItem.feedUrl(it) + '">' +
          '<span class="rest-time">' + fmtTime(it.created_at) + '</span>' +
          '<span class="' + pillClass(it.category) + '">' + esc(it.category || 'social') + '</span>' +
          '<span class="rest-text">' + esc(it.summary || it.full_text || '') + '</span>' +
          '<svg class="rest-open" width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M5 3l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
        '</a>'
      );
    }).join('') +
      (remaining > 0
        ? '<button class="tracker-btn load-more-btn" id="rest-load-more">Load ' +
            Math.min(REST_PAGE, remaining) + ' more (' + remaining + ' remaining)</button>'
        : '');

    restRevealed = rest.length;
    if (window.Reveal) window.Reveal.scan(wrap);

    var moreBtn = document.getElementById('rest-load-more');
    if (moreBtn) {
      var loadMore = function () {
        restShown += REST_PAGE;
        renderRest(items, heroes);
      };
      moreBtn.addEventListener('click', loadMore);
      // Auto-load the next page as the button nears the viewport (infinite
      // scroll) so the "rest of the news" streams in on scroll instead of
      // needing a click. The click handler above stays as a fallback for
      // no-IntersectionObserver environments. rootMargin pre-loads early so
      // the reader rarely sees the button before more rows appear.
      if (restObserver) restObserver.disconnect();
      if ('IntersectionObserver' in window) {
        restObserver = new IntersectionObserver(function (entries) {
          if (entries.some(function (en) { return en.isIntersecting; })) {
            restObserver.disconnect();
            loadMore();
          }
        }, { rootMargin: '400px 0px' });
        restObserver.observe(moreBtn);
      }
    }
  }

  DataLayer.loadFeed().then(function (data) {
    // Sources before the store: tracking a story from here seeds its source
    // selection from the registry (see WatchlistStore.buildStory).
    SourceRegistry.init(data.sources);
    WatchlistStore.init(data.watchlist);
    var items = (data.tweetEnriched || []).slice().sort(function (a, b) {
      return (b.created_at || '').localeCompare(a.created_at || '');
    });
    var heroes = selectHeroes(items, data.storyUpdates || []);
    renderHeroes(heroes, data.storyImages || []);
    renderRest(items, heroes);

    var meta = data.meta || {};
    if (meta.generated) {
      document.getElementById('page-sub').textContent =
        'Your tracked stories first, then the rest of the news. Updated ' +
        meta.generated.slice(0, 16).replace('T', ' ') + ' UTC.';
    }
  }).catch(function (err) {
    console.error('Failed to load tracker data:', err);
    document.getElementById('story-hero').innerHTML =
      '<div class="empty-note">Failed to load data: ' + err.message + '</div>';
  });
})();
