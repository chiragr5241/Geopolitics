'use strict';

/* =========================================================
   GLOBAL OPERATIONS MAP 2025–2026 — Static Configuration
   Rendering config that rarely changes: country palettes,
   SVG strike-type icons, city labels, timeline marks,
   operation metadata, and per-incident imagery.
   ========================================================= */

// ── ISO-3166-1 Numeric → Country Code (for world-atlas GeoJSON border layer) ──

var ISO_NUM_MAP = {
  840: 'US',  // United States
  376: 'IL',  // Israel
  364: 'IR',  // Iran
  156: 'CN',  // China
  862: 'VE',  // Venezuela
  887: 'YE',  // Yemen
  608: 'PH',  // Philippines
  804: 'UA',  // Ukraine
  643: 'RU',  // Russia
  275: 'PS',  // Palestine
  422: 'LB',  // Lebanon
};

// ── Country Rendering ──

var COUNTRIES = {
  US: { label: '\u{1F1FA}\u{1F1F8} US',     color: '#4fc3f7', bg: 'rgba(79,195,247,.15)',  border: 'rgba(79,195,247,.5)'  },
  IL: { label: '\u{1F1EE}\u{1F1F1} Israel', color: '#ce93d8', bg: 'rgba(206,147,216,.15)', border: 'rgba(206,147,216,.5)' },
  IR: { label: '\u{1F1EE}\u{1F1F7} Iran',   color: '#ef5350', bg: 'rgba(239,83,80,.15)',   border: 'rgba(239,83,80,.5)'   },
  CN: { label: '\u{1F1E8}\u{1F1F3} China',  color: '#ff5252', bg: 'rgba(255,82,82,.15)',   border: 'rgba(255,82,82,.5)'   },
  VE: { label: '\u{1F1FB}\u{1F1EA} Venez.', color: '#ffd54f', bg: 'rgba(255,213,79,.15)',  border: 'rgba(255,213,79,.5)'  },
  YE: { label: '\u{1F1FE}\u{1F1EA} Houthi', color: '#f06292', bg: 'rgba(240,98,146,.15)',  border: 'rgba(240,98,146,.5)'  },
  PH: { label: '\u{1F1F5}\u{1F1ED} PHL',    color: '#26c6da', bg: 'rgba(38,198,218,.15)',  border: 'rgba(38,198,218,.5)'  },
  UA: { label: '\u{1F1FA}\u{1F1E6} Ukraine', color: '#fdd835', bg: 'rgba(253,216,53,.15)', border: 'rgba(253,216,53,.5)' },
  RU: { label: '\u{1F1F7}\u{1F1FA} Russia', color: '#e53935', bg: 'rgba(229,57,53,.15)',   border: 'rgba(229,57,53,.5)'   },
  PS: { label: '\u{1F1F5}\u{1F1F8} Palest.', color: '#43a047', bg: 'rgba(67,160,71,.15)',  border: 'rgba(67,160,71,.5)'  },
  LB: { label: '\u{1F1F1}\u{1F1E7} Lebanon', color: '#8d6e63', bg: 'rgba(141,110,99,.15)',  border: 'rgba(141,110,99,.5)'  },
};

// ── Operation Metadata (keyed by operation_name as it appears in the CSV) ──

var OPS_META = {
  'Op. Swords of Iron':   { countries: ['IL','PS'], period: 'Oct 2023\u2013present', dashed: false },
  'Op. Northern Arrows':  { countries: ['IL','IR','LB'], period: 'Apr\u2013Oct 2024', dashed: false },
  'Russia-Ukraine War':   { countries: ['UA','RU'], period: '2022\u2013present',     dashed: false },
  'Op. Midnight Hammer':  { countries: ['US'],      period: 'Jun 2025',              dashed: false },
  '12-Day War (IDF)':     { countries: ['IL','US'], period: 'Jun 2025',              dashed: false },
  'Op. Absolute Resolve': { countries: ['US'],      period: 'Dec 2025\u2013Jan 2026', dashed: false },
  'Op. Southern Spear':   { countries: ['US'],      period: 'Jan 2026',              dashed: false },
  'Op. Epic Fury':        { countries: ['US','IL'], period: 'Feb 28, 2026',          dashed: false },
  'Op. Roaring Lion':     { countries: ['US','IL'], period: 'Feb 28, 2026',          dashed: false },
  'Iran Retaliation':     { countries: ['IR','YE'], period: 'Feb\u2013Mar 2026',     dashed: true  },
  'Houthi / Proxies':     { countries: ['YE','IR'], period: '2025\u20132026',        dashed: true  },
  'China SCS Operations': { countries: ['CN','PH'], period: '2025\u20132026',        dashed: true  },
};

