'use strict';

/* =========================================================
   SOURCES — the registry (data/sources.csv, shipped inside database.json /
   feed.json) plus the picker UI that puts it in front of the user.

   Two objects live here:

     SourceRegistry — read-only view of the registry, and the same resolution
       rules scripts/source_registry.py applies server-side: exact name / alias
       / domain, then a normalised match, then fuzzy for misspellings. Doing it
       in the browser too is what lets a typo get corrected WHILE the user is
       typing, instead of a day later when the routine next runs.

     SourcePicker — the multi-select. Every source starts selected, because
       "which sources should this story use" has an obvious right default and
       making people opt in one at a time would be tedious and worse. What the
       control is really for is the two edits that matter: switching a source
       OFF for a story, and typing in one we don't have.

   A story's selection is an overlay, never a copy of the registry:
     {selected: [id…], excluded: [id…], added: [{input, source_id, status,…}]}
   Absent = everything. So a story from before this feature existed, and a
   source added to the registry tomorrow, both behave the way you'd expect
   without anyone migrating anything.

   Resolution statuses a user-typed name can end up with:
     ok         — it's a source we know
     corrected  — misspelled or an alternate name; we fixed it and SAY SO
     unverified — we've never heard of it; the routine web-checks it next run
     not_found  — the routine looked and it doesn't appear to exist → the UI
                  highlights it. NOT the same as "exists but had no news",
                  which is normal and never flagged.
   ========================================================= */

