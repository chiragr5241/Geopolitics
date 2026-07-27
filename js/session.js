'use strict';

/* =========================================================
   SESSION — the user registry and who is currently active.

   Placeholder for real auth, built to the shape the real thing will need:
   an OPEN-ENDED list of users, each with a generated id, addressed
   identically. There is no privileged user whose data lives somewhere
   special — user 1 and user 5000 are stored the same way (see UserStore) —
   so "add another user" stays a constant-cost operation.

   What the backend replaces, and nothing else:
     - `list()`  → GET  /api/users            (or just the signed-in account)
     - `current()` → the session/JWT subject, not a localStorage value
     - `addUser()` / `removeUser()` → real registration + admin
   Everything downstream already asks this module who the user is, and asks
   UserStore for that user's data, so neither needs to change.

   Roles are coarse on purpose: 'owner' can publish (export the catalog),
   'member' can only curate their own page. That maps onto a real permission
   check later without reshaping the data.
   ========================================================= */

var Session = (function () {
  var USERS_KEY = 'geo.users.v1';
  var CURRENT_KEY = 'geo.session.v1';

  // The first account. Its id is fixed because the pre-multi-user data in
  // this browser gets migrated onto it (see migrateLegacy).
  var OWNER = { id: 'chirag', name: 'Chirag', role: 'owner' };

  var users = null;
  var currentId = null;

  function nowIso() {
    return new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  }

  function readUsers() {
    try {
      var raw = localStorage.getItem(USERS_KEY);
      var doc = raw ? JSON.parse(raw) : null;
      if (doc && doc.users && doc.users.length) return doc.users;
    } catch (e) { /* fall through to the seed */ }
    return null;
  }

  function writeUsers() {
    try {
      localStorage.setItem(USERS_KEY, JSON.stringify({
        version: 1, updated_at: nowIso(), users: users,
      }));
    } catch (e) { /* ignore — the list still works in-session */ }
  }

  // Move this browser's pre-multi-user data onto the owner's namespace, so
  // the "one bare key" era ends without anyone losing their watchlist.
  function migrateLegacy() {
    if (typeof UserStore === 'undefined') return;
    UserStore.adoptLegacy('geo.watchlist.v1', OWNER.id, 'watchlist');
    UserStore.adoptLegacy('geo.flags.v1', OWNER.id, 'flags');
    // The short-lived '::<id>' suffix scheme that preceded UserStore.
    var users_ = users || [];
    users_.forEach(function (u) {
      UserStore.adoptLegacy('geo.watchlist.v1::' + u.id, u.id, 'watchlist');
      UserStore.adoptLegacy('geo.flags.v1::' + u.id, u.id, 'flags');
    });
  }

  function ensureLoaded() {
    if (users) return;
    users = readUsers();
    var seeded = false;
    if (!users) {
      // First run: the owner plus one extra profile to exercise multi-user.
      users = [
        { id: OWNER.id, name: OWNER.name, role: OWNER.role, created_at: nowIso() },
        { id: 'other', name: 'Other', role: 'member', created_at: nowIso() },
      ];
      seeded = true;
    }
    migrateLegacy();
    if (seeded) writeUsers();

    try { currentId = localStorage.getItem(CURRENT_KEY); } catch (e) { currentId = null; }
    if (!byId(currentId)) currentId = users[0].id;
  }

  function byId(id) {
    if (!id || !users) return null;
    return users.filter(function (u) { return u.id === id; })[0] || null;
  }

  function list() {
    ensureLoaded();
    return users.slice();
  }

  function current() {
    ensureLoaded();
    return byId(currentId) || users[0];
  }

  function currentId_() {
    ensureLoaded();
    return current().id;
  }

  function isOwner() {
    return current().role === 'owner';
  }

  // Ids must be unique and stable; the name is free to change and to repeat.
  function makeId(name) {
    var base = String(name || 'user').toLowerCase()
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 24) || 'user';
    var id = base;
    var n = 2;
    while (byId(id)) { id = base + '-' + n; n++; }
    return id;
  }

  function addUser(name, role) {
    ensureLoaded();
    name = String(name || '').trim();
    if (!name) return null;
    var user = {
      id: makeId(name),
      name: name.slice(0, 40),
      role: role === 'owner' ? 'owner' : 'member',
      created_at: nowIso(),
    };
    users.push(user);
    writeUsers();
    return user;
  }

  function renameUser(id, name) {
    ensureLoaded();
    var u = byId(id);
    if (!u || !String(name || '').trim()) return null;
    u.name = String(name).trim().slice(0, 40);
    writeUsers();
    return u;
  }

  // Removing a user takes their data with them. The last remaining user, and
  // the last owner, can't be removed — otherwise the site locks itself out.
  function removeUser(id) {
    ensureLoaded();
    var u = byId(id);
    if (!u || users.length < 2) return false;
    if (u.role === 'owner' && users.filter(function (x) { return x.role === 'owner'; }).length < 2) return false;
    users = users.filter(function (x) { return x.id !== id; });
    writeUsers();
    if (typeof UserStore !== 'undefined') UserStore.clearUser(id);
    if (currentId === id) setUser(users[0].id);
    return true;
  }

  // Switching swaps every per-user store at once and the pages read those at
  // boot, so a reload is the honest way to apply it.
  function setUser(id, opts) {
    ensureLoaded();
    if (!byId(id) || id === currentId) return false;
    currentId = id;
    try { localStorage.setItem(CURRENT_KEY, id); } catch (e) { /* ignore */ }
    if (!opts || opts.reload !== false) location.reload();
    return true;
  }

  return {
    current: current,
    currentId: currentId_,
    users: list,
    isOwner: isOwner,
    setUser: setUser,
    addUser: addUser,
    renameUser: renameUser,
    removeUser: removeUser,
    OWNER_ID: OWNER.id,
  };
})();