// ── Strike Type SVG Icons ──

var STRIKE_TYPES = {
  bomber: {
    color: '#4caf50', bgFill: '#0d3320', label: 'Confirmed Airstrike',
    getSVG: function (sz, c) {
      return '<polygon points="' + sz*.5 + ',' + sz*.25 + ' ' + sz*.85 + ',' + sz*.65 + ' ' + sz*.7 + ',' + sz*.6 + ' ' + sz*.55 + ',' + sz*.72 + ' ' + sz*.45 + ',' + sz*.72 + ' ' + sz*.3 + ',' + sz*.6 + ' ' + sz*.15 + ',' + sz*.65 + '" fill="' + c + '" opacity=".95"/>';
    }
  },
  fighter: {
    color: '#4caf50', bgFill: '#0d3320', label: 'Confirmed Airstrike',
    getSVG: function (sz, c) {
      var cx = sz / 2;
      return '<polygon points="' + cx + ',' + sz*.2 + ' ' + (cx+sz*.04) + ',' + sz*.45 + ' ' + sz*.82 + ',' + sz*.72 + ' ' + sz*.75 + ',' + sz*.78 + ' ' + cx + ',' + sz*.58 + ' ' + sz*.25 + ',' + sz*.78 + ' ' + sz*.18 + ',' + sz*.72 + ' ' + (cx-sz*.04) + ',' + sz*.45 + '" fill="' + c + '" opacity=".95"/>'
           + '<rect x="' + (cx-sz*.02) + '" y="' + sz*.18 + '" width="' + sz*.04 + '" height="' + sz*.4 + '" rx="1" fill="' + c + '"/>';
    }
  },
  missile: {
    color: '#2196f3', bgFill: '#0d2540', label: 'Reported Strike',
    getSVG: function (sz, c) {
      var cx = sz / 2;
      return '<rect x="' + (cx-sz*.07) + '" y="' + sz*.22 + '" width="' + sz*.14 + '" height="' + sz*.45 + '" rx="' + sz*.06 + '" fill="' + c + '" opacity=".9"/>'
           + '<polygon points="' + cx + ',' + sz*.16 + ' ' + (cx+sz*.07) + ',' + sz*.3 + ' ' + (cx-sz*.07) + ',' + sz*.3 + '" fill="' + c + '"/>'
           + '<polygon points="' + (cx-sz*.07) + ',' + sz*.56 + ' ' + (cx-sz*.2) + ',' + sz*.72 + ' ' + (cx-sz*.07) + ',' + sz*.67 + '" fill="' + c + '" opacity=".8"/>'
           + '<polygon points="' + (cx+sz*.07) + ',' + sz*.56 + ' ' + (cx+sz*.2) + ',' + sz*.72 + ' ' + (cx+sz*.07) + ',' + sz*.67 + '" fill="' + c + '" opacity=".8"/>';
    }
  },
  naval: {
    color: '#9c27b0', bgFill: '#1a0d30', label: 'Naval Operation',
    getSVG: function (sz, c) {
      var cx = sz / 2;
      return '<circle cx="' + cx + '" cy="' + sz*.32 + '" r="' + sz*.08 + '" fill="none" stroke="' + c + '" stroke-width="' + sz*.07 + '"/>'
           + '<line x1="' + cx + '" y1="' + sz*.4 + '" x2="' + cx + '" y2="' + sz*.76 + '" stroke="' + c + '" stroke-width="' + sz*.07 + '"/>'
           + '<line x1="' + sz*.25 + '" y1="' + sz*.5 + '" x2="' + sz*.75 + '" y2="' + sz*.5 + '" stroke="' + c + '" stroke-width="' + sz*.07 + '"/>'
           + '<path d="M' + sz*.25 + ',' + sz*.76 + ' Q' + cx + ',' + sz*.88 + ' ' + sz*.75 + ',' + sz*.76 + '" fill="none" stroke="' + c + '" stroke-width="' + sz*.07 + '"/>';
    }
  },
  sof: {
    color: '#9c27b0', bgFill: '#1a0d30', label: 'Special Operation',
    getSVG: function (sz, c) {
      var cx = sz / 2, cy = sz / 2, r = sz * .28;
      return '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="' + c + '" stroke-width="' + sz*.06 + '"/>'
           + '<circle cx="' + cx + '" cy="' + cy + '" r="' + r*.3 + '" fill="' + c + '"/>'
           + '<line x1="' + cx + '" y1="' + sz*.1 + '" x2="' + cx + '" y2="' + (cy-r) + '" stroke="' + c + '" stroke-width="' + sz*.06 + '"/>'
           + '<line x1="' + cx + '" y1="' + (cy+r) + '" x2="' + cx + '" y2="' + sz*.9 + '" stroke="' + c + '" stroke-width="' + sz*.06 + '"/>'
           + '<line x1="' + sz*.1 + '" y1="' + cy + '" x2="' + (cx-r) + '" y2="' + cy + '" stroke="' + c + '" stroke-width="' + sz*.06 + '"/>'
           + '<line x1="' + (cx+r) + '" y1="' + cy + '" x2="' + sz*.9 + '" y2="' + cy + '" stroke="' + c + '" stroke-width="' + sz*.06 + '"/>';
    }
  },
  drone: {
    color: '#ffc107', bgFill: '#2d1a00', label: 'Strike w/ Footage',
    getSVG: function (sz, c) {
      var cx = sz / 2, cy = sz / 2, r = sz * .3;
      var pts = [];
      for (var i = 0; i < 6; i++) {
        var a = (i * 60 - 90) * Math.PI / 180;
        pts.push((cx + r * Math.cos(a)) + ',' + (cy + r * Math.sin(a)));
      }
      return '<polygon points="' + pts.join(' ') + '" fill="none" stroke="' + c + '" stroke-width="' + sz*.06 + '"/>'
           + '<circle cx="' + cx + '" cy="' + cy + '" r="' + sz*.1 + '" fill="' + c + '"/>'
           + '<line x1="' + (cx-sz*.32) + '" y1="' + (cy-sz*.32) + '" x2="' + (cx-sz*.17) + '" y2="' + (cy-sz*.17) + '" stroke="' + c + '" stroke-width="' + sz*.05 + '"/>'
           + '<line x1="' + (cx+sz*.32) + '" y1="' + (cy-sz*.32) + '" x2="' + (cx+sz*.17) + '" y2="' + (cy-sz*.17) + '" stroke="' + c + '" stroke-width="' + sz*.05 + '"/>'
           + '<line x1="' + (cx-sz*.32) + '" y1="' + (cy+sz*.32) + '" x2="' + (cx-sz*.17) + '" y2="' + (cy+sz*.17) + '" stroke="' + c + '" stroke-width="' + sz*.05 + '"/>'
           + '<line x1="' + (cx+sz*.32) + '" y1="' + (cy+sz*.32) + '" x2="' + (cx+sz*.17) + '" y2="' + (cy+sz*.17) + '" stroke="' + c + '" stroke-width="' + sz*.05 + '"/>';
    }
  },
  retaliation: {
    color: '#ff9800', bgFill: '#2d1a00', label: 'Retaliation / Proxy',
    getSVG: function (sz, c) {
      return '<polygon points="' + sz*.55 + ',' + sz*.18 + ' ' + sz*.3 + ',' + sz*.52 + ' ' + sz*.47 + ',' + sz*.52 + ' ' + sz*.42 + ',' + sz*.82 + ' ' + sz*.68 + ',' + sz*.46 + ' ' + sz*.52 + ',' + sz*.46 + '" fill="' + c + '" opacity=".95"/>';
    }
  },
  intel: {
    color: '#607d8b', bgFill: '#151515', label: 'Intel / Buildup',
    getSVG: function (sz, c) {
      var cx = sz / 2;
      return '<rect x="' + sz*.22 + '" y="' + sz*.28 + '" width="' + sz*.56 + '" height="' + sz*.38 + '" rx="2" fill="none" stroke="' + c + '" stroke-width="' + sz*.06 + '"/>'
           + '<rect x="' + sz*.16 + '" y="' + sz*.66 + '" width="' + sz*.68 + '" height="' + sz*.1 + '" rx="1" fill="' + c + '" opacity=".7"/>'
           + '<line x1="' + (cx-sz*.07) + '" y1="' + sz*.28 + '" x2="' + (cx-sz*.07) + '" y2="' + sz*.22 + '" stroke="' + c + '" stroke-width="' + sz*.05 + '"/>'
           + '<line x1="' + (cx+sz*.07) + '" y1="' + sz*.28 + '" x2="' + (cx+sz*.07) + '" y2="' + sz*.22 + '" stroke="' + c + '" stroke-width="' + sz*.05 + '"/>';
    }
  },
  maritime: {
    color: '#26c6da', bgFill: '#0a1a20', label: 'Maritime Coercion',
    getSVG: function (sz, c) {
      var cx = sz / 2;
      return '<rect x="' + sz*.18 + '" y="' + sz*.5 + '" width="' + sz*.64 + '" height="' + sz*.2 + '" rx="2" fill="' + c + '" opacity=".85"/>'
           + '<rect x="' + sz*.35 + '" y="' + sz*.32 + '" width="' + sz*.3 + '" height="' + sz*.2 + '" rx="1" fill="' + c + '" opacity=".7"/>'
           + '<line x1="' + cx + '" y1="' + sz*.16 + '" x2="' + cx + '" y2="' + sz*.32 + '" stroke="' + c + '" stroke-width="' + sz*.05 + '"/>'
           + '<line x1="' + (cx-sz*.12) + '" y1="' + sz*.22 + '" x2="' + (cx+sz*.12) + '" y2="' + sz*.22 + '" stroke="' + c + '" stroke-width="' + sz*.05 + '"/>'
           + '<polygon points="' + sz*.18 + ',' + sz*.7 + ' ' + sz*.82 + ',' + sz*.7 + ' ' + sz*.78 + ',' + sz*.78 + ' ' + sz*.22 + ',' + sz*.78 + '" fill="' + c + '" opacity=".9"/>';
    }
  },
  island: {
    color: '#26c6da', bgFill: '#0a1a20', label: 'Island Construction',
    getSVG: function (sz, c) {
      var cx = sz / 2, cy = sz / 2;
      return '<ellipse cx="' + cx + '" cy="' + (cy+sz*.05) + '" rx="' + sz*.32 + '" ry="' + sz*.18 + '" fill="' + c + '" opacity=".5"/>'
           + '<ellipse cx="' + cx + '" cy="' + (cy+sz*.05) + '" rx="' + sz*.24 + '" ry="' + sz*.12 + '" fill="' + c + '" opacity=".8"/>'
           + '<rect x="' + (cx-sz*.1) + '" y="' + sz*.28 + '" width="' + sz*.2 + '" height="' + sz*.2 + '" rx="1" fill="' + c + '" opacity=".9"/>'
           + '<line x1="' + cx + '" y1="' + sz*.16 + '" x2="' + cx + '" y2="' + sz*.28 + '" stroke="' + c + '" stroke-width="' + sz*.06 + '"/>';
    }
  },
  nuke: {
    color: '#f44336', bgFill: '#300d0d', label: 'Unverified Report',
    getSVG: function (sz, c) {
      var cx = sz / 2, cy = sz / 2;
      return '<circle cx="' + cx + '" cy="' + cy + '" r="' + sz*.28 + '" fill="none" stroke="' + c + '" stroke-width="' + sz*.06 + '"/>'
           + '<line x1="' + cx + '" y1="' + sz*.12 + '" x2="' + cx + '" y2="' + sz*.44 + '" stroke="' + c + '" stroke-width="' + sz*.06 + '"/>'
           + '<line x1="' + cx + '" y1="' + sz*.56 + '" x2="' + cx + '" y2="' + sz*.88 + '" stroke="' + c + '" stroke-width="' + sz*.06 + '" transform="rotate(60,' + cx + ',' + cy + ')"/>'
           + '<line x1="' + cx + '" y1="' + sz*.56 + '" x2="' + cx + '" y2="' + sz*.88 + '" stroke="' + c + '" stroke-width="' + sz*.06 + '" transform="rotate(-60,' + cx + ',' + cy + ')"/>'
           + '<circle cx="' + cx + '" cy="' + cy + '" r="' + sz*.1 + '" fill="' + c + '"/>';
    }
  },
};

