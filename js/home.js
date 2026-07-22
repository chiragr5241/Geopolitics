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
  var HERO_COUNT = 6;
  var REST_LIMIT = 40;

  function fmtTime(ts) {
    if (!ts) return '';
    var d = new Date((ts || '').replace(' ', 'T') + 'Z');
    if (isNaN(d.getTime())) return ts;
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  function pillClass(category) {
    return 'pill pill-' + (category || 'social').toLowerCase();
  }

  function esc(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function ageDays(ts) {
    var d = new Date((ts || '').replace(' ', 'T') + 'Z');
    if (isNaN(d.getTime())) return 999;
    return (Date.now() - d.getTime()) / 86400000;
  }

  // ── Story selection ──────────────────────────────────────

  function countrySet(it) {
    return (it.countries || '').split(';').map(function (c) { return c.trim(); }).filter(Boolean);
  }

  function jaccard(a, b) {
    if (!a.length || !b.length) return 0;
    var inter = a.filter(function (x) { return b.indexOf(x) !== -1; }).length;
    return inter / (a.length + b.length - inter);
  }

  // Two feed items are "the same story" if their country sets mostly
  // overlap or they share a subcategory — keeps the grid from filling
  // up with six variations of the same conflict.
  function sameStory(a, b) {
    if (a.subcategory && a.subcategory === b.subcategory) return true;
    return jaccard(countrySet(a), countrySet(b)) >= 0.5;
  }

  function score(it) {
    var sev = parseInt(it.severity, 10) || 0;
    return sev * 2 + (it.is_breaking === 'TRUE' ? 3 : 0) - ageDays(it.created_at) * 0.6;
  }

  function selectHeroes(items) {
    var heroes = [];
    var trackedPseudo = []; // country-set stand-ins so auto picks dedupe against tracked stories

    // Tracked stories first — the tracker drives the front page.
    WatchlistStore.all()
      .filter(function (s) { return s.status === 'active'; })
      .sort(function (a, b) { return (b.last_update_at || b.marked_at || '').localeCompare(a.last_update_at || a.marked_at || ''); })
      .slice(0, HERO_COUNT)
      .forEach(function (s) {
        heroes.push({
          kind: 'tracked',
          title: s.title,
          dek: (s.seed && s.seed.text) || '',
          category: 'tracked',
          time: s.last_update_at || s.marked_at || '',
          href: 'tracker.html?story=' + encodeURIComponent(s.story_id),
          matchText: (s.title + ' ' + ((s.seed && s.seed.text) || '')).toLowerCase(),
          updates: s.update_count || 0,
        });
        trackedPseudo.push({ subcategory: '', countries: ((s.seed && s.seed.countries) || []).join(';') });
      });

    // Fill remaining slots from the feed, deduped by story.
    var picked = [];
    var candidates = items
      .filter(function (it) { return it.is_breaking === 'TRUE' || (parseInt(it.severity, 10) || 0) >= 4; })
      .slice().sort(function (a, b) { return score(b) - score(a); });

    candidates.forEach(function (it) {
      if (heroes.length + picked.length >= HERO_COUNT) return;
      var dup = picked.concat(trackedPseudo).some(function (p) { return sameStory(p, it); });
      if (!dup) picked.push(it);
    });

    picked.forEach(function (it) {
      heroes.push({
        kind: 'feed',
        item: it,
        title: it.summary || it.full_text || '',
        dek: it.context || it.implications || '',
        category: it.category || 'social',
        time: it.created_at,
        // Deep-link to the same feed cell when enrichment exists.
        href: FeedItem.hasDetails(it) ? FeedItem.feedUrl(it) : 'feed.html',
        matchText: ((it.subcategory || '').replace(/_/g, ' ') + ' ' + (it.summary || '')).toLowerCase(),
      });
    });

    return heroes;
  }

  // ── Hero images ──────────────────────────────────────────

  // First matching row whose image isn't already on another tile —
  // rows in story_images.csv are ordered most-specific first.
  function findImage(hero, storyImages, usedUrls) {
    for (var i = 0; i < storyImages.length; i++) {
      if (usedUrls.indexOf(storyImages[i].url) !== -1) continue;
      var keys = (storyImages[i].keywords || '').toLowerCase().split(';');
      for (var j = 0; j < keys.length; j++) {
        var k = keys[j].trim();
        if (k && hero.matchText.indexOf(k) !== -1) return storyImages[i];
      }
    }
    return null;
  }

  // ── Rendering ────────────────────────────────────────────

  function renderHeroes(heroes, storyImages) {
    var wrap = document.getElementById('story-hero');
    if (!heroes.length) {
      wrap.innerHTML = '<div class="empty-note">No stories available.</div>';
      return;
    }
    var usedUrls = [];
    wrap.innerHTML = heroes.map(function (h, idx) {
      var img = findImage(h, storyImages, usedUrls);
      if (img) usedUrls.push(img.url);
      var lead = idx === 0 ? ' lead' : '';
      var breaking = h.item && h.item.is_breaking === 'TRUE';
      return (
        '<a class="story-tile animate-on-scroll' + lead + (img ? '' : ' no-img') + ' tile-cat-' + esc(h.category).toLowerCase() + '" href="' + h.href + '">' +
          (img ? '<img class="story-tile-img" src="' + esc(img.url) + '" alt="' + esc(img.label) + '">' : '') +
          '<div class="story-tile-scrim"></div>' +
          '<div class="story-tile-body">' +
            '<div class="story-tile-meta">' +
              '<span class="' + pillClass(h.category) + '">' + esc(h.category) + '</span>' +
              (breaking ? '<span class="pill pill-military">breaking</span>' : '') +
              (h.kind === 'tracked' ? '<span class="story-tile-time">' + h.updates + ' update' + (h.updates === 1 ? '' : 's') + '</span>' : '') +
              '<span class="story-tile-time">' + fmtTime(h.time) + '</span>' +
            '</div>' +
            '<div class="story-tile-title">' + esc(h.title) + '</div>' +
            (idx === 0 && h.dek ? '<div class="story-tile-dek">' + esc(h.dek) + '</div>' : '') +
          '</div>' +
          (img && img.credit ? '<div class="story-tile-credit">' + esc(img.credit) + '</div>' : '') +
        '</a>'
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
    var rest = items.filter(function (it) { return heroItems.indexOf(it) === -1; }).slice(0, REST_LIMIT);
    var wrap = document.getElementById('rest-list');
    if (!rest.length) {
      wrap.innerHTML = '<div class="empty-note">Nothing else right now.</div>';
      return;
    }
    wrap.innerHTML = rest.map(function (it) {
      return (
        '<div class="card rest-row animate-on-scroll">' +
          '<span class="rest-time">' + fmtTime(it.created_at) + '</span>' +
          '<span class="' + pillClass(it.category) + '">' + esc(it.category || 'social') + '</span>' +
          '<span class="rest-text">' + esc(it.summary || it.full_text || '') + '</span>' +
          FeedItem.linkBtnHtml(it) +
        '</div>'
      );
    }).join('');

    if (window.Reveal) window.Reveal.scan(wrap);
  }

  DataLayer.loadFeed().then(function (data) {
    WatchlistStore.init(data.watchlist);
    var items = (data.tweetEnriched || []).slice().sort(function (a, b) {
      return (b.created_at || '').localeCompare(a.created_at || '');
    });
    var heroes = selectHeroes(items);
    renderHeroes(heroes, data.storyImages || []);
    renderRest(items, heroes);

    var meta = data.meta || {};
    if (meta.generated) {
      document.getElementById('page-sub').textContent =
        'The six main stories, followed by the rest of the news. Updated ' +
        meta.generated.slice(0, 16).replace('T', ' ') + ' UTC.';
    }
  }).catch(function (err) {
    console.error('Failed to load tracker data:', err);
    document.getElementById('story-hero').innerHTML =
      '<div class="empty-note">Failed to load data: ' + err.message + '</div>';
  });
})();
