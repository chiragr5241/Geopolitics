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

  return {
    esc: esc,
    fmtTime: fmtTime,
    ageDays: ageDays,
    score: score,
    countrySet: countrySet,
    jaccard: jaccard,
    sameStory: sameStory,
  };
})();
