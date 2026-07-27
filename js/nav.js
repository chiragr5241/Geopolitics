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

  var CHEVRON = '<svg class="user-menu__chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9.5l6 6 6-6"/></svg>';

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

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function initials(name) {
    return (name || '?').trim().charAt(0).toUpperCase();
  }

  /* User switcher — a placeholder for real login (see js/session.js). Renders
     a chip in .nav-right, LEFT of the theme toggle, listing every profile in
     the registry. The list is open-ended: profiles can be added and removed
     here, and each one carries its own watchlist, ordering and flags. */
  function userMenuHtml() {
    if (typeof Session === 'undefined') return '';
    var me = Session.current();
    var all = Session.users();
    var items = all.map(function (u) {
      var active = u.id === me.id;
      // Never offer a delete that Session would refuse (last user / last owner).
      var removable = all.length > 1 &&
        !(u.role === 'owner' && all.filter(function (x) { return x.role === 'owner'; }).length < 2);
      return '<div class="user-menu__row' + (active ? ' is-active' : '') + '">' +
          '<button type="button" class="user-menu__item"' +
            ' role="menuitemradio" aria-checked="' + (active ? 'true' : 'false') + '"' +
            ' data-user-id="' + esc(u.id) + '">' +
            '<span class="user-avatar user-avatar--sm">' + esc(initials(u.name)) + '</span>' +
            '<span class="user-menu__meta">' +
              '<span class="user-menu__name">' + esc(u.name) + '</span>' +
              '<span class="user-menu__role">' + esc(u.role) + '</span>' +
            '</span>' +
          '</button>' +
          (removable
            ? '<button type="button" class="user-menu__remove" data-remove-id="' + esc(u.id) + '"' +
                ' title="Delete this profile and its data" aria-label="Delete ' + esc(u.name) + '">&times;</button>'
            : '') +
        '</div>';
    }).join('');
    return '<div class="user-menu" id="user-menu">' +
        '<button type="button" class="user-menu__trigger" id="user-menu-trigger"' +
          ' aria-haspopup="true" aria-expanded="false" title="Change user">' +
          '<span class="user-avatar">' + esc(initials(me.name)) + '</span>' +
          '<span class="user-menu__label">' + esc(me.name) + '</span>' +
          CHEVRON +
        '</button>' +
        '<div class="user-menu__panel" role="menu" hidden>' +
          '<div class="user-menu__head">Signed in as</div>' +
          '<div class="user-menu__list">' + items + '</div>' +
          '<form class="user-menu__add" id="user-add-form">' +
            '<input type="text" id="user-add-name" placeholder="New profile name" maxlength="40" autocomplete="off" aria-label="New profile name">' +
            '<button type="submit" title="Add profile">Add</button>' +
          '</form>' +
          '<div class="user-menu__foot">Local profiles — real sign-in coming soon.</div>' +
        '</div>' +
      '</div>';
  }

  function wireUserMenu() {
    var wrap = document.getElementById('user-menu');
    if (!wrap) return;
    var trigger = wrap.querySelector('.user-menu__trigger');
    var panel = wrap.querySelector('.user-menu__panel');

    function close() {
      panel.hidden = true;
      wrap.classList.remove('is-open');
      trigger.setAttribute('aria-expanded', 'false');
    }
    function open() {
      panel.hidden = false;
      wrap.classList.add('is-open');
      trigger.setAttribute('aria-expanded', 'true');
    }

    trigger.addEventListener('click', function (e) {
      e.stopPropagation();
      if (panel.hidden) open(); else close();
    });
    panel.addEventListener('click', function (e) {
      var kill = e.target.closest ? e.target.closest('.user-menu__remove') : null;
      if (kill) {
        e.stopPropagation();
        var id = kill.getAttribute('data-remove-id');
        var victim = Session.users().filter(function (u) { return u.id === id; })[0];
        // Deleting a profile destroys its watchlist and flags — confirm first.
        if (!window.confirm('Delete the profile “' + (victim ? victim.name : id) +
            '” and everything it has tracked? This cannot be undone.')) return;
        var wasCurrent = Session.current().id === id;
        Session.removeUser(id);
        if (wasCurrent) return; // removeUser switched profiles and reloaded
        render();
        return;
      }
      var btn = e.target.closest ? e.target.closest('.user-menu__item') : null;
      if (!btn) return;
      close();
      Session.setUser(btn.getAttribute('data-user-id'));
    });

    var addForm = document.getElementById('user-add-form');
    if (addForm) {
      addForm.addEventListener('click', function (e) { e.stopPropagation(); });
      addForm.addEventListener('submit', function (e) {
        e.preventDefault();
        var input = document.getElementById('user-add-name');
        var user = Session.addUser(input.value);
        if (!user) { input.focus(); return; }
        // Switch straight into the new profile — that's what "add a user" means
        // here, and it reloads onto their (empty) page.
        Session.setUser(user.id);
      });
    }
    document.addEventListener('click', function (e) {
      if (!wrap.contains(e.target)) close();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') close();
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
          userMenuHtml() +
          '<label class="theme-toggle" title="Toggle light / dark">' +
            '<input type="checkbox" class="theme-toggle__input" id="theme-toggle" aria-label="Toggle colour theme">' +
            '<span class="theme-toggle__slider">' + SUN + MOON + '</span>' +
          '</label>' +
        '</div>' +
      '</nav>';
    wireToggle();
    wireUserMenu();
    syncTheme();
  }

  render();

  // Re-apply on back/forward cache restore — bfcache can resurrect a page with
  // a stale <html> class while localStorage is current.
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) syncTheme();
  });
})();
