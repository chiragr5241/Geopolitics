'use strict';

/* Home / daily-briefing page: top stories, tracked-story highlights,
   category digest. Read-only overview — marking happens on Feed,
   full timelines live on Tracker. */

(function () {
  function fmtTime(ts) {
    if (!ts) return '';
    var d = new Date((ts || '').replace(' ', 'T') + 'Z');
    if (isNaN(d.getTime())) return ts;
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  function pillClass(category) {
    return 'pill pill-' + (category || 'social').toLowerCase();
  }

  function renderHero(items) {
    var top = items
      .filter(function (it) { return it.is_breaking === 'TRUE' || parseInt(it.severity, 10) >= 4; })
      .slice(0, 12);
    var wrap = document.getElementById('hero-grid');
    if (!top.length) {
      wrap.innerHTML = '<div class="empty-note">No breaking or high-severity items right now.</div>';
      return;
    }
    wrap.innerHTML = top.map(function (it) {
      return (
        '<div class="card hero-card ' + (it.is_breaking === 'TRUE' ? 'breaking' : '') + '">' +
          '<div class="hero-meta">' +
            '<span class="' + pillClass(it.category) + '">' + (it.category || 'social') + '</span>' +
            '<span class="hero-time">' + fmtTime(it.created_at) + '</span>' +
          '</div>' +
          '<div class="hero-title">' + (it.summary || it.full_text || '') + '</div>' +
        '</div>'
      );
    }).join('');
  }

  function daysSince(dateStr) {
    if (!dateStr) return Infinity;
    var d = new Date(dateStr);
    if (isNaN(d.getTime())) return Infinity;
    return Math.floor((Date.now() - d.getTime()) / 86400000);
  }

  function renderStories() {
    var stories = WatchlistStore.all()
      .filter(function (s) { return s.status === 'active'; })
      .sort(function (a, b) { return (b.last_update_at || b.marked_at || '').localeCompare(a.last_update_at || a.marked_at || ''); })
      .slice(0, 4);
    var wrap = document.getElementById('story-grid');
    var section = document.getElementById('stories-section');
    if (!stories.length) { section.style.display = 'none'; return; }
    wrap.innerHTML = stories.map(function (s) {
      var stale = daysSince(s.last_update_at) > 14;
      return (
        '<a class="card story-mini" href="tracker.html" style="text-decoration:none;display:block;">' +
          '<div class="story-mini-title">' + s.title + '</div>' +
          '<div class="story-mini-meta"><span class="tracker-status ' + (stale ? 'stale' : 'active') + '">' + (stale ? 'stale' : 'active') + '</span><span>' + (s.update_count || 0) + ' updates</span></div>' +
        '</a>'
      );
    }).join('');
  }

  function renderDigest(items) {
    var counts = {};
    items.forEach(function (it) {
      var c = (it.category || 'social').toLowerCase();
      counts[c] = (counts[c] || 0) + 1;
    });
    var wrap = document.getElementById('digest-grid');
    wrap.innerHTML = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; }).map(function (c) {
      return '<div class="card card-pad" style="text-align:center;"><div style="font-family:var(--font-display);font-size:20px;font-weight:800;color:var(--bright);">' + counts[c] + '</div><span class="' + pillClass(c) + '" style="margin-top:6px;">' + c + '</span></div>';
    }).join('');
  }

  DataLayer.loadAll().then(function (data) {
    WatchlistStore.init(data.watchlist);
    var items = (data.tweetEnriched || []).slice().sort(function (a, b) {
      return (b.created_at || '').localeCompare(a.created_at || '');
    });
    renderHero(items);
    renderStories();
    renderDigest(items.slice(0, 500));

    var meta = data.meta || {};
    var counts = meta.counts || {};
    document.getElementById('stat-incidents').textContent = counts.incidents_total || '—';
    document.getElementById('stat-tweets').textContent = counts.tweets || '—';
    document.getElementById('stat-stories').textContent = counts.watchlist_active || 0;
    document.getElementById('stat-generated').textContent = meta.generated ? meta.generated.slice(0, 16).replace('T', ' ') : '—';
  }).catch(function (err) {
    console.error('Failed to load home data:', err);
    document.getElementById('hero-grid').innerHTML =
      '<div class="empty-note">Failed to load data: ' + err.message + '</div>';
  });
})();