var SourceRegistry = (function () {
  var rows = [];
  var index = {};
  var USABLE = { active: 1, unverified: 1 };

  var NOISE = { the: 1, a: 1, an: 1, news: 1, agency: 1, media: 1, press: 1,
                daily: 1, online: 1, network: 1, group: 1, com: 1, org: 1, net: 1 };

  function normalize(name) {
    var s = String(name || '').toLowerCase().replace(/https?:\/\//g, ' ');
    s = s.replace(/[^a-z0-9]+/g, ' ').trim();
    var words = s.split(' ').filter(function (w) { return w && !NOISE[w]; });
    return words.length ? words.join(' ') : s;
  }

  // 2·LCS / (len a + len b) — the same shape as Python's difflib ratio, which
  // is what scripts/source_registry.py fuzzy-matches with. Matching the metric
  // matters: if the browser corrected a name the routine wouldn't (or vice
  // versa) the two halves of this feature would disagree about what the user
  // typed. Character bigrams were tried first and rejected — they punish a
  // transposition so hard that "Kiyv Independant" missed.
  function similarity(a, b) {
    if (a === b) return 1;
    if (!a.length || !b.length) return 0;
    // Classic LCS DP over two rolling rows. Names are short; this only runs
    // when the user clicks Add.
    var prev = new Array(b.length + 1).fill(0);
    var cur = new Array(b.length + 1).fill(0);
    for (var i = 1; i <= a.length; i++) {
      cur[0] = 0;
      for (var j = 1; j <= b.length; j++) {
        cur[j] = a.charAt(i - 1) === b.charAt(j - 1)
          ? prev[j - 1] + 1
          : Math.max(prev[j], cur[j - 1]);
      }
      var swap = prev; prev = cur; cur = swap;
    }
    return (2 * prev[b.length]) / (a.length + b.length);
  }

  function aliasesOf(row) {
    return String(row.aliases || '').split(';')
      .map(function (a) { return a.trim(); })
      .filter(Boolean);
  }

  function init(sourceRows) {
    rows = (sourceRows || []).filter(function (r) { return r && r.source_id; });
    index = {};
    rows.forEach(function (r) { index[r.source_id] = r; });
    return rows;
  }

  function all() { return rows.slice(); }

  // What the picker offers: anything not retired. A not_found entry stays
  // visible on the story that introduced it so the user can see the problem
  // and fix the spelling, but it isn't offered to other stories.
  function selectable() {
    return rows.filter(function (r) { return USABLE[r.status]; });
  }

  function get(id) { return index[id] || null; }

  function displayName(id) {
    var r = index[id];
    return r ? r.name : id;
  }

  /* ── Resolution — mirrors source_registry.resolve() ─────────────────── */

  function resolveLocal(name) {
    var raw = String(name || '').trim();
    if (!raw) return { input: raw, status: 'unknown', source_id: '', name: '', score: 0 };
    var lowered = raw.toLowerCase();
    var i, r;

    // 1. Exact — id, canonical name, alias, or domain.
    for (i = 0; i < rows.length; i++) {
      r = rows[i];
      if (lowered === String(r.source_id).toLowerCase() ||
          lowered === String(r.name || '').toLowerCase()) {
        return hit('exact', raw, r, 1);
      }
      var al = aliasesOf(r);
      for (var j = 0; j < al.length; j++) {
        if (al[j].toLowerCase() === lowered) return hit('exact', raw, r, 1);
      }
      var dom = String(r.domain || '').toLowerCase();
      if (dom && (lowered === dom || lowered === 'www.' + dom)) return hit('exact', raw, r, 1);
    }

    // 2. A pasted URL or a name carrying a domain → match on the host.
    var host = '';
    var m = raw.match(/https?:\/\/([^/\s]+)/i);
    if (m) host = m[1].toLowerCase().replace(/^www\./, '');
    else if (/\b[a-z0-9-]+\.[a-z]{2,}\b/i.test(lowered)) {
      host = lowered.match(/\b[a-z0-9.-]+\.[a-z]{2,}\b/)[0].replace(/^www\./, '');
    }
    if (host) {
      for (i = 0; i < rows.length; i++) {
        var d = String(rows[i].domain || '').toLowerCase();
        if (d && (host === d || host.indexOf('.' + d) > -1 || d.indexOf('.' + host) > -1)) {
          return hit('corrected', raw, rows[i], 0.95);
        }
      }
    }

    // 3. Normalised — differs only by case, punctuation or a noise word.
    var key = normalize(raw);
    var keyed = [];
    rows.forEach(function (row) {
      [row.name, row.source_id].concat(aliasesOf(row)).forEach(function (cand) {
        var k = normalize(cand);
        if (k) keyed.push([k, row]);
      });
    });
    for (i = 0; i < keyed.length; i++) {
      if (keyed[i][0] === key) return hit('corrected', raw, keyed[i][1], 0.98);
    }

    // 4. Fuzzy — the actual misspelling case.
    var best = null, bestScore = 0;
    for (i = 0; i < keyed.length; i++) {
      var score = similarity(key, keyed[i][0]);
      if (score > bestScore) { bestScore = score; best = keyed[i][1]; }
    }
    // Same cutoff as source_registry.FUZZY_CUTOFF — keep the two in step.
    if (best && bestScore >= 0.84) return hit('corrected', raw, best, bestScore);

    return { input: raw, status: 'unknown', source_id: '', name: '', score: 0 };
  }

  function hit(status, input, row, score) {
    return {
      input: input,
      status: status,
      source_id: row.source_id,
      name: row.name,
      source_status: row.status,
      score: Math.round(score * 1000) / 1000,
    };
  }

  /* ── Per-story selection ────────────────────────────────────────────── */

  function selectionFor(story) {
    var s = (story && story.sources) || {};
    return {
      selected: (s.selected || []).slice(),
      excluded: (s.excluded || []).slice(),
      added: (s.added || []).slice(),
    };
  }

  // The sources this story will actually be researched with.
  function effectiveFor(story) {
    var excluded = {};
    selectionFor(story).excluded.forEach(function (id) { excluded[id] = 1; });
    return selectable().filter(function (r) { return !excluded[r.source_id]; });
  }

  // A fresh story starts with everything selected — that's the default the
  // Add form is required to show.
  function defaultSelection() {
    return {
      selected: selectable().map(function (r) { return r.source_id; }),
      excluded: [],
      added: [],
    };
  }

  // User-added entries still needing the routine's verdict, or already known
  // to be bad. These are what the UI highlights.
  function problemsIn(selection) {
    return (selection.added || []).filter(function (a) {
      var row = index[a.source_id];
      var st = (row && row.status) || a.status;
      return st === 'unverified' || st === 'not_found' || !a.source_id;
    });
  }

  return {
    init: init,
    all: all,
    selectable: selectable,
    get: get,
    displayName: displayName,
    resolveLocal: resolveLocal,
    normalize: normalize,
    selectionFor: selectionFor,
    effectiveFor: effectiveFor,
    defaultSelection: defaultSelection,
    problemsIn: problemsIn,
  };
})();


/* =========================================================
   SourcePicker — renders one selection and reads it back.

   Deliberately stateless between render and read: the DOM holds the state
   (chips carry data-on, added rows carry their resolution), so a caller can
   drop the markup into any form — the Add-story form, the inline editor, or
   the timeline header — and call read() when it saves.
   ========================================================= */

var SourcePicker = (function () {
  var seq = 0;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function chipHtml(row, on) {
    return (
      '<button type="button" class="source-chip' + (on ? ' on' : '') + '" ' +
        'data-src="' + esc(row.source_id) + '" data-on="' + (on ? '1' : '0') + '" ' +
        'title="' + esc((row.perspective || '') + (row.domain ? ' · ' + row.domain : '')) + '">' +
        '<span class="source-chip-tick" aria-hidden="true"></span>' +
        esc(row.name) +
      '</button>'
    );
  }

  function addedRowHtml(a) {
    var row = SourceRegistry.get(a.source_id);
    var status = (row && row.status) || a.status || 'unverified';
    var label, cls;
    if (a.status === 'corrected' || (a.resolved_name && a.resolved_name !== a.input)) {
      cls = 'corrected';
      label = 'corrected to ' + (a.resolved_name || (row && row.name) || '');
    } else if (status === 'not_found') {
      cls = 'not-found';
      label = 'no such source found — check the spelling';
    } else if (status === 'unverified') {
      cls = 'unverified';
      label = 'new — will be verified on the next run';
    } else {
      cls = 'ok';
      label = 'added';
    }
    return (
      '<div class="source-added ' + cls + '" data-added="' + esc(a.input) + '" ' +
        'data-src="' + esc(a.source_id || '') + '" data-status="' + esc(a.status || status) + '" ' +
        'data-resolved="' + esc(a.resolved_name || '') + '">' +
        '<span class="source-added-name">' + esc(a.input) + '</span>' +
        '<span class="source-added-note">' + esc(label) + '</span>' +
        '<button type="button" class="source-added-x" data-sp="drop" title="Remove">×</button>' +
      '</div>'
    );
  }

  /* Render a picker. `opts`:
       selection {selected, excluded, added} — defaults to everything selected
       compact   true  → collapsed behind a summary line (timeline header)
       title     heading text
  */
  function html(selection, opts) {
    opts = opts || {};
    selection = selection || SourceRegistry.defaultSelection();
    var id = 'sp' + (++seq);
    var excluded = {};
    selection.excluded.forEach(function (x) { excluded[x] = 1; });
    var rows = SourceRegistry.selectable();
    var onCount = rows.filter(function (r) { return !excluded[r.source_id]; }).length;
    var added = selection.added || [];
    var problems = SourceRegistry.problemsIn(selection).length;

    var summary =
      '<div class="source-picker-summary">' +
        '<span class="source-picker-count"><strong>' + onCount + '</strong> of ' +
          rows.length + ' sources</span>' +
        (problems ? '<span class="source-flag">' + problems + ' need' +
          (problems === 1 ? 's' : '') + ' checking</span>' : '') +
        '<button type="button" class="tracker-btn source-picker-toggle" data-sp="toggle">' +
          (opts.compact ? 'Edit sources' : 'Hide') + '</button>' +
      '</div>';

    var body =
      '<div class="source-picker-body"' + (opts.compact ? ' hidden' : '') + '>' +
        '<div class="source-picker-tools">' +
          '<input type="text" class="source-filter" data-sp="filter" placeholder="Filter sources…" autocomplete="off">' +
          '<button type="button" class="tracker-btn" data-sp="all">Select all</button>' +
          '<button type="button" class="tracker-btn" data-sp="none">Clear all</button>' +
        '</div>' +
        '<div class="source-chips">' +
          rows.map(function (r) { return chipHtml(r, !excluded[r.source_id]); }).join('') +
        '</div>' +
        '<div class="source-add">' +
          '<input type="text" class="source-add-input" data-sp="new" ' +
            'placeholder="Add a source by name or URL…" autocomplete="off">' +
          '<button type="button" class="tracker-btn" data-sp="add">Add source</button>' +
        '</div>' +
        '<div class="source-added-list">' + added.map(addedRowHtml).join('') + '</div>' +
        '<div class="source-picker-note">Everything is selected by default. Deselect a source ' +
          'to stop using it for this story from now on.</div>' +
      '</div>';

    return (
      '<div class="source-picker' + (opts.compact ? ' compact' : '') + '" data-picker="' + id + '">' +
        (opts.title ? '<div class="source-picker-head">' + esc(opts.title) + '</div>' : '') +
        summary + body +
      '</div>'
    );
  }

  // Read the current selection back out of the DOM.
  function read(root) {
    var picker = root.classList && root.classList.contains('source-picker')
      ? root : root.querySelector('.source-picker');
    if (!picker) return null;
    var selected = [], excluded = [];
    picker.querySelectorAll('.source-chip').forEach(function (chip) {
      (chip.dataset.on === '1' ? selected : excluded).push(chip.dataset.src);
    });
    var added = [];
    picker.querySelectorAll('.source-added').forEach(function (el) {
      added.push({
        input: el.dataset.added,
        source_id: el.dataset.src || '',
        status: el.dataset.status || 'unverified',
        resolved_name: el.dataset.resolved || '',
      });
    });
    return { selected: selected, excluded: excluded, added: added };
  }

  function refreshSummary(picker) {
    var chips = picker.querySelectorAll('.source-chip');
    var on = 0;
    chips.forEach(function (c) { if (c.dataset.on === '1') on++; });
    var count = picker.querySelector('.source-picker-count');
    if (count) count.innerHTML = '<strong>' + on + '</strong> of ' + chips.length + ' sources';
    var problems = SourceRegistry.problemsIn(read(picker)).length;
    var flag = picker.querySelector('.source-flag');
    if (problems && !flag) {
      flag = document.createElement('span');
      flag.className = 'source-flag';
      picker.querySelector('.source-picker-summary').insertBefore(
        flag, picker.querySelector('.source-picker-toggle'));
    }
    if (flag) {
      if (problems) flag.textContent = problems + ' need' + (problems === 1 ? 's' : '') + ' checking';
      else flag.remove();
    }
  }

  // Wire one rendered picker. `onChange(selection)` fires on every edit —
  // the timeline header uses it to persist immediately; the forms ignore it
  // and call read() on submit instead.
  function wire(root, onChange) {
    var picker = root.classList && root.classList.contains('source-picker')
      ? root : root.querySelector('.source-picker');
    if (!picker || picker.dataset.wired === '1') return;
    picker.dataset.wired = '1';

    function changed() {
      refreshSummary(picker);
      if (onChange) onChange(read(picker));
    }

    function addTyped() {
      var input = picker.querySelector('[data-sp="new"]');
      var name = (input.value || '').trim();
      if (!name) return;
      input.value = '';

      // Resolve against the registry right here: an exact hit just re-selects
      // the chip that was already there, a near hit is corrected (and the
      // correction is shown, not silently applied), and anything else is
      // recorded for the routine to web-verify.
      var res = SourceRegistry.resolveLocal(name);
      if (res.status !== 'unknown') {
        var chip = picker.querySelector('.source-chip[data-src="' + res.source_id + '"]');
        if (chip) {
          chip.dataset.on = '1';
          chip.classList.add('on');
          chip.classList.add('flash');
          setTimeout(function () { chip.classList.remove('flash'); }, 1200);
          try { chip.scrollIntoView({ block: 'nearest' }); } catch (e) { /* noop */ }
        }
        if (res.status === 'corrected') {
          appendAdded({ input: name, source_id: res.source_id, status: 'corrected',
                        resolved_name: res.name });
        }
      } else {
        appendAdded({ input: name, source_id: '', status: 'unverified', resolved_name: '' });
      }
      changed();
    }

    function appendAdded(entry) {
      var list = picker.querySelector('.source-added-list');
      var dup = list.querySelector('.source-added[data-added="' + entry.input.replace(/"/g, '') + '"]');
      if (dup) return;
      var wrap = document.createElement('div');
      wrap.innerHTML = addedRowHtml(entry);
      list.appendChild(wrap.firstChild);
    }

    picker.addEventListener('click', function (e) {
      var chip = e.target.closest('.source-chip');
      if (chip) {
        e.preventDefault();
        var on = chip.dataset.on === '1';
        chip.dataset.on = on ? '0' : '1';
        chip.classList.toggle('on', !on);
        changed();
        return;
      }
      var btn = e.target.closest('[data-sp]');
      if (!btn) return;
      var act = btn.dataset.sp;
      if (act === 'toggle') {
        e.preventDefault();
        var body = picker.querySelector('.source-picker-body');
        var hidden = body.hasAttribute('hidden');
        if (hidden) body.removeAttribute('hidden'); else body.setAttribute('hidden', '');
        btn.textContent = hidden ? 'Done' : 'Edit sources';
      } else if (act === 'all' || act === 'none') {
        e.preventDefault();
        picker.querySelectorAll('.source-chip').forEach(function (c) {
          if (c.hidden) return;                 // respect the filter
          c.dataset.on = act === 'all' ? '1' : '0';
          c.classList.toggle('on', act === 'all');
        });
        changed();
      } else if (act === 'add') {
        e.preventDefault();
        addTyped();
      } else if (act === 'drop') {
        e.preventDefault();
        var row = btn.closest('.source-added');
        if (row) row.remove();
        changed();
      }
    });

    var newInput = picker.querySelector('[data-sp="new"]');
    if (newInput) {
      newInput.addEventListener('keydown', function (e) {
        // Enter inside a form would submit it — this field means "add", not "save".
        if (e.key === 'Enter') { e.preventDefault(); addTyped(); }
      });
    }

    var filter = picker.querySelector('[data-sp="filter"]');
    if (filter) {
      filter.addEventListener('input', function () {
        var q = filter.value.trim().toLowerCase();
        picker.querySelectorAll('.source-chip').forEach(function (c) {
          c.hidden = !!q && c.textContent.toLowerCase().indexOf(q) === -1;
        });
      });
      filter.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') e.preventDefault();
      });
    }
  }

  return { html: html, read: read, wire: wire };
})();