// ── City Map Labels ──

var CITIES = [
  { lat: 35.68,  lng: 51.39,   name: 'Tehran' },
  { lat: 33.72,  lng: 51.73,   name: 'Natanz' },
  { lat: 34.88,  lng: 50.50,   name: 'Fordow' },
  { lat: 32.65,  lng: 51.67,   name: 'Isfahan' },
  { lat: 27.09,  lng: 57.05,   name: 'Minab' },
  { lat: 29.37,  lng: 47.97,   name: 'Kuwait City' },
  { lat: 31.77,  lng: 35.21,   name: 'Jerusalem' },
  { lat: 32.08,  lng: 34.78,   name: 'Tel Aviv' },
  { lat: 24.45,  lng: 54.37,   name: 'Abu Dhabi' },
  { lat: 25.20,  lng: 55.27,   name: 'Dubai' },
  { lat: 24.68,  lng: 46.72,   name: 'Riyadh' },
  { lat: 25.28,  lng: 51.53,   name: 'Doha' },
  { lat: 10.48,  lng: -66.90,  name: 'Caracas' },
  { lat: -7.32,  lng: 72.42,   name: 'Diego Garcia' },
  { lat: 33.89,  lng: 35.49,   name: 'Beirut' },
  { lat: 15.36,  lng: 44.19,   name: "Sana'a" },
  { lat: 26.22,  lng: 50.59,   name: 'Manama' },
  { lat: 23.62,  lng: 58.59,   name: 'Muscat' },
  { lat: 20.0,   lng: 110.35,  name: 'Sanya (PLAN)' },
  { lat: 22.3,   lng: 114.1,   name: 'Hong Kong' },
  { lat: 25.04,  lng: 121.51,  name: 'Taipei' },
  { lat: 14.59,  lng: 120.98,  name: 'Manila' },
  { lat: 9.73,   lng: 115.52,  name: '2nd Thomas Shoal' },
  { lat: 9.9,    lng: 115.53,  name: 'Mischief Rf.' },
  { lat: 11.5,   lng: 114.5,   name: 'Fiery Cross Rf.' },
  { lat: 15.13,  lng: 117.77,  name: 'Scarborough' },
  { lat: 31.52,  lng: 34.46,   name: 'Gaza' },
  { lat: 50.45,  lng: 30.52,   name: 'Kyiv' },
  { lat: 51.19,  lng: 35.27,   name: 'Sudzha' },
  { lat: 55.75,  lng: 37.62,   name: 'Moscow' },
];

