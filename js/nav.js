'use strict';

/* Shared top nav, injected into <div id="site-nav-mount"></div> on every
   page. Kept as a tiny standalone script (no dependency on DataLayer or
   config.js) so it can run before the page's data finishes loading.

   Mirrors the personal site (chirag5241.github.io/website): a sticky,
   translucent bar with a sliding sun/moon theme toggle and a link back to
   the personal site. The theme class is applied pre-paint by a tiny inline
   script in each page's <head> (to avoid a flash); here we render the
   control and wire it. Uses the same localStorage key ('theme') and the
   same "checked = light mode" convention as the personal site. */

(function () {
  var PAGES = [
    { href: 'index.html',   key: 'home',    label: 'Tracker' },
    { href: 'feed.html',    key: 'feed',    label: 'Feed' },
    { href: 'tracker.html', key: 'tracker', label: 'Timelines' },
    { href: 'map.html',     key: 'map',     label: 'Map' },
  ];

  var PERSONAL_URL = 'https://chirag5241.github.io/website/';

  var SUN = '<svg class="theme-toggle__icon theme-toggle__icon--sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4.5"/><path d="M12 1.5v2.5M12 20v2.5M3.5 3.5l1.8 1.8M18.7 18.7l1.8 1.8M1.5 12h2.5M20 12h2.5M3.5 20.5l1.8-1.8M18.7 5.3l1.8-1.8"/></svg>';
  var MOON = '<svg class="theme-toggle__icon theme-toggle__icon--moon" viewBox="0 0 24 24" fill="currentColor"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';

  function currentKey() {
    var path = (location.pathname.split('/').pop() || 'index.html');
    if (path === '' || path === '/') path = 'index.html';
    var found = PAGES.filter(function (p) { return p.href === path; })[0];
    return found ? found.key : 'home';
  }

  function applyTheme(theme) {
    var root = document.documentElement;
    if (theme === 'dark') root.classList.remove('light-mode');
    else root.classList.add('light-mode');
  }

  // localStorage is the single source of truth; the personal site (same origin)
  // ships no theme JS and is always light, so an UNSET preference defaults to
  // light — matching it. Reconciling here (not just in the pre-paint inline
  // script) fixes desyncs where the class and the stored value disagree, e.g.
  // after a bfcache restore, so the Feed can't open dark while storage says light.
  function storedTheme() {
    try { return localStorage.getItem('theme') === 'dark' ? 'dark' : 'light'; }
    catch (e) { return 'light'; }
  }

  function syncTheme() {
    applyTheme(storedTheme());
    var input = document.getElementById('theme-toggle');
    if (input) input.checked = isLight();
  }

  function isLight() {
    return document.documentElement.classList.contains('light-mode');
  }

  function wireToggle() {
    var input = document.getElementById('theme-toggle');
    if (!input) return;
    // "checked" means light mode, matching the personal site.
    input.checked = isLight();
    input.addEventListener('change', function () {
      var theme = input.checked ? 'light' : 'dark';
      applyTheme(theme);
      try { localStorage.setItem('theme', theme); } catch (e) { /* ignore */ }
    });
  }

  function render() {
    var mount = document.getElementById('site-nav-mount');
    if (!mount) return;
    var active = currentKey();
    var links = PAGES.map(function (p) {
      return '<a href="' + p.href + '" class="' + (p.key === active ? 'active' : '') + '">' + p.label + '</a>';
    }).join('');
    mount.outerHTML =
      '<nav id="site-nav">' +
        '<a class="nav-brand" href="' + PERSONAL_URL + '">chirag</a>' +
        '<div class="nav-links">' + links + '</div>' +
        '<div class="nav-right">' +
          '<label class="theme-toggle" title="Toggle light / dark">' +
            '<input type="checkbox" class="theme-toggle__input" id="theme-toggle" aria-label="Toggle colour theme">' +
            '<span class="theme-toggle__slider">' + SUN + MOON + '</span>' +
          '</label>' +
        '</div>' +
      '</nav>';
    wireToggle();
    syncTheme();
  }

  render();

  // Re-apply on back/forward cache restore — bfcache can resurrect a page with
  // a stale <html> class while localStorage is current.
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) syncTheme();
  });
})();
