'use strict';

/* FLAG STORE — the user's flagged / favourite feed items.

   Deliberately separate from WatchlistStore. Tracking a story (WatchlistStore)
   is an editorial act: it seeds a timeline, gets committed to watchlist.json,
   and the pipeline keeps feeding it. Flagging is a purely personal bookmark —
   "come back to this one" — so it stays on the device and is never exported.

   A flag is the FIRST tag on a card: it renders in the same `.story-tags` row
   as the story chips, ahead of them, and it drives its own filter.

   Keyed by FeedItem.itemKey(item) so a flag survives re-sorting, filtering, and
   the daily data rebuild. */

var FlagStore = (function () {
  // Per-user, through the same seam as the watchlist (js/user-store.js) —
  // flags are personal, so every profile gets its own set and none of them
  // is stored specially.
  var DOC_NAME = 'flags';
  var keys = Object.create(null);

  function uid() {
    return (typeof Session !== 'undefined') ? Session.currentId() : 'local';
  }

  function load() {
    if (typeof UserStore === 'undefined') return;
    var doc = UserStore.load(uid(), DOC_NAME);
    (doc && doc.keys || []).forEach(function (k) { if (k) keys[k] = 1; });
  }

  function save() {
    if (typeof UserStore === 'undefined') return;
    UserStore.save(uid(), DOC_NAME, {
      version: 1,
      updated_at: new Date().toISOString(),
      keys: Object.keys(keys),
    });
  }

  function keyOf(itemOrKey) {
    if (!itemOrKey) return '';
    return typeof itemOrKey === 'string' ? itemOrKey : FeedItem.itemKey(itemOrKey);
  }

  function isFlagged(itemOrKey) {
    var k = keyOf(itemOrKey);
    return !!(k && keys[k]);
  }

  function add(itemOrKey) {
    var k = keyOf(itemOrKey);
    if (!k) return false;
    keys[k] = 1;
    save();
    return true;
  }

  function remove(itemOrKey) {
    var k = keyOf(itemOrKey);
    if (!k) return false;
    delete keys[k];
    save();
    return false;
  }

  // Returns the NEW state, so a caller can re-render off the return value.
  function toggle(itemOrKey) {
    return isFlagged(itemOrKey) ? remove(itemOrKey) : add(itemOrKey);
  }

  function count() {
    return Object.keys(keys).length;
  }

  function clear() {
    keys = Object.create(null);
    save();
  }

  load();

  return {
    isFlagged: isFlagged,
    add: add,
    remove: remove,
    toggle: toggle,
    count: count,
    clear: clear,
  };
})();
