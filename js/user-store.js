'use strict';

/* =========================================================
   USER STORE — per-user persistence, behind one seam.

   Every piece of state that belongs to ONE person (their followed stories,
   their ordering, their flags) is read and written through here, keyed by
   user id. Nothing else in the app touches localStorage for user data.

   That's the whole point: today the backend is the browser, tomorrow it's a
   server, and only this file changes. The HTTP version is:

     function read(userId, name) {
       return fetch('/api/users/' + userId + '/' + name).then(r => r.json());
     }

   which makes every read async — so callers already treat `load()` as the
   boundary and keep a local copy, rather than reading on every render.

   Key layout: geo.u.<userId>.<name>. Namespacing by user id (with no
   privileged "bare key" user) is what lets the user list grow without
   bound — user 5000's data is addressed exactly like user 1's.
   ========================================================= */

var UserStore = (function () {
  var PREFIX = 'geo.u.';

  function keyFor(userId, name) {
    return PREFIX + userId + '.' + name;
  }

  function load(userId, name) {
    if (!userId) return null;
    try {
      var raw = localStorage.getItem(keyFor(userId, name));
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null; // unreadable / corrupt — caller starts fresh
    }
  }

  function save(userId, name, value) {
    if (!userId) return false;
    try {
      localStorage.setItem(keyFor(userId, name), JSON.stringify(value));
      return true;
    } catch (e) {
      return false; // quota or private mode — state still works in-session
    }
  }

  function remove(userId, name) {
    try { localStorage.removeItem(keyFor(userId, name)); } catch (e) { /* ignore */ }
  }

  // Drop everything belonging to a user — used when a profile is deleted, so
  // removing a user doesn't leave orphaned rows behind forever.
  function clearUser(userId) {
    if (!userId) return;
    var pre = PREFIX + userId + '.';
    var doomed = [];
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (k && k.indexOf(pre) === 0) doomed.push(k);
      }
      doomed.forEach(function (k) { localStorage.removeItem(k); });
    } catch (e) { /* ignore */ }
  }

  // One-time move of a pre-multi-user key into a user's namespace. No-op if
  // the source is gone or the destination already has data.
  function adoptLegacy(legacyKey, userId, name) {
    try {
      var raw = localStorage.getItem(legacyKey);
      if (raw == null) return false;
      if (localStorage.getItem(keyFor(userId, name)) == null) {
        localStorage.setItem(keyFor(userId, name), raw);
      }
      localStorage.removeItem(legacyKey);
      return true;
    } catch (e) {
      return false;
    }
  }

  return {
    load: load,
    save: save,
    remove: remove,
    clearUser: clearUser,
    adoptLegacy: adoptLegacy,
  };
})();
