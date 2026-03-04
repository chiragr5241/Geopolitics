'use strict';

/* =========================================================
   GLOBAL OPERATIONS MAP 2025–2026 — Application Logic
   Depends on: Leaflet (L), config.js globals
   Loads incident data from operationsdata.csv at startup.
   ========================================================= */

(function () {

  // ── CSV Parser ──

  function parseCSV(text) {
    var lines = [];
    var current = '';
    var inQuotes = false;

    for (var i = 0; i < text.length; i++) {
      var ch = text[i];
      if (ch === '"') {
        if (inQuotes && i + 1 < text.length && text[i + 1] === '"') {
          current += '"';
          i++;
        } else {
          inQuotes = !inQuotes;
        }
      } else if ((ch === '\n' || ch === '\r') && !inQuotes) {
        if (ch === '\r' && i + 1 < text.length && text[i + 1] === '\n') i++;
        if (current.length > 0) lines.push(current);
        current = '';
      } else {
        current += ch;
      }
    }
    if (current.length > 0) lines.push(current);

    if (lines.length < 2) return [];

    var headers = splitCSVRow(lines[0]);
    var rows = [];
    for (var j = 1; j < lines.length; j++) {
      var values = splitCSVRow(lines[j]);
      if (!values[0]) continue;
      var obj = {};
      for (var k = 0; k < headers.length; k++) {
        obj[headers[k]] = (k < values.length) ? values[k] : '';
      }
      rows.push(obj);
    }
    return rows;
  }

  function splitCSVRow(line) {
    var fields = [];
    var current = '';
    var inQuotes = false;

    for (var i = 0; i < line.length; i++) {
      var ch = line[i];
      if (ch === '"') {
        if (inQuotes && i + 1 < line.length && line[i + 1] === '"') {
          current += '"';
          i++;
        } else {
          inQuotes = !inQuotes;
        }
      } else if (ch === ',' && !inQuotes) {
        fields.push(current);
        current = '';
      } else {
        current += ch;
      }
    }
    fields.push(current);
    return fields;
  }

  // ── Data Transformation ──

  function buildIntel(r) {
    var intel = [];
    function add(k, v, opts) {
      if (!v || v === '0' || v === 'N/A' || v === 'Unknown — disputed') return;
      intel.push({ k: k, v: v, hi: !!(opts && opts.hi), cls: (opts && opts.cls) || '' });
    }
    add('Platform', r.platform_or_unit, { hi: true });
    if (r.munitions_weapons && r.munitions_weapons !== 'N/A') {
      var mun = r.munitions_weapons;
      if (r.munitions_quantity && r.munitions_quantity !== '0' && r.munitions_quantity !== 'Classified')
        mun += ' (' + r.munitions_quantity + ')';
      intel.push({ k: 'Munitions', v: mun, hi: true, cls: '' });
    }
    add('Range', r.range_km ? r.range_km + ' km' : '', { hi: true });
    add('Target Type', r.target_type);
    add('Target Depth', r.target_depth_hardening, { cls: 'gold' });
    add('Personnel', r.personnel_deployed, { hi: true });
    add('Aircraft', r.aircraft_deployed, { hi: true });
    add('Naval Vessels', r.naval_vessels);
    if (r.military_kia_enemy && r.military_kia_enemy !== '0' && r.military_kia_enemy !== 'Unknown')
      intel.push({ k: 'Enemy KIA', v: r.military_kia_enemy, hi: false, cls: 'danger' });
    if (r.military_kia_friendly && r.military_kia_friendly !== '0')
      intel.push({ k: 'Friendly KIA', v: r.military_kia_friendly, hi: false, cls: 'danger' });
    if (r.civilian_kia && r.civilian_kia !== '0' && r.civilian_kia !== '0 (all intercepted)')
      intel.push({ k: 'Civilian KIA', v: r.civilian_kia, hi: false, cls: 'danger' });
    if (r.military_wia_friendly && r.military_wia_friendly !== '0')
      intel.push({ k: 'Friendly WIA', v: r.military_wia_friendly, hi: false, cls: 'danger' });
    add('Result', r.result_outcome, { hi: true });
    add('Nuclear Setback', r.nuclear_setback_assessment, { cls: 'gold' });
    add('Economic Impact', r.economic_impact, { cls: 'orange' });
    if (r.intercepted_munitions)
      intel.push({ k: 'Intercepted', v: r.intercepted_munitions, hi: false, cls: 'green' });
    add('Intel Notes', r.key_intelligence_notes, { cls: 'gold' });
    return intel;
  }

  function buildSources(r) {
    var sources = [];
    function addGroup(field, prefix) {
      if (!field) return;
      field.split(';').forEach(function (s) {
        s = s.trim();
        if (!s) return;
        var parts = s.split('|');
        var name = parts[0].trim();
        var url  = parts[1] ? parts[1].trim() : null;
        sources.push({ n: name, u: url, t: prefix });
      });
    }
    addGroup(r.osint_sources, 'OSINT');
    addGroup(r.press_sources, 'Press');
    addGroup(r.think_tank_sources, 'Think Tank');
    return sources;
  }

  function buildBadges(r) {
    var tags = (r.tags || '').split(';').map(function (s) { return s.trim(); }).filter(Boolean);
    var colors = (r.badge_colors || '').split(';').map(function (s) { return s.trim(); });
    return tags.map(function (t, i) { return [t, colors[i] || 'blue']; });
  }

  function csvRowToIncident(r) {
    return {
      id:        r.incident_id,
      op:        r.operation_name,
      opColor:   r.operation_color,
      type:      r.strike_type,
      timeVal:   parseInt(r.date_sort_value, 10) || 0,
      title:     r.incident_title,
      date:      r.date,
      confirmed: r.confirmed === 'TRUE',
      from: {
        lat:   parseFloat(r.origin_lat),
        lng:   parseFloat(r.origin_lng),
        label: r.origin_label,
        sub:   r.origin_sublabel,
      },
      to: {
        lat:   parseFloat(r.target_lat),
        lng:   parseFloat(r.target_lng),
        label: r.target_label,
        sub:   r.target_sublabel,
      },
      summary:  r.summary,
      assess:   r.assessment,
      intel:    buildIntel(r),
      sources:  buildSources(r),
      badges:   buildBadges(r),
      imagery:  IMAGERY[r.incident_id] || [],
    };
  }

  function deriveOps(incidents) {
    var ops = {};
    incidents.forEach(function (inc) {
      if (ops[inc.op]) return;
      var meta = OPS_META[inc.op] || {};
      ops[inc.op] = {
        name:      inc.op,
        color:     inc.opColor,
        countries: meta.countries || [],
        period:    meta.period || '',
        dashed:    !!meta.dashed,
      };
    });
    return ops;
  }

  // ── Boot ──

  function boot(csvText) {
    var rows = parseCSV(csvText);
    var INCIDENTS = rows.map(csvRowToIncident);
    var OPS = deriveOps(INCIDENTS);

    initApp(INCIDENTS, OPS);
  }

  // ── Application ──

  function initApp(INCIDENTS, OPS) {

    // Map
    var map = L.map('map', {
      center: [25, 75], zoom: 3,
      minZoom: 2,
      maxBounds: [[-85, -180], [85, 180]],
      maxBoundsViscosity: 1.0,
      zoomControl: false, attributionControl: false, preferCanvas: true,
    });
    L.control.zoom({ position: 'bottomleft' }).addTo(map);

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      subdomains: 'abcd', maxZoom: 19, minZoom: 2, noWrap: true,
    }).addTo(map);

    // ── World borders + country highlights ──
    var worldBorderLayer = null;

    function getActiveCountryCodes() {
      var codes = new Set();
      INCIDENTS.filter(isVisible).forEach(function (inc) {
        var op = OPS[inc.op] || {};
        (op.countries || []).forEach(function (c) { codes.add(c); });
      });
      return codes;
    }

    function countryFeatureStyle(feature, activeCodes) {
      var code = ISO_NUM_MAP[feature.id];
      if (code && activeCodes && activeCodes.has(code)) {
        var cn = COUNTRIES[code];
        return { color: cn.color, weight: 1.5, opacity: 0.7, fillColor: cn.color, fillOpacity: 0.12 };
      }
      return { color: '#2a4060', weight: 0.4, opacity: 0.25, fillColor: 'transparent', fillOpacity: 0 };
    }

    // Fix antimeridian rendering artefacts in world-atlas data.
    // world-atlas arcs 161/162 jump 358° within a single ring (178.6°→−180°→179.99°).
    // Leaflet draws a straight screen-space line for each such segment, smearing a
    // line across the full map width. Strategy:
    //   1. Flatten MultiPolygons → separate Polygon features (eliminates cross-ring
    //      canvas-fill artefacts that arise when the two Russia sub-paths have
    //      opposite winding on the shared canvas path).
    //   2. Normalise each ring so consecutive longitude values never jump >180°
    //      (converts −180.0 after 178.6 → 180.0, keeping the ring continuous).
    function processWorldGeoJSON(geojson) {
      var result = [];
      geojson.features.forEach(function (f) {
        var g = f.geometry;
        if (!g) { result.push(f); return; }
        var polys = g.type === 'MultiPolygon' ? g.coordinates
                  : g.type === 'Polygon'      ? [g.coordinates]
                  : null;
        if (!polys) { result.push(f); return; }
        polys.forEach(function (polyCoords) {
          result.push({
            type: 'Feature', id: f.id, properties: f.properties,
            geometry: {
              type: 'Polygon',
              coordinates: polyCoords.map(function (ring) {
                var out = [[ring[0][0], ring[0][1]]];
                for (var i = 1; i < ring.length; i++) {
                  var prev = out[out.length - 1][0];
                  var lng = ring[i][0], lat = ring[i][1];
                  while (lng - prev >  180) lng -= 360;
                  while (prev - lng >  180) lng += 360;
                  out.push([lng, lat]);
                }
                return out;
              }),
            },
          });
        });
      });
      return { type: 'FeatureCollection', features: result };
    }

    fetch('https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json')
      .then(function (r) { return r.json(); })
      .then(function (world) {
        var geojson = processWorldGeoJSON(topojson.feature(world, world.objects.countries));
        var activeCodes = getActiveCountryCodes();
        worldBorderLayer = L.geoJSON(geojson, {
          style: function (f) { return countryFeatureStyle(f, activeCodes); },
          interactive: false,
        }).addTo(map);
        worldBorderLayer.bringToBack();
      })
      .catch(function () { /* borders optional — silently skip on error */ });

    function refreshBorders() {
      if (!worldBorderLayer) return;
      var activeCodes = getActiveCountryCodes();
      worldBorderLayer.setStyle(function (f) { return countryFeatureStyle(f, activeCodes); });
    }

    CITIES.forEach(function (c) {
      var icon = L.divIcon({
        html: '<div class="city-marker"><div class="city-dot"></div><div class="city-name">' + c.name + '</div></div>',
        iconSize: [90, 16], iconAnchor: [4, 8], className: '',
      });
      L.marker([c.lat, c.lng], { icon: icon, interactive: false, zIndexOffset: -100 }).addTo(map);
    });

    // State
    var activeOps       = new Set(Object.keys(OPS));
    var activeCountries = new Set(Object.keys(COUNTRIES));
    var selectedId  = null;
    var timeVal     = 100;
    var playTimer   = null;
    var allLayers   = {};

    // DOM refs
    var $incList        = document.getElementById('inc-list');
    var $incCount       = document.getElementById('inc-count');
    var $countryFilter  = document.getElementById('country-filter');
    var $opFilter       = document.getElementById('op-filter');
    var $opLegendItems  = document.getElementById('op-legend-items');
    var $tlMarks        = document.getElementById('tl-marks');
    var $tlDate         = document.getElementById('tl-date');
    var $tlSlider       = document.getElementById('tl-slider');
    var $btnShowAll     = document.getElementById('btn-show-all');
    var $btnPlay        = document.getElementById('btn-play');
    var $btnPause       = document.getElementById('btn-pause');
    var $btnReset       = document.getElementById('btn-reset');
    var $btnOpsAll      = document.getElementById('btn-ops-all');
    var $btnOpsNone     = document.getElementById('btn-ops-none');
    var $detPlaceholder = document.getElementById('det-placeholder');
    var $detContent     = document.getElementById('det-content');
    var $detScroll      = document.getElementById('detail-scroll');
    var $hOps           = document.getElementById('h-ops');

    $hOps.textContent = Object.keys(OPS).length + ' OPS';

    // Icon builders
    function buildMapIcon(inc, isSelected, isDimmed) {
      var st = STRIKE_TYPES[inc.type] || STRIKE_TYPES.missile;
      var sz = isSelected ? 36 : 28;
      var mainOp  = isDimmed ? 0.1 : 1;
      var pulseOp = isDimmed ? 0 : (isSelected ? 0.5 : 0.3);
      var c  = st.color, bg = st.bgFill;
      return '<div style="position:relative;width:' + sz + 'px;height:' + sz + 'px;cursor:pointer;">'
        + '<svg style="position:absolute;inset:0;overflow:visible;" width="' + sz + '" height="' + sz + '"><circle cx="' + sz/2 + '" cy="' + sz/2 + '" r="' + (sz/2-1) + '" fill="none" stroke="' + c + '" stroke-width="1.5" opacity="' + pulseOp + '" style="animation:ring-pulse 2.2s ease-out infinite;transform-origin:' + sz/2 + 'px ' + sz/2 + 'px;"/></svg>'
        + '<svg style="position:absolute;inset:0;" width="' + sz + '" height="' + sz + '" opacity="' + mainOp + '"><circle cx="' + sz/2 + '" cy="' + sz/2 + '" r="' + (sz/2-1) + '" fill="' + bg + '" fill-opacity="0.92" stroke="' + c + '" stroke-width="' + (isSelected?2.5:1.8) + '"/>' + st.getSVG(sz,c) + (isSelected?'<circle cx="'+sz/2+'" cy="'+sz/2+'" r="'+(sz/2-1)+'" fill="none" stroke="white" stroke-width="0.8" opacity="0.35"/>':'') + '</svg></div>';
    }

    function buildListIcon(type, sz) {
      sz = sz || 16;
      var st = STRIKE_TYPES[type] || STRIKE_TYPES.missile;
      return '<svg width="' + sz + '" height="' + sz + '" viewBox="0 0 ' + sz + ' ' + sz + '"><circle cx="' + sz/2 + '" cy="' + sz/2 + '" r="' + (sz/2-1) + '" fill="' + st.bgFill + '" fill-opacity="0.9" stroke="' + st.color + '" stroke-width="1.5"/>' + st.getSVG(sz, st.color) + '</svg>';
    }

    // Arrow rendering
    function makeArrow(inc) {
      // Skip rendering if coordinates are invalid
      if (isNaN(inc.from.lat) || isNaN(inc.from.lng) || isNaN(inc.to.lat) || isNaN(inc.to.lng)) {
        return null;
      }

      var op = OPS[inc.op] || {};
      var opColor = op.color || '#fff';
      var isDash = !!op.dashed;
      var st = STRIKE_TYPES[inc.type] || STRIKE_TYPES.missile;
      var isSelected = inc.id === selectedId;
      var isDimmed = selectedId && !isSelected;

      var f = [inc.from.lat, inc.from.lng], t = [inc.to.lat, inc.to.lng];
      var latMid = (f[0]+t[0])/2, lngMid = (f[1]+t[1])/2;
      var dx = t[1]-f[1], dy = t[0]-f[0];
      var len = Math.sqrt(dx*dx+dy*dy)||1;
      var off = Math.min(len*0.32,7);
      var nx = -dy/len*off, ny = dx/len*off;
      var pts = [];
      for (var i = 0; i <= 40; i++) {
        var tt = i/40;
        pts.push([(1-tt)*(1-tt)*f[0]+2*(1-tt)*tt*(latMid+nx)+tt*tt*t[0], (1-tt)*(1-tt)*f[1]+2*(1-tt)*tt*(lngMid+ny)+tt*tt*t[1]]);
      }

      var line = L.polyline(pts, { color: opColor, weight: isSelected?2.5:1.6, opacity: isSelected?1:(isDimmed?0.08:0.7), dashArray: isDash?'7,5':null });

      var e1 = pts[pts.length-1], e2 = pts[pts.length-4];
      var angle = Math.atan2(e1[0]-e2[0],e1[1]-e2[1])*180/Math.PI;
      var headIcon = L.divIcon({ html:'<div style="width:0;height:0;border-left:4px solid transparent;border-right:4px solid transparent;border-bottom:10px solid '+opColor+';transform:rotate('+angle+'deg);opacity:'+(isDimmed?0.08:0.8)+';filter:drop-shadow(0 0 2px '+opColor+');"></div>', iconSize:[8,10], iconAnchor:[4,5], className:'' });
      var arrowHead = L.marker([e1[0],e1[1]], { icon: headIcon, interactive: false });

      var originIcon = L.divIcon({ html:'<div style="width:5px;height:5px;background:'+opColor+';border-radius:50%;border:1px solid rgba(0,0,0,.6);box-shadow:0 0 5px '+opColor+';opacity:'+(isDimmed?0.08:0.85)+';"></div>', iconSize:[5,5], iconAnchor:[2,2], className:'' });
      var originMark = L.marker([f[0],f[1]], { icon: originIcon, interactive: false });

      var sz = isSelected ? 36 : 28;
      var targetIcon = L.divIcon({ html: buildMapIcon(inc, isSelected, isDimmed), iconSize:[sz,sz], iconAnchor:[sz/2,sz/2], className:'' });
      var targetMark = L.marker([t[0],t[1]], { icon: targetIcon, zIndexOffset: isSelected?200:100 });
      targetMark.on('click', function () { selectIncident(inc.id); });
      targetMark.bindTooltip('<div class="map-tooltip-inner"><b>'+inc.title+'</b><span class="tt-date">'+inc.date+'</span><span class="tt-conf" style="background:'+st.color+'22;color:'+st.color+';border:1px solid '+st.color+'44;">'+st.label.toUpperCase()+'</span></div>', { sticky: true });
      line.on('click', function () { selectIncident(inc.id); });

      return L.layerGroup([line, arrowHead, originMark, targetMark]);
    }

    // Visibility
    function isVisible(inc) {
      if (!activeOps.has(inc.op)) return false;
      if (inc.timeVal > timeVal) return false;
      var opCountries = (OPS[inc.op] || {}).countries || [];
      // If no country metadata exists (e.g. new operation added to CSV without OPS_META),
      // show the incident as long as the operation toggle is on.
      if (opCountries.length === 0) return true;
      return opCountries.some(function (c) { return activeCountries.has(c); });
    }

    // Renderers
    function renderMap() {
      Object.values(allLayers).forEach(function (l) { map.removeLayer(l); });
      allLayers = {};
      INCIDENTS.filter(isVisible).forEach(function (inc) {
        var grp = makeArrow(inc);
        if (grp) {
          grp.addTo(map);
          allLayers[inc.id] = grp;
        }
      });
    }

    function renderList() {
      var visible = INCIDENTS.filter(isVisible);
      $incCount.textContent = visible.length + ' shown';
      if (!visible.length) {
        $incList.innerHTML = '<div style="padding:18px;text-align:center;color:var(--text);font-size:9px;letter-spacing:1px;">NO INCIDENTS IN RANGE</div>';
        return;
      }
      var frag = document.createDocumentFragment();
      visible.slice().sort(function (a,b) { return b.timeVal-a.timeVal; }).forEach(function (inc) {
        var op = OPS[inc.op] || {}, col = op.color || '#fff';
        var st = STRIKE_TYPES[inc.type] || STRIKE_TYPES.missile;
        var d = document.createElement('div');
        d.className = 'inc-item' + (selectedId===inc.id?' selected':'');
        d.style.borderLeftColor = col;
        d.innerHTML = '<div class="inc-icon-wrap">'+buildListIcon(inc.type,18)+'</div><div class="inc-text"><div class="inc-item-op" style="color:'+col+'">'+(op.name||inc.op)+'</div><div class="inc-item-name">'+inc.title+'</div><div class="inc-item-meta">'+inc.date+' &middot; <span style="color:'+st.color+';font-weight:700;">'+st.label+'</span></div></div>';
        d.addEventListener('click', function () { selectIncident(inc.id); });
        frag.appendChild(d);
      });
      $incList.innerHTML = '';
      $incList.appendChild(frag);
    }

    // Selection & detail
    function selectIncident(id) {
      selectedId = id;
      renderMap(); renderList(); renderDetail();
    }

    function badge(txt, cls) { return '<span class="badge badge-'+cls+'">'+txt+'</span>'; }

    function renderDetail() {
      if (!selectedId) { $detPlaceholder.style.display='flex'; $detContent.style.display='none'; return; }
      var inc = INCIDENTS.find(function (i) { return i.id===selectedId; });
      if (!inc) return;
      $detPlaceholder.style.display='none'; $detContent.style.display='block';

      var op = OPS[inc.op] || {}, col = op.color || '#fff';
      var st = STRIKE_TYPES[inc.type] || STRIKE_TYPES.missile;
      var badgeHTML = (inc.badges||[]).map(function (b) { return badge(b[0],b[1]); }).join('');
      var intelRows = (inc.intel||[]).map(function (r) { return '<div class="drow"><div class="drow-k">'+r.k+'</div><div class="drow-v '+(r.hi?'hi':'')+' '+(r.cls||'')+'">'+r.v+'</div></div>'; }).join('');
      var srcHTML = (inc.sources||[]).map(function (s) { var nameHTML = s.u ? '<a class="source-link" href="'+s.u+'" target="_blank" rel="noopener noreferrer">'+s.n+'</a>' : s.n; return '<div class="source-item"><div class="source-name">'+nameHTML+'</div><div class="source-type">'+s.t+'</div></div>'; }).join('');
      var hasImagery = inc.imagery && inc.imagery.length > 0;
      var imgTabBtn = hasImagery ? '<div class="det-tab" data-tab="tab-imagery">Imagery</div>' : '';
      var imgBody = hasImagery ? '<div id="tab-imagery" class="det-tab-body">' + inc.imagery.map(function (img) {
        return '<div class="img-block"><div class="img-label">'+img.label+'</div><div><img src="'+img.url+'" class="sat-img" alt="'+img.label+'" onerror="this.parentElement.innerHTML=\'<div class=img-err>Image unavailable</div>\'"/></div>'+(img.caption?'<div class="img-caption">'+img.caption+'</div>':'')+(img.source?'<div class="img-source">Source: '+img.source+'</div>':'')+'</div>';
      }).join('') + '</div>' : '';

      var opCtags = (op.countries||[]).map(function (c) {
        var cn = COUNTRIES[c]; if (!cn) return '';
        return '<span style="font-size:9px;background:'+cn.bg+';color:'+cn.color+';border:1px solid '+cn.border+';padding:1px 6px;border-radius:2px;font-weight:700;">'+cn.label+'</span>';
      }).join('');

      $detContent.innerHTML =
        '<div class="det-hero"><div style="display:flex;align-items:center;gap:6px;margin-bottom:7px;flex-wrap:wrap;"><div class="det-op-tag" style="background:'+col+'22;color:'+col+';border:1px solid '+col+'44;">'+(op.name||inc.op)+'</div>'+opCtags+'</div><div class="det-title">'+inc.title+'</div><div class="det-date">'+inc.date+'</div><div class="det-conf-row">'+buildListIcon(inc.type,14)+'<span style="font-size:9px;font-weight:700;letter-spacing:1px;color:'+st.color+';text-transform:uppercase;">'+st.label+'</span>'+(inc.confirmed?'<span style="font-size:8px;color:var(--green);font-weight:700;letter-spacing:1px;margin-left:4px;">\u25CF CONFIRMED</span>':'<span style="font-size:8px;color:var(--gold);font-weight:700;letter-spacing:1px;margin-left:4px;">\u25D1 REPORTED</span>')+'</div><div class="det-badges">'+badgeHTML+'</div></div>'
        + '<div class="det-tabs"><div class="det-tab active" data-tab="tab-summary">Summary</div><div class="det-tab" data-tab="tab-intel">Intel</div>'+imgTabBtn+'<div class="det-tab" data-tab="tab-assess">Assessment</div><div class="det-tab" data-tab="tab-sources">Sources</div></div>'
        + '<div id="tab-summary" class="det-tab-body active"><div class="route-strip"><div class="route-from"><div class="route-label">Origin</div><div class="route-val">'+inc.from.label+'</div><div class="route-label" style="margin-top:1px;">'+inc.from.sub+'</div></div><div class="route-arrow">\u2192</div><div class="route-to"><div class="route-label">Target</div><div class="route-val" style="color:var(--accent2);">'+inc.to.label+'</div><div class="route-label" style="margin-top:1px;">'+inc.to.sub+'</div></div></div><div class="assessment"><div class="assessment-body">'+inc.summary+'</div></div></div>'
        + '<div id="tab-intel" class="det-tab-body">'+intelRows+'</div>'
        + imgBody
        + '<div id="tab-assess" class="det-tab-body"><div class="assessment"><div class="assessment-title">Operational Assessment</div><div class="assessment-body">'+inc.assess+'</div></div></div>'
        + '<div id="tab-sources" class="det-tab-body">'+srcHTML+'</div>';

      map.flyTo([inc.to.lat, inc.to.lng], Math.max(map.getZoom(),4), { duration: 1 });
    }

    $detScroll.addEventListener('click', function (e) {
      var tab = e.target.closest('.det-tab');
      if (!tab || !tab.dataset.tab) return;
      $detScroll.querySelectorAll('.det-tab').forEach(function (t) { t.classList.remove('active'); });
      $detScroll.querySelectorAll('.det-tab-body').forEach(function (b) { b.classList.remove('active'); });
      tab.classList.add('active');
      var target = $detScroll.querySelector('#'+tab.dataset.tab);
      if (target) target.classList.add('active');
    });

    // Country filter
    function renderCountryFilter() {
      $countryFilter.innerHTML = '';
      var frag = document.createDocumentFragment();
      Object.entries(COUNTRIES).forEach(function (entry) {
        var k = entry[0], cn = entry[1], on = activeCountries.has(k);
        var d = document.createElement('div');
        d.className = 'c-pill' + (on?'':' off');
        d.style.cssText = 'color:'+cn.color+';background:'+(on?cn.bg:'rgba(0,0,0,.3)')+';border-color:'+(on?cn.border:'rgba(255,255,255,.08)')+';';
        d.textContent = cn.label;
        d.addEventListener('click', function () {
          if (activeCountries.has(k)) activeCountries.delete(k); else activeCountries.add(k);
          deselectIfHidden(); refresh();
        });
        frag.appendChild(d);
      });
      $countryFilter.appendChild(frag);
    }

    // Op filter
    function renderOpFilter() {
      $opFilter.innerHTML = '';
      var frag = document.createDocumentFragment();
      Object.entries(OPS).forEach(function (entry) {
        var k = entry[0], op = entry[1];
        var on = activeOps.has(k);
        var cnt = INCIDENTS.filter(function (i) { return i.op===k && i.timeVal<=timeVal; }).length;
        var d = document.createElement('div');
        d.className = 'op-row' + (on?' on':' off');
        var ctags = (op.countries||[]).map(function (cc) {
          var cn = COUNTRIES[cc]; if (!cn) return '';
          return '<span class="op-ctag" style="background:'+cn.bg+';color:'+cn.color+';border:1px solid '+cn.border+'50;">'+cc+'</span>';
        }).join('');
        d.innerHTML = '<div class="op-color" style="background:'+(on?op.color:'#2a3d5a')+';"></div><div class="op-info"><div class="op-name" style="color:'+(on?op.color:'var(--text)')+'">'+op.name+'</div><div class="op-period">'+op.period+'</div><div class="op-country-tags">'+ctags+'</div></div><div class="op-count">'+cnt+'</div>';
        d.addEventListener('click', function () {
          if (activeOps.has(k)) activeOps.delete(k); else activeOps.add(k);
          deselectIfHidden(); refresh();
        });
        frag.appendChild(d);
      });
      $opFilter.appendChild(frag);
    }

    function renderOpLegend() {
      $opLegendItems.innerHTML = Object.entries(OPS).map(function (entry) {
        var op = entry[1];
        return '<div class="oleg-row"><div class="oleg-swatch" style="background:'+op.color+';'+(op.dashed?'border-bottom:1px dashed '+op.color+';background:transparent;':'')+'"></div><div class="oleg-text">'+op.name+'</div></div>';
      }).join('');
    }

    // Timeline
    function renderTLMarks() {
      $tlMarks.innerHTML = TL_MARKS.map(function (m) {
        return '<span class="tl-mark '+(m.v<=timeVal?'active':'')+'" data-tl-val="'+m.v+'">'+m.lbl+'</span>';
      }).join('');
    }

    $tlMarks.addEventListener('click', function (e) {
      var mark = e.target.closest('.tl-mark');
      if (!mark) return;
      setTime(parseInt(mark.dataset.tlVal, 10));
    });

    function setTime(v) {
      timeVal = v;
      $tlSlider.value = v;
      var lbl = TL_MARKS[0].lbl;
      TL_MARKS.forEach(function (m) { if (v >= m.v) lbl = m.lbl; });
      $tlDate.textContent = lbl.toUpperCase();
      renderTLMarks(); deselectIfHidden(); refresh();
    }

    $tlSlider.addEventListener('input', function () { setTime(parseInt(this.value,10)); });
    $btnShowAll.addEventListener('click', function () { setTime(parseInt($tlSlider.max, 10)); });
    $btnReset.addEventListener('click', function () { stopPlay(); setTime(parseInt($tlSlider.min, 10)); });
    $btnPlay.addEventListener('click', function () {
      if (playTimer) { stopPlay(); return; }
      $btnPlay.classList.add('playing');
      $btnPlay.textContent = '\u23F8 Pause';
      playTimer = setInterval(function () {
        var cur = parseInt($tlSlider.value, 10);
        var maxVal = parseInt($tlSlider.max, 10);
        if (cur >= maxVal) { stopPlay(); return; }
        setTime(Math.min(cur+1, maxVal));
      }, 90);
    });
    $btnPause.addEventListener('click', stopPlay);

    if ($btnOpsAll) {
      $btnOpsAll.addEventListener('click', function () {
        Object.keys(OPS).forEach(function (k) { activeOps.add(k); });
        deselectIfHidden(); refresh();
      });
    }
    if ($btnOpsNone) {
      $btnOpsNone.addEventListener('click', function () {
        activeOps.clear();
        selectedId = null; refresh();
      });
    }

    function stopPlay() {
      if (playTimer) { clearInterval(playTimer); playTimer = null; }
      $btnPlay.classList.remove('playing');
      $btnPlay.textContent = '\u25B6 Play';
    }

    function deselectIfHidden() {
      if (!selectedId) return;
      var inc = INCIDENTS.find(function (i) { return i.id===selectedId; });
      if (inc && !isVisible(inc)) selectedId = null;
    }

    function refresh() { renderMap(); renderList(); renderOpFilter(); renderCountryFilter(); refreshBorders(); }

    // Init
    renderOpLegend();
    renderTLMarks();
    refresh();
    setTime(parseInt($tlSlider.max, 10));
  }

  // ── Fetch CSV and start ──

  fetch('operationsdata.csv?v=' + Date.now())
    .then(function (res) {
      if (!res.ok) throw new Error('CSV fetch failed: ' + res.status);
      return res.text();
    })
    .then(boot)
    .catch(function (err) {
      console.error('Failed to load CSV data:', err);
      document.body.innerHTML = '<div style="color:#f44;padding:40px;font-family:monospace;">Failed to load operationsdata.csv: ' + err.message + '</div>';
    });

})();
