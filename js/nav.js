'use strict';

/* Shared top nav, injected into <div id="site-nav-mount"></div> on every
   page. Kept as a tiny standalone script (no dependency on DataLayer or
   config.js) so it can run before the page's data finishes loading. */

(function () {
  var PAGES = [
    { href: 'index.html',   key: 'home',    label: 'Briefing' },
    { href: 'feed.html',    key: 'feed',    label: 'Feed' },
    { href: 'tracker.html', key: 'tracker', label: 'Tracker' },
    { href: 'map.html',     key: 'map',     label: 'Map' },
  ];

  function currentKey() {
    var path = (location.pathname.split('/').pop() || 'index.html');
    if (path === '' || path === '/') path = 'index.html';
    var found = PAGES.filter(function (p) { return p.href === path; })[0];
    return found ? found.key : 'home';
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
        '<div class="nav-brand">OSINT<span class="nav-brand-sub">DAILY</span></div>' +
        '<div class="nav-links">' + links + '</div>' +
        '<div class="nav-right"><span class="live-dot"></span>LIVE</div>' +
      '</nav>';
  }

  render();
})();
