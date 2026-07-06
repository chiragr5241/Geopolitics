'use strict';

/* Tracker page — per-story chronological update timelines for whatever
   has been starred on the Feed page. Reads WatchlistStore (stories) and
   data.storyUpdates (rows appended by scripts/update_stories.py and
   scripts/add_story_update.py) and renders a vertical thread per story. */

(function () {
  var STALE_DAYS = 14;
  var storyUpdates = [];
  var selectedId = null;

  function daysSince(dateStr) {
    if (!dateStr) return Infinity;
    var d = new Date(dateStr);
    if (isNaN(d.getTime())) return Infinity;
    return Math.floor((Date.now() - d.getTime()) / 86400000);
  }

  function statusFor(story) {
    if (story.status === 'resolved') return 'resolved';
    if (story.status === 'archived') return 'archived';
    if (daysSince(story.last_update_at) > STALE_DAYS) return 'stale';
    return 'active';
  }

  function renderRail() {
    var stories = WatchlistStore.all().slice().sort(function (a, b) {
      return (b.last_update_at || b.marked_at || '').localeCompare(a.last_update_at || a.marked_at || '');
    });
    var rail = document.getElementById('tracker-rail');
    if (!stories.length) {
      rail.innerHTML = '<div class="empty-note">No stories marked yet.<br>Star items on the Feed page to start tracking them.</div>';
      return;
    }
    rail.innerHTML = stories.map(function (s) {
      var st = statusFor(s);
      var count = storyUpdates.filter(function (u) { return u.story_id === s.story_id; }).length;
      return (
        '<div class="card tracker-story-item ' + (s.story_id === selectedId ? 'selected' : '') + '" data-id="' + s.story_id + '">' +
          '<span class="tracker-status ' + st + '">' + st + '</span>' +
          '<div class="story-mini-title" style="margin-top:6px;">' + s.title + '</div>' +
          '<div class="story-mini-meta"><span>' + count + ' update' + (count === 1 ? '' : 's') + '</span><span>last: ' + (s.last_update_at || '—') + '</span></div>' +
        '</div>'
      );
    }).join('');
    rail.querySelectorAll('.tracker-story-item').forEach(function (el) {
      el.addEventListener('click', function () {
        selectedId = el.dataset.id;
        renderRail();
        renderMain();
      });
    });
  }

  function renderMain() {
    var main = document.getElementById('tracker-main');
    var story = WatchlistStore.all().filter(function (s) { return s.story_id === selectedId; })[0];
    if (!story) {
      main.innerHTML = '<div class="tracker-empty">Select a tracked story from the left to view its timeline.</div>';
      return;
    }
    var st = statusFor(story);
    var updates = storyUpdates
      .filter(function (u) { return u.story_id === story.story_id; })
      .sort(function (a, b) { return (a.date || '').localeCompare(b.date || ''); });

    var nodes = '<div class="timeline-node seed"><div class="card timeline-node-card">' +
      '<div class="timeline-node-meta"><span class="origin-tag">seed</span><span>' + (story.seed.created_at || story.marked_at || '') + '</span></div>' +
      '<div class="timeline-node-headline">Marked important</div>' +
      '<div class="timeline-node-summary">' + (story.seed.text || '') + '</div>' +
    '</div></div>';

    nodes += updates.map(function (u) {
      return (
        '<div class="timeline-node"><div class="card timeline-node-card">' +
          '<div class="timeline-node-meta">' +
            '<span class="origin-tag">' + (u.origin || 'update') + '</span>' +
            '<span>' + u.date + '</span>' +
            (u.status ? '<span>· ' + u.status + '</span>' : '') +
          '</div>' +
          '<div class="timeline-node-headline">' + u.headline + '</div>' +
          '<div class="timeline-node-summary">' + (u.summary || '') + '</div>' +
          (u.source_name || u.url ?
            '<div class="timeline-node-source">' +
              (u.url ? '<a href="' + u.url + '" target="_blank" rel="noopener">' + (u.source_name || u.url) + '</a>' : u.source_name) +
            '</div>' : '') +
        '</div></div>'
      );
    }).join('');

    main.innerHTML =
      '<div class="card tracker-story-header">' +
        '<span class="tracker-status ' + st + '">' + st + '</span>' +
        '<div class="tracker-story-title">' + story.title + '</div>' +
        '<div class="story-mini-meta"><span>' + updates.length + ' update' + (updates.length === 1 ? '' : 's') + '</span><span>marked ' + (story.marked_at || '').slice(0, 10) + '</span></div>' +
        '<div class="tracker-story-actions">' +
          (story.status !== 'resolved' ? '<button class="tracker-btn" data-action="resolve">Mark resolved</button>' : '<button class="tracker-btn" data-action="reactivate">Reactivate</button>') +
          (story.status !== 'archived' ? '<button class="tracker-btn" data-action="archive">Archive</button>' : '') +
        '</div>' +
      '</div>' +
      '<div class="timeline-thread">' + nodes + '</div>';

    main.querySelectorAll('[data-action]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var action = btn.dataset.action;
        var status = action === 'resolve' ? 'resolved' : action === 'reactivate' ? 'active' : 'archived';
        WatchlistStore.setStatus(story.story_id, status);
        renderRail();
        renderMain();
      });
    });
  }

  DataLayer.loadAll().then(function (data) {
    WatchlistStore.init(data.watchlist);
    storyUpdates = data.storyUpdates || [];
    var stories = WatchlistStore.all();
    if (stories.length) {
      selectedId = stories.slice().sort(function (a, b) {
        return (b.last_update_at || b.marked_at || '').localeCompare(a.last_update_at || a.marked_at || '');
      })[0].story_id;
    }
    renderRail();
    renderMain();

    var exportBtn = document.getElementById('export-watchlist-btn');
    if (exportBtn) exportBtn.addEventListener('click', function () { WatchlistStore.exportFile(); });
  }).catch(function (err) {
    console.error('Failed to load tracker data:', err);
    document.getElementById('tracker-main').innerHTML =
      '<div class="empty-note">Failed to load data: ' + err.message + '</div>';
  });
})();
