'use strict';

/* Shared helpers used by the news pages (home, feed, tracker). These were
   previously copy-pasted into each page script; centralising them keeps a
   single source of truth. Exposed as a `Util` global (same IIFE pattern as
   FeedItem). The map (app.js) has its own map-specific variants and does not
   depend on this module. */

var Util = (function () {

  function esc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // "Mar 24, 14:30"-style short timestamp. Data timestamps are UTC-naive
  // ("2026-03-24 16:40:02"); we treat them as UTC and render in local time.
  function fmtTime(ts) {
    if (!ts) return '';
    var d = new Date((ts || '').replace(' ', 'T') + 'Z');
    if (isNaN(d.getTime())) return ts;
    return d.toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  }

  function ageDays(ts) {
    var d = new Date((ts || '').replace(' ', 'T') + 'Z');
    if (isNaN(d.getTime())) return 999;
    return (Date.now() - d.getTime()) / 86400000;
  }

  // Story-ranking score: severity + breaking bonus, decayed by age.
  function score(it) {
    var sev = parseInt(it.severity, 10) || 0;
    return sev * 2 + (it.is_breaking === 'TRUE' ? 3 : 0) - ageDays(it.created_at) * 0.6;
  }

  function countrySet(it) {
    return (it.countries || '').split(';').map(function (c) { return c.trim(); }).filter(Boolean);
  }

  function jaccard(a, b) {
    if (!a.length || !b.length) return 0;
    var inter = a.filter(function (x) { return b.indexOf(x) !== -1; }).length;
    return inter / (a.length + b.length - inter);
  }

  // Two feed items are "the same story" if their country sets mostly overlap
  // or they share a subcategory — keeps grids from filling with variations of
  // the same conflict.
  function sameStory(a, b) {
    if (a.subcategory && a.subcategory === b.subcategory) return true;
    return jaccard(countrySet(a), countrySet(b)) >= 0.5;
  }

  // Normalise a headline for dedup keys (shared by buildStoryEntries).
  function normHead(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9 ]/g, ' ')
      .replace(/\s+/g, ' ').trim().slice(0, 70);
  }

  // ── Merged story timeline: curated beats + every linked feed tweet ────────
  // Curated story_updates are the hand/agent-authored beats; linked tweets come
  // from linked_story_ids (the whole feed, retroactively) and carry enriched
  // context/sources. We merge, drop near-duplicates (by date|normHead), and
  // sort NEWEST-FIRST. This is the SINGLE source of truth for a story's update
  // list — used by the Tracker (rail count + timeline thread) AND the main
  // page's hero tiles, so the number shown always matches reality (a story's
  // static `update_count` field is NOT reliable — it's rarely kept in sync,
  // e.g. it stays 0 for a story whose only coverage is linked feed tweets).
  function buildStoryEntries(story, storyUpdates, feedItems) {
    var feedByNorm = {};
    feedItems.forEach(function (it) {
      var fk = (it.created_at || '').slice(0, 10) + '|' + normHead(it.summary || it.full_text);
      if (!feedByNorm[fk]) feedByNorm[fk] = it;
    });

    var seen = {};
    var entries = [];

    // Curated beats first (authoritative — dedup wins over a raw tweet).
    storyUpdates.filter(function (u) { return u.story_id === story.story_id; })
      .forEach(function (u) {
        var head = u.headline || u.summary || '';
        var k = (u.date || '') + '|' + normHead(head);
        if (seen[k]) return;
        seen[k] = 1;
        entries.push({
          date: u.date || '', headline: head, summary: u.summary || '',
          origin: u.origin || 'update', status: u.status || '',
          source_name: u.source_name || '', url: u.url || '',
          feed: (!u.url && feedByNorm[k]) || null,
        });
      });

    // Every linked feed tweet.
    feedItems.filter(function (it) {
      return String(it.linked_story_ids || '').split(';').indexOf(story.story_id) !== -1;
    }).forEach(function (it) {
      var date = (it.created_at || '').slice(0, 10);
      var head = it.summary || it.full_text || '';
      var k = date + '|' + normHead(head);
      if (seen[k]) return;
      seen[k] = 1;
      entries.push({
        date: date, headline: head, summary: '',
        origin: 'feed', status: '', source_name: 'Spectator Index', url: '',
        feed: it,
      });
    });

    // Newest first.
    entries.sort(function (a, b) { return (b.date || '').localeCompare(a.date || ''); });
    return entries;
  }

  function countStoryEntries(story, storyUpdates, feedItems) {
    return buildStoryEntries(story, storyUpdates, feedItems).length;
  }

  return {
    esc: esc,
    fmtTime: fmtTime,
    ageDays: ageDays,
    score: score,
    countrySet: countrySet,
    jaccard: jaccard,
    sameStory: sameStory,
    buildStoryEntries: buildStoryEntries,
    countStoryEntries: countStoryEntries,
  };
})();