// ── Timeline Marks ──

var TL_MARKS = [
  { v: -60, lbl: 'Oct 2023' },
  { v: -35, lbl: 'Apr 2024' },
  { v: -25, lbl: 'Aug 2024' },
  { v: -15, lbl: 'Nov 2024' },
  { v: 0,   lbl: 'Jun 2025' },
  { v: 10,  lbl: 'Mar 2025' },
  { v: 18,  lbl: 'Sep 2025' },
  { v: 32,  lbl: 'Dec 2025' },
  { v: 45,  lbl: 'Jan 2026' },
  { v: 65,  lbl: 'Feb 28' },
  { v: 82,  lbl: 'Mar 2026' },
  { v: 100, lbl: 'Now' },
];

// ── Imagery (keyed by incident_id, only for incidents that have images) ──

var IMAGERY = {
  'mh-fordow': [
    { label: 'B-2 Spirit Stealth Bomber', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/B-2_Spirit_original.jpg/1280px-B-2_Spirit_original.jpg', caption: 'B-2 Spirit dropping ordnance. Seven flew round-trip from Diego Garcia (~13,000 km) requiring 52 tankers.', source: 'USAF / Wikimedia Commons (public domain)' },
    { label: 'GBU-57 Massive Ordnance Penetrator', url: 'https://upload.wikimedia.org/wikipedia/commons/b/bb/USAF_MOP_test_release_crop.jpg', caption: 'GBU-57A/B MOP \u2014 30,000 lb, Eglin steel alloy casing. Fordow required 12 (vs 2 at Natanz).', source: 'USAF / Wikimedia Commons (public domain)' },
  ],
  'mh-natanz': [
    { label: 'Natanz \u2014 Satellite Pre-Strike', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/01/Atomanlage_Natanz_%282022%29.jpg/1280px-Atomanlage_Natanz_%282022%29.jpg', caption: 'Pre-strike satellite imagery of Iranian nuclear enrichment infrastructure. Natanz houses centrifuge halls ~8m underground with reinforced concrete.', source: 'DigitalGlobe / IAEA (pre-strike OSINT)' },
  ],
  'tdw-campaign': [
    { label: 'F-35I Adir \u2014 Primary Strike Platform', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/1/14/F-35I-Adir-0296.jpg/1280px-F-35I-Adir-0296.jpg', caption: 'F-35I Adir \u2014 Israeli customized variant with indigenous avionics. Low-observable design penetrated Iran\'s S-300 network.', source: 'Israeli Air Force / Wikimedia Commons (public domain)' },
    { label: 'S-300 Battery \u2014 Neutralized', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/5/51/S-300_Triumf_-_MAKS-2009_%28uncropped%29.jpg/1200px-S-300_Triumf_-_MAKS-2009_%28uncropped%29.jpg', caption: 'S-300PMU2 batteries could not track the F-35I at combat altitude \u2014 rendered effectively blind by stealth.', source: 'Wikimedia Commons (public domain)' },
  ],
  'ocean-trader': [
    { label: 'ESA Sentinel-2 \u2014 Commercial Satellite (Detection Method)', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/5/5e/Sentinel-2_image_on_2019-05-08_showing_Heraklion%2C_Crete%2C_Greece.jpg/1200px-Sentinel-2_image_on_2019-05-08_showing_Heraklion%2C_Crete%2C_Greece.jpg', caption: 'Sentinel-2 multispectral imagery (10m resolution). OSINT analysts cross-referenced AIS gaps with satellite data to confirm the vessel\'s classified mission profile days before the operation launched.', source: 'ESA Copernicus / @MT_Anderson OSINT' },
    { label: 'USS Lake Erie (CG-70) \u2014 Ticonderoga-class Cruiser Escort', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c9/USS_Lake_Erie_%28CG-70%29_underway.jpg/1200px-USS_Lake_Erie_%28CG-70%29_underway.jpg', caption: 'USS Lake Erie (CG-70) assigned as protective escort for MV Ocean Trader.', source: 'US Navy / Wikimedia Commons (public domain)' },
    { label: 'MH-60 SOF Helicopter Insertion', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a4/MH-60_Black_Hawk.jpg/1280px-MH-60_Black_Hawk.jpg', caption: 'MH-60 Black Hawk variant used for SOF insertion from the Ocean Trader to the Caracas target.', source: 'US Army / Wikimedia Commons (public domain)' },
  ],
  'abs-resolve': [
    { label: 'SOF Helicopter Raid \u2014 Caracas Insertion', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/a4/MH-60_Black_Hawk.jpg/1280px-MH-60_Black_Hawk.jpg', caption: 'SOF forces inserted by helicopter from the MV Ocean Trader staging platform. Zero US casualties.', source: 'US Army / Wikimedia Commons (public domain)' },
  ],
  'ef-main': [
    { label: 'Tomahawk VLS Launch \u2014 Arleigh Burke DDG', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/e/e8/Tomahawk_Block_IV_launch.jpg/1280px-Tomahawk_Block_IV_launch.jpg', caption: 'Tomahawk Block IV launch from Vertical Launch System. 13 Arleigh Burke DDGs contributed to the 900+ strike opening salvo.', source: 'US Navy / Wikimedia Commons (public domain)' },
  ],
  'ef-prsm': [
    { label: 'HIMARS \u2014 PrSM Launch Platform', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/06/HIMARS_launch.jpg/1280px-HIMARS_launch.jpg', caption: 'US Army HIMARS firing from Kuwait. PrSM made its combat debut from these platforms, demonstrating 499+ km range.', source: 'US Army / Wikimedia Commons (public domain)' },
  ],
  'rl-khamenei': [
    { label: 'JDAM Bunker Strike Munition', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/6/6f/U.S._Air_Force_Senior_Airman_Ryan_Minner%2C_a_load_crew_member_with_the_509th_Maintenance_Squadron%2C_poses_for_a_photo_under_a_GBU-31_joint_direct_attack_munition_and_a_Mark_84_munition_in_a_B-2_Spirit_aircraft_140221-F-RH756-320.jpg/1280px-thumbnail.jpg', caption: 'GBU-31 Joint Direct Attack Munition loaded in a B-2 Spirit \u2014 precision guidance kit for bunker targeting. CIA penetration enabled location of Khamenei\'s underground bunker.', source: 'USAF / Wikimedia Commons (public domain)' },
  ],
  'ir-gcc': [
    { label: 'Shahed-136 Kamikaze Drone', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/0/09/Shahed_136_rendering.png/1280px-Shahed_136_rendering.png', caption: 'Shahed-136 loitering munition \u2014 one of 541 drones in the 708-munition barrage. ~$20,000 each vs. $4M for a Patriot PAC-3 interceptor.', source: 'Wikimedia Commons (public domain)' },
    { label: 'Patriot PAC-3 Intercept', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/1/18/74th_Patriot_Regiment_missile_launch.jpg/1280px-74th_Patriot_Regiment_missile_launch.jpg', caption: 'Patriot PAC-3 missile intercept. The layered GCC + US defense architecture intercepted all 708 munitions.', source: 'US Army / Wikimedia Commons (public domain)' },
  ],
  'scs-carrier': [
    { label: 'PLAN Shandong (CV-17) \u2014 Type 001A Carrier', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/4/4d/Chinese_carrier_Liaoning_CV-16_-_Transferred_to_People%27s_Liberation_Army_Navy.jpg/1280px-Chinese_carrier_Liaoning_CV-16_-_Transferred_to_People%27s_Liberation_Army_Navy.jpg', caption: 'PLA Navy carrier in South China Sea operations.', source: 'Wikimedia Commons (public domain)' },
    { label: 'Fiery Cross Reef \u2014 PLAN Artificial Island Base', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/b/b5/Fiery_Cross_Reef_CSIS_2015.jpg/1280px-Fiery_Cross_Reef_CSIS_2015.jpg', caption: 'Fiery Cross Reef artificial island \u2014 3,000m runway, hardened aircraft shelters, SAM/CDCM batteries.', source: 'CSIS AMTI / Planet Labs satellite imagery' },
  ],
  'scs-scarborough': [
    { label: 'China Coast Guard (CCG) Vessel', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/1/1a/China_coast_guard_vessel.jpg/1280px-China_coast_guard_vessel.jpg', caption: 'China Coast Guard vessel \u2014 primary gray-zone coercion tool.', source: 'Wikimedia Commons (public domain)' },
  ],
  'scs-second-thomas': [
    { label: 'BRP Sierra Madre \u2014 Philippine Military Outpost', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/5/5f/BRP_Sierra_Madre_%28AT-43%29.jpg/1280px-BRP_Sierra_Madre_%28AT-43%29.jpg', caption: 'BRP Sierra Madre (AT-43) \u2014 a deliberately grounded WWII-era LST serving as the Philippines\' military outpost on Second Thomas Shoal.', source: 'Philippine Navy / Wikimedia Commons (public domain)' },
  ],
  'scs-fonops': [
    { label: 'USS Arleigh Burke DDG \u2014 FONOP Platform', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/8/88/USS_Arleigh_Burke_%28DDG-51%29.jpg/1200px-USS_Arleigh_Burke_%28DDG-51%29.jpg', caption: 'Arleigh Burke-class guided-missile destroyer \u2014 the primary US Navy platform for SCS FONOP operations.', source: 'US Navy / Wikimedia Commons (public domain)' },
  ],
  'scs-island-build': [
    { label: 'Mischief Reef \u2014 CSIS AMTI Satellite (2025)', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/b/b5/Fiery_Cross_Reef_CSIS_2015.jpg/1280px-Fiery_Cross_Reef_CSIS_2015.jpg', caption: 'PLA artificial island base \u2014 Mischief Reef, 250km from Palawan, Philippine EEZ.', source: 'CSIS AMTI / Planet Labs (public satellite imagery)' },
  ],
  'scs-taiwan-strait': [
    { label: 'H-6K Nuclear-Capable Bomber \u2014 PLAAF', url: 'https://upload.wikimedia.org/wikipedia/commons/thumb/2/22/H-6K_bomber.jpg/1280px-H-6K_bomber.jpg', caption: 'PLAAF H-6K Xian bomber \u2014 nuclear-capable platform in the 103-aircraft ADIZ incursion.', source: 'Wikimedia Commons (public domain)' },
  ],
};
