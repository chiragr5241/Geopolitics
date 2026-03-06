'use strict';

/* =========================================================
   GLOBAL OPERATIONS MAP 2025–2026 — Application Logic
   Depends on: Leaflet (L), config.js globals, DataLayer
   All data is loaded via DataLayer (js/data.js).
   ========================================================= */

(function () {

  // ── Data Transformation ──

  function buildImageryIndex(imageryRows) {
    // Build a lookup: incident_id → array of image objects
    var index = {};
    imageryRows.forEach(function (r) {
      var id = r.incident_id;
      if (!id) return;
      if (!index[id]) index[id] = [];
      index[id].push({
        label:   r.label   || '',
        url:     r.url     || '',
        caption: r.caption || '',
        source:  r.source  || '',
      });
    });
    return index;
  }

  function buildOpsIndex(operationsRows) {
    // Build a lookup: operation_name → operation object
    var index = {};
    operationsRows.forEach(function (r) {
      var name = r.operation_name;
      if (!name) return;
      var countries = r.countries
        ? r.countries.split(';').map(function (c) { return c.trim(); }).filter(Boolean)
        : [];
      index[name] = {
        name:      name,
        color:     r.color    || '#ffffff',
        countries: countries,
        period:    r.period   || '',
        dashed:    r.dashed === 'true',
      };
    });
    return index;
  }

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

  function csvRowToIncident(r, imageryIndex) {
    return {
      id:        r.incident_id,
      op:        r.operation_name,
      type:      r.strike_type,
      timeVal:   parseInt(r.date_sort_value, 10) || 0,
      title:     r.incident_title,
      date:      r.date,
      confirmed: r.confirmed === 'TRUE' || r.confirmed === 'true',
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
      imagery:  imageryIndex[r.incident_id] || [],
    };
  }

  // ── Boot ──

  function boot(data) {
    var imageryIndex = buildImageryIndex(data.imagery);
    var OPS = buildOpsIndex(data.operations);

    // Build incidents; fall back to operation_color from incident row if
    // the operation isn't yet in operations.csv.
    var INCIDENTS = data.incidents.map(function (r) {
      if (!OPS[r.operation_name]) {
        OPS[r.operation_name] = {
          name:      r.operation_name,
          color:     r.operation_color || '#ffffff',
          countries: [],
          period:    '',
          dashed:    false,
        };
      }
      return csvRowToIncident(r, imageryIndex);
    });

    // Attach resolved color to each incident for convenient access
    INCIDENTS.forEach(function (inc) {
      inc.opColor = (OPS[inc.op] || {}).color || '#ffffff';
    });

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

    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19, minZoom: 2, noWrap: true,
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
      return { color: '#a09888', weight: 0.5, opacity: 0.35, fillColor: 'transparent', fillOpacity: 0 };
    }

    // Fix antimeridian rendering artefacts in world-atlas data.
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
    var $hTheaters      = document.getElementById('h-theaters');

    // Derive header stats from data
    $hOps.textContent = Object.keys(OPS).length + ' OPS';

    var theaterCountries = new Set();
    Object.values(OPS).forEach(function (op) {
      (op.countries || []).forEach(function (c) { theaterCountries.add(c); });
    });
    if ($hTheaters) $hTheaters.textContent = theaterCountries.size + ' THEATERS';

    // Icon builders
    function buildMapIcon(inc, isSelected, isDimmed) {
      var st = STRIKE_TYPES[inc.type] || STRIKE_TYPES.missile;
      var sz = isSelected ? 18 : 13;
      // Animate only the newest visible events relative to current slider position
      var RECENT_THRESHOLD = 2; // ~10 days on the slider scale
      var isRecent = !isDimmed && inc.timeVal <= timeVal && (timeVal - inc.timeVal) <= RECENT_THRESHOLD;
      var mainOp  = isDimmed ? 0.12 : 1;
      var pulseOp = isRecent ? (isSelected ? 0.55 : 0.35) : 0;
      var c  = st.color, bg = st.bgFill;
      var pulseEl = isRecent
        ? '<svg style="position:absolute;inset:0;overflow:visible;" width="' + sz + '" height="' + sz + '"><circle cx="' + sz/2 + '" cy="' + sz/2 + '" r="' + (sz/2-1) + '" fill="none" stroke="' + c + '" stroke-width="1.5" opacity="' + pulseOp + '" style="animation:ring-pulse 2.2s ease-out infinite;transform-origin:' + sz/2 + 'px ' + sz/2 + 'px;"/></svg>'
        : '';
      return '<div style="position:relative;width:' + sz + 'px;height:' + sz + 'px;cursor:pointer;">'
        + pulseEl
        + '<svg style="position:absolute;inset:0;" width="' + sz + '" height="' + sz + '" opacity="' + mainOp + '"><circle cx="' + sz/2 + '" cy="' + sz/2 + '" r="' + (sz/2-1) + '" fill="' + bg + '" fill-opacity="0.95" stroke="' + c + '" stroke-width="' + (isSelected?2:1.5) + '"/>' + st.getSVG(sz,c) + (isSelected?'<circle cx="'+sz/2+'" cy="'+sz/2+'" r="'+(sz/2-1)+'" fill="none" stroke="'+c+'" stroke-width="0.8" opacity="0.4"/>':'') + '</svg></div>';
    }

    function buildListIcon(type, sz) {
      sz = sz || 16;
      var st = STRIKE_TYPES[type] || STRIKE_TYPES.missile;
      return '<svg width="' + sz + '" height="' + sz + '" viewBox="0 0 ' + sz + ' ' + sz + '"><circle cx="' + sz/2 + '" cy="' + sz/2 + '" r="' + (sz/2-1) + '" fill="' + st.bgFill + '" fill-opacity="0.9" stroke="' + st.color + '" stroke-width="1.5"/>' + st.getSVG(sz, st.color) + '</svg>';
    }

    // Arrow rendering
    function makeArrow(inc) {
      if (isNaN(inc.to.lat) || isNaN(inc.to.lng)) {
        return null;
      }

      var op = OPS[inc.op] || {};
      var opColor = op.color || '#fff';
      var isDash = !!op.dashed;
      var st = STRIKE_TYPES[inc.type] || STRIKE_TYPES.missile;
      var isSelected = inc.id === selectedId;
      var isDimmed = selectedId && !isSelected;

      var hasOrigin = !isNaN(inc.from.lat) && !isNaN(inc.from.lng);
      var t = [inc.to.lat, inc.to.lng];

      var sz = isSelected ? 26 : 20;
      var targetIcon = L.divIcon({ html: buildMapIcon(inc, isSelected, isDimmed), iconSize:[sz,sz], iconAnchor:[sz/2,sz/2], className:'' });
      var targetMark = L.marker(t, { icon: targetIcon, zIndexOffset: isSelected?200:100 });
      targetMark.on('click', function () { selectIncident(inc.id); });
      targetMark.bindTooltip('<div class="map-tooltip-inner"><b>'+inc.title+'</b><span class="tt-date">'+inc.date+'</span><span class="tt-conf" style="background:'+st.color+'22;color:'+st.color+';border:1px solid '+st.color+'44;">'+st.label.toUpperCase()+'</span></div>', { sticky: true });

      if (!hasOrigin) {
        return L.layerGroup([targetMark]);
      }

      var f = [inc.from.lat, inc.from.lng];
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
      var originMark = L.marker(f, { icon: originIcon, interactive: false });
      line.on('click', function () { selectIncident(inc.id); });

      return L.layerGroup([line, arrowHead, originMark, targetMark]);
    }

    // Visibility
    function isVisible(inc) {
      if (!activeOps.has(inc.op)) return false;
      if (inc.timeVal > timeVal) return false;
      var opCountries = (OPS[inc.op] || {}).countries || [];
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
        d.style.cssText = 'color:'+cn.color+';background:'+(on?cn.bg:'rgba(0,0,0,.06)')+';border-color:'+(on?cn.border:'rgba(0,0,0,.15)')+';';
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

      // Sort: most-recent incident date DESC, then total incident count DESC
      var opEntries = Object.entries(OPS).sort(function (a, b) {
        var incA = INCIDENTS.filter(function (i) { return i.op === a[0]; });
        var incB = INCIDENTS.filter(function (i) { return i.op === b[0]; });
        var maxA = incA.length ? Math.max.apply(null, incA.map(function (i) { return i.timeVal; })) : -999;
        var maxB = incB.length ? Math.max.apply(null, incB.map(function (i) { return i.timeVal; })) : -999;
        if (maxB !== maxA) return maxB - maxA;
        return incB.length - incA.length;
      });

      opEntries.forEach(function (entry) {
        var k = entry[0], op = entry[1];
        var on = activeOps.has(k);
        // Visible count respects country filter (same logic as isVisible minus op-active check)
        var visibleCnt = INCIDENTS.filter(function (i) {
          if (i.op !== k || i.timeVal > timeVal) return false;
          var opC = op.countries || [];
          if (opC.length === 0) return true;
          return opC.some(function (c) { return activeCountries.has(c); });
        }).length;
        var isZero = visibleCnt === 0;
        var swatchColor = (on && !isZero) ? op.color : '#b0a894';
        var nameColor   = (on && !isZero) ? op.color : 'var(--text)';
        var d = document.createElement('div');
        d.className = 'op-row' + (on?' on':' off') + (isZero?' op-zero':'');
        var ctags = (op.countries||[]).map(function (cc) {
          var cn = COUNTRIES[cc]; if (!cn) return '';
          return '<span class="op-ctag" style="background:'+cn.bg+';color:'+cn.color+';border:1px solid '+cn.border+';">'+cc+'</span>';
        }).join('');
        d.innerHTML = '<div class="op-color" style="background:'+swatchColor+';"></div><div class="op-info"><div class="op-name" style="color:'+nameColor+'">'+op.name+'</div><div class="op-period">'+op.period+'</div><div class="op-country-tags">'+ctags+'</div></div><div class="op-count">'+visibleCnt+'</div>';
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

    var $btnCountryAll  = document.getElementById('btn-country-all');
    var $btnCountryNone = document.getElementById('btn-country-none');
    if ($btnCountryAll) {
      $btnCountryAll.addEventListener('click', function () {
        Object.keys(COUNTRIES).forEach(function (k) { activeCountries.add(k); });
        deselectIfHidden(); refresh();
      });
    }
    if ($btnCountryNone) {
      $btnCountryNone.addEventListener('click', function () {
        activeCountries.clear();
        deselectIfHidden(); refresh();
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

  // ── Load all data via DataLayer and start ──

  DataLayer.loadAll()
    .then(boot)
    .catch(function (err) {
      console.error('Failed to load data:', err);
      document.body.innerHTML = '<div style="color:#f44;padding:40px;font-family:monospace;">Failed to load data: ' + err.message + '</div>';
    });

})();
