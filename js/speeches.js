'use strict';

/* UN General Debate page — reads data/un_speeches/unga<N>.json (built by
   scripts/analyze_un_speeches.py) and renders:

     topic prevalence bars · concern-cluster map · friendliness network ·
     per-nation detail · rights of reply · filterable address cards · method

   Colour follows the site rule (tokens.css): neutrals carry everything, the
   accent marks selection / warmth, --accent2 (the one alarm colour) marks
   hostility. Clusters therefore get marker SHAPES, not hues.

   Both layouts (map de-overlap, network) run their force simulations to
   completion synchronously — no rAF ticking — so they render the same in a
   hidden tab or a screenshot as on screen. */

(function () {
  var esc = Util.esc;
  var D = null;              // the whole dataset
  var N = [];                // nations, dataset order (= friendliness order)
  var byIso = {};
  var topicLabel = {};
  var selected = null;       // iso2 of the selected nation
  var filter = { topic: null, cluster: null, q: '' };
  var showInferred = false;
  var tip = document.getElementById('un-tip');

  var SHAPES = [d3.symbolCircle, d3.symbolSquare, d3.symbolTriangle, d3.symbolDiamond,
                d3.symbolCross, d3.symbolStar, d3.symbolWye];
  // Always-labelled on the map/network: the speeches people will look for.
  var MARQUEE = ['US', 'CN', 'RU', 'IN', 'BR', 'FR', 'GB', 'DE', 'JP', 'IR', 'IL', 'PS',
                 'UA', 'TR', 'SA', 'ZA', 'PK', 'EU'];

  function param(name) {
    try { return new URLSearchParams(location.search).get(name); } catch (e) { return null; }
  }

  function flag(iso) {
    if (!iso || iso.length !== 2) return '';
    return String.fromCodePoint.apply(null, iso.toUpperCase().split('').map(function (c) {
      return 0x1F1E6 + c.charCodeAt(0) - 65;
    }));
  }

  function shapePath(cluster, size) {
    return d3.symbol().type(SHAPES[cluster % SHAPES.length]).size(size || 64)();
  }

  function shapeSvg(cluster, px) {
    px = px || 14;
    return '<svg class="un-shape" width="' + px + '" height="' + px + '" viewBox="-8 -8 16 16" aria-hidden="true">' +
      '<path d="' + shapePath(cluster, 70) + '"></path></svg>';
  }

  // Friendliness lookup in the flat upper triangle.
  function fIndex(i, j) {
    var n = N.length;
    if (i > j) { var t = i; i = j; j = t; }
    return i * n - (i * (i + 1)) / 2 + (j - i - 1);
  }
  function friend(a, b) {
    var i = N.indexOf(byIso[a]), j = N.indexOf(byIso[b]);
    if (i < 0 || j < 0 || i === j) return null;
    var k = fIndex(i, j);
    return { score: D.friendliness.tri[k], basis: D.friendliness.basis[k] };
  }

  function stanceWord(s) {
    if (s >= 1.5) return 'strong support';
    if (s >= 0.5) return 'supportive';
    if (s > -0.5) return 'neutral';
    if (s > -1.5) return 'critical';
    return 'hostile';
  }
  // Where a summary came from: the full speech, or the UN's per-speaker
  // meeting coverage (used while YouTube blocked transcript downloads).
  function sourceHtml(n) {
    if (n.src === 'un_press') {
      return '<a class="un-src" href="' + esc(n.source_url || 'https://press.un.org/') + '" target="_blank" rel="noopener" ' +
        'title="Summarised from the UN\'s official meeting coverage of this speech">UN coverage</a>';
    }
    return '<span class="un-src transcript" title="Summarised from the full speech transcript">transcript</span>';
  }

  // A weak lean shouldn't read as taking a side.
  function posWord(v, p) {
    var a = Math.abs(v);
    if (a < 0.2) return 'neutral';
    var side = v > 0 ? p.plus : p.minus;
    return a < 0.6 ? 'leans: ' + side : side;
  }
  function stanceClass(s) { return s >= 0.5 ? 'warm' : s <= -0.5 ? 'cool' : 'flat'; }

  // ── Tooltip ──────────────────────────────────────────────────────────
  function showTip(html, ev) {
    tip.innerHTML = html;
    tip.hidden = false;
    var pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    var x = ev.clientX + pad, y = ev.clientY + pad;
    if (x + w > window.innerWidth - 8) x = ev.clientX - w - pad;
    if (y + h > window.innerHeight - 8) y = ev.clientY - h - pad;
    tip.style.left = Math.max(8, x) + 'px';
    tip.style.top = Math.max(8, y) + 'px';
  }
  function hideTip() { tip.hidden = true; }

  function nationTip(n) {
    return '<div class="un-tip-title">' + flag(n.iso2) + ' ' + esc(n.country) + '</div>' +
      '<div class="un-tip-sub">' + esc(n.speaker) + ' · ' + esc(n.role) + '</div>' +
      '<div class="un-tip-body">' + esc(n.primary_concern) + '</div>' +
      '<div class="un-tip-sub">Cluster ' + (n.cluster + 1) + ' · ' + esc(D.clusters[n.cluster].label) + '</div>';
  }

  // ── Header + stats ───────────────────────────────────────────────────
  function renderHeader() {
    var cov = D.coverage;
    document.getElementById('un-title').textContent = 'UN General Debate · ' + D.session + 'st session';
    var story = param('story');
    if (story) document.getElementById('un-back').href = 'tracker.html?story=' + encodeURIComponent(story);
    document.getElementById('un-sub').textContent =
      cov.summarised + ' national addresses summarised (' + cov.from_transcript + ' from full transcripts, ' +
      cov.from_press + ' from UN meeting coverage) · New York, 22–28 Sep 2026 · updated ' + D.generated_at.slice(0, 10);

    var counts = topicCounts();
    var top = counts[0];
    var hostile = D.edges.filter(function (e) { return e.stance <= -0.5; }).length;
    var warm = D.edges.filter(function (e) { return e.stance >= 0.5; }).length;
    var stats = [
      { v: cov.summarised, l: 'addresses analysed', s: cov.indexed > cov.summarised ? (cov.indexed - cov.summarised) + ' still to summarise' : 'every address posted so far' },
      { v: Math.round(100 * top.n / N.length) + '%', l: top.label, s: 'the most shared concern' },
      { v: D.clusters.length, l: 'concern clusters', s: 'silhouette ' + D.silhouette },
      { v: warm + ' / ' + hostile, l: 'warm / hostile ties', s: 'said from the podium' },
    ];
    document.getElementById('un-stats').innerHTML = stats.map(function (s) {
      return '<div class="card un-stat"><div class="un-stat-v">' + esc(String(s.v)) + '</div>' +
        '<div class="un-stat-l">' + esc(s.l) + '</div><div class="un-stat-s">' + esc(s.s) + '</div></div>';
    }).join('');
  }

  // ── Topic prevalence ─────────────────────────────────────────────────
  function topicCounts() {
    return D.topics.map(function (t) {
      var n = N.filter(function (x) { return (x.concerns[t.key] || 0) >= 2; }).length;
      var lead = N.filter(function (x) { return x.primary_topic === t.key; }).length;
      return { key: t.key, label: t.label, n: n, lead: lead };
    }).filter(function (t) { return t.n > 0; })
      .sort(function (a, b) { return b.n - a.n || b.lead - a.lead; });
  }

  function renderTopics() {
    var rows = topicCounts();
    var max = rows.length ? rows[0].n : 1;
    var el = document.getElementById('un-topics');
    el.innerHTML = rows.map(function (t) {
      var pct = Math.round(100 * t.n / N.length);
      return '<button class="un-topic-row' + (filter.topic === t.key ? ' on' : '') + '" data-topic="' + t.key + '">' +
        '<span class="un-topic-label">' + esc(t.label) + '</span>' +
        '<span class="un-topic-track"><span class="un-topic-bar" style="width:' + (100 * t.n / max) + '%"></span></span>' +
        '<span class="un-topic-n">' + pct + '%<em>' + t.n + (t.lead ? ' · ' + t.lead + ' lead' : '') + '</em></span>' +
      '</button>';
    }).join('');
    el.querySelectorAll('.un-topic-row').forEach(function (b) {
      b.addEventListener('mousemove', function (ev) {
        var t = rows.filter(function (r) { return r.key === b.dataset.topic; })[0];
        showTip('<div class="un-tip-title">' + esc(t.label) + '</div>' +
          '<div class="un-tip-body">' + t.n + ' of ' + N.length + ' addresses made this a major theme; ' +
          t.lead + ' made it their primary concern.</div>', ev);
      });
      b.addEventListener('mouseleave', hideTip);
      b.addEventListener('click', function () {
        filter.topic = filter.topic === b.dataset.topic ? null : b.dataset.topic;
        renderTopics();
        renderFilter();
        renderGrid();
        if (filter.topic) document.getElementById('addresses').scrollIntoView({ behavior: 'smooth' });
      });
    });
  }

  // ── Concern map ──────────────────────────────────────────────────────
  var mapSel = null;

  function renderScatter() {
    var W = 640, H = 440, M = 26;
    var x = d3.scaleLinear().domain([-1.08, 1.08]).range([M, W - M]);
    var y = d3.scaleLinear().domain([-1.08, 1.08]).range([H - M, M]);
    // Many speeches share near-identical concern mixes; de-overlap with a
    // collide force pinned back toward each PCA position, run to completion.
    var pts = N.map(function (n) { return { n: n, x: x(n.xy[0]), y: y(n.xy[1]), tx: x(n.xy[0]), ty: y(n.xy[1]) }; });
    d3.forceSimulation(pts)
      .force('x', d3.forceX(function (p) { return p.tx; }).strength(0.35))
      .force('y', d3.forceY(function (p) { return p.ty; }).strength(0.35))
      .force('c', d3.forceCollide(7.5))
      .stop().tick(240);
    pts.forEach(function (p) {
      p.x = Math.max(10, Math.min(W - 10, p.x));
      p.y = Math.max(10, Math.min(H - 10, p.y));
    });

    var el = document.getElementById('un-scatter');
    el.innerHTML = '';
    var svg = d3.select(el).append('svg').attr('viewBox', '0 0 ' + W + ' ' + H)
      .attr('class', 'un-svg').attr('role', 'img')
      .attr('aria-label', 'Map of nations positioned by the concerns their speeches emphasised');

    // Recessive axes: just the two centre lines, captioned with what each
    // direction MEANS (the topics loading hardest on it — from the analysis).
    svg.append('line').attr('class', 'un-axis').attr('x1', x(0)).attr('x2', x(0)).attr('y1', M).attr('y2', H - M);
    svg.append('line').attr('class', 'un-axis').attr('y1', y(0)).attr('y2', y(0)).attr('x1', M).attr('x2', W - M);
    function axisText(keys) {
      return keys.map(function (k) { return topicLabel[k].split(/ & |:/)[0].toLowerCase(); }).join(' / ');
    }
    var ax = D.axes || [];
    if (ax[0]) {
      if (ax[0].plus.length) svg.append('text').attr('class', 'un-axis-label').attr('x', W - M).attr('y', y(0) - 6)
        .attr('text-anchor', 'end').text('more ' + axisText(ax[0].plus) + ' →');
      if (ax[0].minus.length) svg.append('text').attr('class', 'un-axis-label').attr('x', M).attr('y', y(0) + 14)
        .text('← more ' + axisText(ax[0].minus));
    }
    if (ax[1]) {
      if (ax[1].plus.length) svg.append('text').attr('class', 'un-axis-label').attr('x', x(0) + 6).attr('y', M + 4)
        .text('↑ more ' + axisText(ax[1].plus));
      if (ax[1].minus.length) svg.append('text').attr('class', 'un-axis-label').attr('x', x(0) + 6).attr('y', H - M + 2)
        .text('↓ more ' + axisText(ax[1].minus));
    }

    var g = svg.append('g');
    var marks = g.selectAll('g.un-mark').data(pts).enter().append('g')
      .attr('class', 'un-mark')
      .attr('transform', function (p) { return 'translate(' + p.x + ',' + p.y + ')'; });
    marks.append('circle').attr('r', 9).attr('class', 'un-hit');   // hit target > mark
    marks.append('path').attr('d', function (p) { return shapePath(p.n.cluster, 58); });
    marks.filter(function (p) { return MARQUEE.indexOf(p.n.iso2) !== -1; })
      .append('text').attr('class', 'un-mark-label').attr('x', 7).attr('y', 3.5)
      .text(function (p) { return p.n.iso2; });

    marks.on('mousemove', function (ev, p) { showTip(nationTip(p.n), ev); })
      .on('mouseleave', hideTip)
      .on('click', function (ev, p) { select(p.n.iso2, true); });

    svg.selectAll('.un-axis-label').raise();   // captions stay legible over the marks
    mapSel = marks;
    paintScatter();
  }

  function paintScatter() {
    if (!mapSel) return;
    var focusCluster = filter.cluster;
    mapSel.classed('sel', function (p) { return p.n.iso2 === selected; })
      .classed('dim', function (p) { return focusCluster != null && p.n.cluster !== focusCluster; })
      .classed('in', function (p) { return focusCluster != null && p.n.cluster === focusCluster; });
    mapSel.filter(function (p) { return p.n.iso2 === selected; }).raise();
  }

  function renderClusters() {
    var el = document.getElementById('un-clusters');
    el.innerHTML = '<div class="un-cluster-head">Clusters · click to focus</div>' + D.clusters.map(function (c) {
      var members = c.members.map(function (iso) { return byIso[iso]; }).filter(Boolean);
      return '<button class="un-cluster' + (filter.cluster === c.id ? ' on' : '') + '" data-cluster="' + c.id + '">' +
        '<div class="un-cluster-top">' + shapeSvg(c.id) +
          '<span class="un-cluster-name">' + (c.id + 1) + '. ' + esc(c.label) + '</span>' +
          '<span class="un-cluster-n">' + members.length + '</span></div>' +
        '<div class="un-cluster-topics">' + c.top_topics.map(function (t) {
          return '<span>' + esc(topicLabel[t.key]) + '</span>';
        }).join('') + '</div>' +
        '<div class="un-cluster-flags" title="' + esc(members.map(function (m) { return m.country; }).join(', ')) + '">' +
          members.map(function (m) { return flag(m.iso2); }).join(' ') + '</div>' +
      '</button>';
    }).join('');
    el.querySelectorAll('.un-cluster').forEach(function (b) {
      b.addEventListener('click', function () {
        var id = +b.dataset.cluster;
        filter.cluster = filter.cluster === id ? null : id;
        renderClusters();
        paintScatter();
        renderFilter();
        renderGrid();
      });
    });
  }

  // ── Friendliness network ─────────────────────────────────────────────
  var net = null;   // { nodes, links, svg selections }

  function inferredLinks() {
    // The strongest inferred ties that nobody actually voiced — capped so the
    // graph stays readable. Only pairs whose score has an alignment component.
    var out = [], n = N.length;
    var direct = {};
    D.edges.forEach(function (e) { direct[e.a + e.b] = direct[e.b + e.a] = 1; });
    for (var i = 0; i < n; i++) {
      for (var j = i + 1; j < n; j++) {
        var k = fIndex(i, j);
        var s = D.friendliness.tri[k];
        if (D.friendliness.basis[k].indexOf('a') === -1) continue;
        if (direct[N[i].iso2 + N[j].iso2]) continue;
        if (Math.abs(s) >= 0.6) out.push({ a: N[i].iso2, b: N[j].iso2, stance: s * 2, inferred: true, score: s });
      }
    }
    out.sort(function (a, b) { return Math.abs(b.score) - Math.abs(a.score); });
    return out.slice(0, 120);
  }

  function renderNetwork() {
    var W = 640, H = 480;
    var links = D.edges.map(function (e) { return { a: e.a, b: e.b, stance: e.stance, said: e.said }; });
    if (showInferred) links = links.concat(inferredLinks());
    var used = {};   // iso → degree
    links.forEach(function (l) {
      used[l.a] = (used[l.a] || 0) + 1;
      used[l.b] = (used[l.b] || 0) + 1;
    });
    if (selected && !(selected in used)) used[selected] = 0;
    var nodes = Object.keys(used).map(function (iso) { return { id: iso, n: byIso[iso], deg: used[iso] }; });

    var el = document.getElementById('un-network');
    el.innerHTML = '';
    if (!links.length) {
      el.innerHTML = '<div class="empty-note">No nation has named another yet in the addresses summarised so far.</div>';
      return;
    }

    var sim = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links.map(function (l) { return { source: l.a, target: l.b, stance: l.stance }; }))
        .id(function (d) { return d.id; })
        .distance(function (l) { return l.stance >= 0.5 ? 55 : l.stance <= -0.5 ? 150 : 100; })
        .strength(function (l) { return l.stance >= 0.5 ? 0.5 : 0.15; }))
      .force('charge', d3.forceManyBody().strength(-90))
      .force('x', d3.forceX(W / 2).strength(0.06))
      .force('y', d3.forceY(H / 2).strength(0.08))
      .force('collide', d3.forceCollide(12))
      .stop();
    sim.tick(400);
    nodes.forEach(function (d) {
      d.x = Math.max(16, Math.min(W - 16, d.x));
      d.y = Math.max(16, Math.min(H - 16, d.y));
    });
    var pos = {};
    nodes.forEach(function (d) { pos[d.id] = d; });

    var svg = d3.select(el).append('svg').attr('viewBox', '0 0 ' + W + ' ' + H).attr('class', 'un-svg')
      .attr('role', 'img').attr('aria-label', 'Network of what nations said about each other');
    var lsel = svg.append('g').selectAll('line').data(links).enter().append('line')
      .attr('class', function (l) { return 'un-link ' + stanceClass(l.stance) + (l.inferred ? ' inferred' : ''); })
      .attr('x1', function (l) { return pos[l.a].x; }).attr('y1', function (l) { return pos[l.a].y; })
      .attr('x2', function (l) { return pos[l.b].x; }).attr('y2', function (l) { return pos[l.b].y; })
      .attr('stroke-width', function (l) { return l.inferred ? 1 : 1 + Math.abs(l.stance); });
    // Invisible fat twin per link for hover.
    svg.append('g').selectAll('line').data(links).enter().append('line')
      .attr('class', 'un-link-hit')
      .attr('x1', function (l) { return pos[l.a].x; }).attr('y1', function (l) { return pos[l.a].y; })
      .attr('x2', function (l) { return pos[l.b].x; }).attr('y2', function (l) { return pos[l.b].y; })
      .on('mousemove', function (ev, l) { showTip(linkTip(l), ev); })
      .on('mouseleave', hideTip);

    var nsel = svg.append('g').selectAll('g').data(nodes).enter().append('g')
      .attr('class', 'un-node')
      .attr('transform', function (d) { return 'translate(' + d.x + ',' + d.y + ')'; });
    nsel.append('circle').attr('r', function (d) { return 4 + Math.min(8, Math.sqrt(d.deg) * 2); });
    nsel.append('text').attr('class', 'un-node-label').attr('dy', function (d) { return -(7 + Math.min(8, Math.sqrt(d.deg) * 2)); })
      .attr('text-anchor', 'middle').text(function (d) { return d.id; });
    nsel.on('mousemove', function (ev, d) {
      if (d.n) showTip(nationTip(d.n), ev);
    }).on('mouseleave', hideTip)
      .on('click', function (ev, d) { if (d.n) select(d.id, false); });

    net = { links: lsel, nodes: nsel, data: links };
    paintNetwork();
  }

  function linkTip(l) {
    var A = byIso[l.a], B = byIso[l.b];
    var head = '<div class="un-tip-title">' + flag(l.a) + ' ' + esc(A ? A.country : l.a) + ' ↔ ' +
      flag(l.b) + ' ' + esc(B ? B.country : l.b) + '</div>';
    if (l.inferred) {
      return head + '<div class="un-tip-body">Inferred ' + (l.score > 0 ? 'alignment' : 'opposition') +
        ' (' + l.score.toFixed(2) + '): neither named the other, but their stated positions ' +
        (l.score > 0 ? 'match' : 'clash') + '.</div>';
    }
    return head + (l.said || []).map(function (s) {
      return '<div class="un-tip-said ' + stanceClass(s.stance) + '"><b>' + esc(s.from) + ' → ' + esc(s.to) + '</b> ' +
        esc(stanceWord(s.stance)) + (s.src === 'reply' ? ' (right of reply)' : '') +
        (s.note ? ': ' + esc(s.note) : '') + '</div>';
    }).join('');
  }

  function paintNetwork() {
    if (!net) return;
    var nb = {};
    if (selected) net.data.forEach(function (l) {
      if (l.a === selected) nb[l.b] = 1;
      if (l.b === selected) nb[l.a] = 1;
    });
    net.nodes.classed('sel', function (d) { return d.id === selected; })
      .classed('nb', function (d) { return !!nb[d.id]; })
      .classed('dim', function (d) { return !!selected && d.id !== selected && !nb[d.id]; })
      .classed('marquee', function (d) { return MARQUEE.indexOf(d.id) !== -1 || d.deg >= 4; });
    net.links.classed('dim', function (l) { return !!selected && l.a !== selected && l.b !== selected; });
  }

  // ── Nation detail ────────────────────────────────────────────────────
  function renderDetail() {
    var el = document.getElementById('un-detail');
    var opts = N.slice().sort(function (a, b) { return a.country.localeCompare(b.country); }).map(function (n) {
      return '<option value="' + n.iso2 + '"' + (n.iso2 === selected ? ' selected' : '') + '>' +
        flag(n.iso2) + ' ' + esc(n.country) + '</option>';
    }).join('');
    var picker = '<select class="un-picker" id="un-picker" aria-label="Choose a nation">' +
      '<option value="">Choose a nation…</option>' + opts + '</select>';

    var n = byIso[selected];
    if (!n) {
      el.innerHTML = picker + '<div class="un-detail-empty">Pick a nation, or click one on the map or network, to see its speech, its concerns, and who it is closest to and furthest from.</div>';
      wirePicker();
      return;
    }

    var concerns = Object.keys(n.concerns).sort(function (a, b) { return n.concerns[b] - n.concerns[a]; });
    var bars = concerns.map(function (k) {
      return '<div class="un-cbar"><span>' + esc(topicLabel[k]) + '</span>' +
        '<span class="un-cbar-track"><span style="width:' + (100 * n.concerns[k] / 3) + '%"></span></span></div>';
    }).join('');

    var pos = D.positions.filter(function (p) { return p.key in n.positions; }).map(function (p) {
      var v = n.positions[p.key];
      return '<div class="un-pos"><span class="un-pos-k">' + esc(p.label) + '</span>' +
        '<span class="un-pos-track" title="' + esc(p.minus + ' ← → ' + p.plus) + '">' +
          '<span class="un-pos-mid"></span><span class="un-pos-dot" style="left:' + (50 + 50 * v) + '%"></span></span>' +
        '<span class="un-pos-v">' + esc(posWord(v, p)) + '</span></div>';
    }).join('');

    var said = n.mentions.slice().sort(function (a, b) { return a.stance - b.stance; }).map(function (m) {
      return '<li class="' + stanceClass(m.stance) + '"><span class="un-said-who">' + flag(m.iso2) + ' ' +
        esc(byIso[m.iso2] ? byIso[m.iso2].country : m.iso2) + '</span> <span class="un-said-stance">' +
        esc(stanceWord(m.stance)) + '</span>' + (m.note ? '<span class="un-said-note">' + esc(m.note) + '</span>' : '') + '</li>';
    }).join('');
    // What others said about THIS nation.
    var about = [];
    D.edges.forEach(function (e) {
      (e.said || []).forEach(function (s) { if (s.to === n.iso2) about.push(s); });
    });
    var aboutHtml = about.sort(function (a, b) { return a.stance - b.stance; }).map(function (s) {
      return '<li class="' + stanceClass(s.stance) + '"><span class="un-said-who">' + flag(s.from) + ' ' +
        esc(byIso[s.from] ? byIso[s.from].country : s.from) + '</span> <span class="un-said-stance">' +
        esc(stanceWord(s.stance)) + (s.src === 'reply' ? ', right of reply' : '') + '</span>' +
        (s.note ? '<span class="un-said-note">' + esc(s.note) + '</span>' : '') + '</li>';
    }).join('');

    var ranked = N.filter(function (m) { return m.iso2 !== n.iso2; }).map(function (m) {
      var f = friend(n.iso2, m.iso2);
      return { n: m, score: f.score, basis: f.basis };
    }).sort(function (a, b) { return b.score - a.score; });
    function rankList(list) {
      return list.map(function (r) {
        var tag = r.basis.indexOf('d') !== -1 ? 'said so' : r.basis.indexOf('a') !== -1 ? 'positions' : 'concerns only';
        return '<li data-iso="' + r.n.iso2 + '"><span>' + flag(r.n.iso2) + ' ' + esc(r.n.country) + '</span>' +
          '<span class="un-rank-score ' + stanceClass(r.score * 2) + '">' + (r.score > 0 ? '+' : '') + r.score.toFixed(2) + '</span>' +
          '<span class="un-rank-basis">' + tag + '</span></li>';
      }).join('');
    }

    el.innerHTML = picker +
      '<div class="un-detail-title">' + flag(n.iso2) + ' ' + esc(n.country) + '</div>' +
      '<div class="un-detail-sub">' + esc(n.speaker) + ' · ' + esc(n.role) +
        (n.published ? ' · ' + esc(n.published) : '') + ' · ' + sourceHtml(n) + ' · <a href="' + esc(n.url) + '" target="_blank" rel="noopener">watch ▸</a></div>' +
      '<div class="un-detail-concern"><span class="un-kicker">Primary concern</span>' + esc(n.primary_concern) + '</div>' +
      '<p class="un-detail-summary">' + esc(n.summary) + '</p>' +
      '<div class="un-kicker">Concern mix · cluster ' + shapeSvg(n.cluster, 11) + ' ' + (n.cluster + 1) + '</div>' + bars +
      (pos ? '<div class="un-kicker">Positions</div>' + pos : '') +
      (said ? '<div class="un-kicker">Said about others</div><ul class="un-said">' + said + '</ul>' : '') +
      (aboutHtml ? '<div class="un-kicker">What others said about ' + esc(n.country) + '</div><ul class="un-said">' + aboutHtml + '</ul>' : '') +
      '<div class="un-rank-cols">' +
        '<div><div class="un-kicker">Closest</div><ul class="un-rank">' + rankList(ranked.slice(0, 6)) + '</ul></div>' +
        '<div><div class="un-kicker">Furthest</div><ul class="un-rank">' + rankList(ranked.slice(-6).reverse()) + '</ul></div>' +
      '</div>';
    wirePicker();
    el.querySelectorAll('.un-rank li').forEach(function (li) {
      li.addEventListener('click', function () { select(li.dataset.iso, false); });
    });
  }

  function wirePicker() {
    var p = document.getElementById('un-picker');
    if (p) p.addEventListener('change', function () { select(p.value || null, false); });
  }

  // ── Rights of reply ──────────────────────────────────────────────────
  function renderReplies() {
    if (!D.replies.length) return;
    document.getElementById('replies-label').hidden = false;
    document.getElementById('un-replies').innerHTML = D.replies.map(function (r) {
      return '<div class="card card-pad un-reply">' +
        '<div class="un-reply-title">' + esc(r.title) + ' <span class="un-card-links">' + sourceHtml(r) +
          '<a href="' + esc(r.url) + '" target="_blank" rel="noopener">watch ▸</a></span></div>' +
        '<p>' + esc(r.summary) + '</p>' +
        '<ul class="un-said">' + r.pairs.map(function (p) {
          return '<li class="' + stanceClass(p.stance) + '"><span class="un-said-who">' + flag(p.from) + ' ' + esc(p.from) +
            ' → ' + flag(p.to) + ' ' + esc(p.to) + '</span>' + (p.note ? '<span class="un-said-note">' + esc(p.note) + '</span>' : '') + '</li>';
        }).join('') + '</ul></div>';
    }).join('');
  }

  // ── Address cards ────────────────────────────────────────────────────
  function renderFilter() {
    var bits = [];
    if (filter.topic) bits.push('<button class="filter-pill" data-clear="topic">' + esc(topicLabel[filter.topic]) + ' ✕</button>');
    if (filter.cluster != null) bits.push('<button class="filter-pill" data-clear="cluster">Cluster ' + (filter.cluster + 1) + ' ✕</button>');
    var el = document.getElementById('un-filter');
    el.innerHTML = bits.length ? '<span class="un-filter-label">Filtered by</span>' + bits.join('') : '';
    el.querySelectorAll('[data-clear]').forEach(function (b) {
      b.addEventListener('click', function () {
        filter[b.dataset.clear] = null;
        renderTopics();
        renderClusters();
        paintScatter();
        renderFilter();
        renderGrid();
      });
    });
  }

  function matches(n) {
    if (filter.topic && (n.concerns[filter.topic] || 0) < 2) return false;
    if (filter.cluster != null && n.cluster !== filter.cluster) return false;
    if (filter.q) {
      var hay = (n.country + ' ' + n.speaker + ' ' + n.primary_concern + ' ' + n.summary).toLowerCase();
      if (hay.indexOf(filter.q) === -1) return false;
    }
    return true;
  }

  function renderGrid() {
    var list = N.filter(matches);
    var el = document.getElementById('un-grid');
    if (!list.length) { el.innerHTML = '<div class="empty-note">No addresses match.</div>'; return; }
    el.innerHTML = list.map(function (n) {
      var tags = Object.keys(n.concerns).filter(function (k) { return n.concerns[k] >= 2; })
        .sort(function (a, b) { return n.concerns[b] - n.concerns[a]; }).slice(0, 4);
      return '<article class="card un-card' + (n.iso2 === selected ? ' sel' : '') + '" data-iso="' + n.iso2 + '">' +
        '<div class="un-card-top"><span class="un-card-flag">' + flag(n.iso2) + '</span>' +
          '<div><div class="un-card-country">' + esc(n.country) + '</div>' +
          '<div class="un-card-speaker">' + esc(n.speaker) + ' · ' + esc(n.role) + '</div></div>' +
          '<span class="un-card-cluster" title="Cluster ' + (n.cluster + 1) + ': ' + esc(D.clusters[n.cluster].label) + '">' + shapeSvg(n.cluster, 12) + '</span></div>' +
        '<div class="un-card-concern">' + esc(n.primary_concern) + '</div>' +
        '<p class="un-card-summary">' + esc(n.summary) + '</p>' +
        '<div class="un-card-foot">' + tags.map(function (k) { return '<span class="pill">' + esc(topicLabel[k]) + '</span>'; }).join('') +
          '<span class="un-card-links">' + sourceHtml(n) + '<a class="un-card-watch" href="' + esc(n.url) + '" target="_blank" rel="noopener">watch ▸</a></span></div>' +
      '</article>';
    }).join('');
  }

  // ── Method ───────────────────────────────────────────────────────────
  function renderMethod() {
    var w = D.weights;
    document.getElementById('un-method').innerHTML =
      '<p><b>Sources.</b> Every address is indexed from the official United Nations YouTube channel, whose uploads carry the English interpretation track (<code>scripts/pull_un_speeches.py</code>). ' + D.coverage.from_transcript + ' speeches were summarised from their full transcripts. YouTube then rate-limited transcript downloads, so the other ' + D.coverage.from_press + ' were summarised from the UN’s own per-speaker meeting coverage (press.un.org, 250–400 words per speaker), and each card says which. A transcript-based summary replaces a coverage-based one as transcripts come in.</p>' +
      '<p><b>Summaries &amp; concerns.</b> Each transcript is read in full and given a short summary, a primary concern, weights (1–3) on ' + D.topics.length + ' shared topics, every explicit statement about another nation (−2 hostile … +2 strong support), and a stance on five contested questions where the speech takes one. These are editorial judgements from the text, not keyword counts.</p>' +
      '<p><b>Clusters.</b> k-means on the normalised concern weights (cosine), with k picked by silhouette score (' + D.silhouette + ' here, where 0.25–0.5 means real but overlapping groups). The map is a 2-D projection (PCA) of the same weights.</p>' +
      '<p><b>Friendliness</b> (−1 … +1) blends whichever signals a pair has: <b>' + Math.round(w.direct * 100) + '%</b> what they said about each other (a right of reply counts as hostile), <b>' + Math.round(w.align * 100) + '%</b> agreement on the five contested positions (only when both took at least two), and <b>' + Math.round(w.concern * 100) + '%</b> how similar their concerns are. Rankings are tagged <em>said so</em>, <em>positions</em> or <em>concerns only</em> so a stated tie is never confused with an inferred one.</p>' +
      '<p class="un-method-note">One speech is one data point. It shows what a government chose to say in New York, not the full state of a relationship.</p>';
  }

  // ── Selection ────────────────────────────────────────────────────────
  function select(iso, scrollToDetail) {
    selected = iso || null;
    paintScatter();
    renderNetwork();
    renderDetail();
    document.querySelectorAll('.un-card').forEach(function (c) { c.classList.toggle('sel', c.dataset.iso === selected); });
    try { history.replaceState(null, '', updateParam('nation', selected)); } catch (e) {}
    if (scrollToDetail && selected) document.getElementById('friendliness').scrollIntoView({ behavior: 'smooth' });
  }

  function updateParam(k, v) {
    var p = new URLSearchParams(location.search);
    if (v) p.set(k, v); else p.delete(k);
    var qs = p.toString();
    return location.pathname + (qs ? '?' + qs : '') + location.hash;
  }

  // ── Boot ─────────────────────────────────────────────────────────────
  var session = (param('session') || '81').replace(/\D/g, '');
  fetch('data/un_speeches/unga' + session + '.json', { cache: 'no-cache' })
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function (data) {
      D = data;
      N = data.nations;
      N.forEach(function (n) { byIso[n.iso2] = n; });
      data.topics.forEach(function (t) { topicLabel[t.key] = t.label; });
      var want = param('nation');
      if (want && byIso[want]) selected = want;

      renderHeader();
      renderTopics();
      renderScatter();
      renderClusters();
      renderNetwork();
      renderDetail();
      renderReplies();
      renderFilter();
      renderGrid();
      renderMethod();

      document.getElementById('un-inferred').addEventListener('change', function (e) {
        showInferred = e.target.checked;
        renderNetwork();
      });
      var search = document.getElementById('un-search');
      search.addEventListener('input', function () {
        filter.q = search.value.trim().toLowerCase();
        renderGrid();
      });
      document.getElementById('un-grid').addEventListener('click', function (e) {
        if (e.target.closest('a')) return;
        var card = e.target.closest('.un-card');
        if (card) select(card.dataset.iso, true);
      });
    })
    .catch(function (err) {
      document.getElementById('un-sub').textContent = 'Failed to load speech data: ' + err.message;
    });
})();
