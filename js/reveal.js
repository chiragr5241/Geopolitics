'use strict';

/* Scroll reveal — mirrors the personal site's `.animate-on-scroll` → `.visible`
   pattern (chirag5241.github.io/website), but driven by IntersectionObserver
   instead of a scroll handler so it's cheap and reveals each block only as it
   enters the viewport.

   This pairs with `content-visibility: auto` on the heavy repeated items
   (feed cards, story tiles, timeline nodes): the browser skips layout/paint
   for off-screen content, and this fades each piece in as you reach it — so
   the page renders progressively instead of all at once.

   Because the news pages build their lists after data loads, call
   window.Reveal.scan() at the end of each render to pick up new nodes. */

(function () {
  var supported = 'IntersectionObserver' in window;
  var reduceMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var io = null;

  function revealNow(el) { el.classList.add('visible'); }

  function ensureObserver() {
    if (io) return io;
    io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          revealNow(entry.target);
          io.unobserve(entry.target);
        }
      });
    }, {
      // Trigger a touch before the element is fully in view so the reveal
      // feels responsive rather than lagging behind the scroll.
      root: null,
      rootMargin: '0px 0px -8% 0px',
      threshold: 0.04,
    });
    return io;
  }

  function scan(root) {
    root = root || document;
    var nodes = root.querySelectorAll('.animate-on-scroll');
    // No IO or reduced-motion preference: just show everything immediately.
    if (!supported || reduceMotion) {
      for (var i = 0; i < nodes.length; i++) revealNow(nodes[i]);
      return;
    }
    var observer = ensureObserver();
    for (var j = 0; j < nodes.length; j++) {
      var el = nodes[j];
      if (el.dataset.revealBound) continue;
      el.dataset.revealBound = '1';
      observer.observe(el);
    }
  }

  window.Reveal = { scan: scan };

  document.addEventListener('DOMContentLoaded', function () { scan(document); });
})();
