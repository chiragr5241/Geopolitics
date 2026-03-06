'use strict';

/* =========================================================
   GLOBAL OPERATIONS MAP 2025–2026 — Static Configuration
   Rendering config that rarely changes: country palettes,
   SVG strike-type icons, city labels, and timeline marks.

   Data that changes frequently lives in CSV files under
   data/ and is loaded via DataLayer (js/data.js):
     data/incidents.csv   — incident rows
     data/operations.csv  — operation metadata + colors
     data/imagery.csv     — per-incident imagery

   To add a new operation: edit data/operations.csv.
   To add a new incident:  edit data/incidents.csv.
   To add imagery:         edit data/imagery.csv.
   No JS changes needed.
   ========================================================= */

// ── Data Source Paths (change here to point at a new backend) ──

var DATA_SOURCES = {
  incidents:  'data/incidents.csv',
  operations: 'data/operations.csv',
  imagery:    'data/imagery.csv',
};

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
  US: { label: '\u{1F1FA}\u{1F1F8} US',     color: '#1565c0', bg: 'rgba(21,101,192,.12)',  border: 'rgba(21,101,192,.45)'  },
  IL: { label: '\u{1F1EE}\u{1F1F1} Israel', color: '#6a1b9a', bg: 'rgba(106,27,154,.12)', border: 'rgba(106,27,154,.45)' },
  IR: { label: '\u{1F1EE}\u{1F1F7} Iran',   color: '#00695c', bg: 'rgba(0,105,92,.12)',   border: 'rgba(0,105,92,.45)'   },
  CN: { label: '\u{1F1E8}\u{1F1F3} China',  color: '#c62828', bg: 'rgba(198,40,40,.12)',  border: 'rgba(198,40,40,.45)'  },
  VE: { label: '\u{1F1FB}\u{1F1EA} Venez.', color: '#7b5800', bg: 'rgba(123,88,0,.12)',   border: 'rgba(123,88,0,.45)'   },
  YE: { label: '\u{1F1FE}\u{1F1EA} Houthi', color: '#ad1457', bg: 'rgba(173,20,87,.12)',  border: 'rgba(173,20,87,.45)'  },
  PH: { label: '\u{1F1F5}\u{1F1ED} PHL',    color: '#00838f', bg: 'rgba(0,131,143,.12)',  border: 'rgba(0,131,143,.45)'  },
  UA: { label: '\u{1F1FA}\u{1F1E6} Ukraine', color: '#e65100', bg: 'rgba(230,81,0,.12)',  border: 'rgba(230,81,0,.45)'  },
  RU: { label: '\u{1F1F7}\u{1F1FA} Russia', color: '#546e7a', bg: 'rgba(84,110,122,.12)', border: 'rgba(84,110,122,.45)' },
  PS: { label: '\u{1F1F5}\u{1F1F8} Palest.', color: '#2e7d32', bg: 'rgba(46,125,50,.12)', border: 'rgba(46,125,50,.45)' },
  LB: { label: '\u{1F1F1}\u{1F1E7} Lebanon', color: '#5d4037', bg: 'rgba(93,64,55,.12)',  border: 'rgba(93,64,55,.45)'  },
};


// ── Strike Type SVG Icons ──

var STRIKE_TYPES = {
  bomber: {
    color: '#4caf50', bgFill: 'rgba(255,255,255,0.92)', label: 'Confirmed Airstrike',
    getSVG: function (sz, c) {
      return '<polygon points="' + sz*.5 + ',' + sz*.25 + ' ' + sz*.85 + ',' + sz*.65 + ' ' + sz*.7 + ',' + sz*.6 + ' ' + sz*.55 + ',' + sz*.72 + ' ' + sz*.45 + ',' + sz*.72 + ' ' + sz*.3 + ',' + sz*.6 + ' ' + sz*.15 + ',' + sz*.65 + '" fill="' + c + '" opacity=".95"/>';
    }
  },
  fighter: {
    color: '#4caf50', bgFill: 'rgba(255,255,255,0.92)', label: 'Confirmed Airstrike',
    getSVG: function (sz, c) {
      var cx = sz / 2;
      return '<polygon points="' + cx + ',' + sz*.2 + ' ' + (cx+sz*.04) + ',' + sz*.45 + ' ' + sz*.82 + ',' + sz*.72 + ' ' + sz*.75 + ',' + sz*.78 + ' ' + cx + ',' + sz*.58 + ' ' + sz*.25 + ',' + sz*.78 + ' ' + sz*.18 + ',' + sz*.72 + ' ' + (cx-sz*.04) + ',' + sz*.45 + '" fill="' + c + '" opacity=".95"/>'
           + '<rect x="' + (cx-sz*.02) + '" y="' + sz*.18 + '" width="' + sz*.04 + '" height="' + sz*.4 + '" rx="1" fill="' + c + '"/>';
    }
  },
  missile: {
    color: '#2196f3', bgFill: 'rgba(255,255,255,0.92)', label: 'Reported Strike',
    getSVG: function (sz, c) {
      var cx = sz / 2;
      return '<rect x="' + (cx-sz*.07) + '" y="' + sz*.22 + '" width="' + sz*.14 + '" height="' + sz*.45 + '" rx="' + sz*.06 + '" fill="' + c + '" opacity=".9"/>'
           + '<polygon points="' + cx + ',' + sz*.16 + ' ' + (cx+sz*.07) + ',' + sz*.3 + ' ' + (cx-sz*.07) + ',' + sz*.3 + '" fill="' + c + '"/>'
           + '<polygon points="' + (cx-sz*.07) + ',' + sz*.56 + ' ' + (cx-sz*.2) + ',' + sz*.72 + ' ' + (cx-sz*.07) + ',' + sz*.67 + '" fill="' + c + '" opacity=".8"/>'
           + '<polygon points="' + (cx+sz*.07) + ',' + sz*.56 + ' ' + (cx+sz*.2) + ',' + sz*.72 + ' ' + (cx+sz*.07) + ',' + sz*.67 + '" fill="' + c + '" opacity=".8"/>';
    }
  },
  naval: {
    color: '#9c27b0', bgFill: 'rgba(255,255,255,0.92)', label: 'Naval Operation',
    getSVG: function (sz, c) {
      var cx = sz / 2;
      return '<circle cx="' + cx + '" cy="' + sz*.32 + '" r="' + sz*.08 + '" fill="none" stroke="' + c + '" stroke-width="' + sz*.07 + '"/>'
           + '<line x1="' + cx + '" y1="' + sz*.4 + '" x2="' + cx + '" y2="' + sz*.76 + '" stroke="' + c + '" stroke-width="' + sz*.07 + '"/>'
           + '<line x1="' + sz*.25 + '" y1="' + sz*.5 + '" x2="' + sz*.75 + '" y2="' + sz*.5 + '" stroke="' + c + '" stroke-width="' + sz*.07 + '"/>'
           + '<path d="M' + sz*.25 + ',' + sz*.76 + ' Q' + cx + ',' + sz*.88 + ' ' + sz*.75 + ',' + sz*.76 + '" fill="none" stroke="' + c + '" stroke-width="' + sz*.07 + '"/>';
    }
  },
  sof: {
    color: '#9c27b0', bgFill: 'rgba(255,255,255,0.92)', label: 'Special Operation',
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
    color: '#e6a800', bgFill: 'rgba(255,255,255,0.92)', label: 'Strike w/ Footage',
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
    color: '#e07b00', bgFill: 'rgba(255,255,255,0.92)', label: 'Retaliation / Proxy',
    getSVG: function (sz, c) {
      return '<polygon points="' + sz*.55 + ',' + sz*.18 + ' ' + sz*.3 + ',' + sz*.52 + ' ' + sz*.47 + ',' + sz*.52 + ' ' + sz*.42 + ',' + sz*.82 + ' ' + sz*.68 + ',' + sz*.46 + ' ' + sz*.52 + ',' + sz*.46 + '" fill="' + c + '" opacity=".95"/>';
    }
  },
  intel: {
    color: '#546e7a', bgFill: 'rgba(255,255,255,0.92)', label: 'Intel / Buildup',
    getSVG: function (sz, c) {
      var cx = sz / 2;
      return '<rect x="' + sz*.22 + '" y="' + sz*.28 + '" width="' + sz*.56 + '" height="' + sz*.38 + '" rx="2" fill="none" stroke="' + c + '" stroke-width="' + sz*.06 + '"/>'
           + '<rect x="' + sz*.16 + '" y="' + sz*.66 + '" width="' + sz*.68 + '" height="' + sz*.1 + '" rx="1" fill="' + c + '" opacity=".7"/>'
           + '<line x1="' + (cx-sz*.07) + '" y1="' + sz*.28 + '" x2="' + (cx-sz*.07) + '" y2="' + sz*.22 + '" stroke="' + c + '" stroke-width="' + sz*.05 + '"/>'
           + '<line x1="' + (cx+sz*.07) + '" y1="' + sz*.28 + '" x2="' + (cx+sz*.07) + '" y2="' + sz*.22 + '" stroke="' + c + '" stroke-width="' + sz*.05 + '"/>';
    }
  },
  maritime: {
    color: '#007b8a', bgFill: 'rgba(255,255,255,0.92)', label: 'Maritime Coercion',
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
    color: '#007b8a', bgFill: 'rgba(255,255,255,0.92)', label: 'Island Construction',
    getSVG: function (sz, c) {
      var cx = sz / 2, cy = sz / 2;
      return '<ellipse cx="' + cx + '" cy="' + (cy+sz*.05) + '" rx="' + sz*.32 + '" ry="' + sz*.18 + '" fill="' + c + '" opacity=".5"/>'
           + '<ellipse cx="' + cx + '" cy="' + (cy+sz*.05) + '" rx="' + sz*.24 + '" ry="' + sz*.12 + '" fill="' + c + '" opacity=".8"/>'
           + '<rect x="' + (cx-sz*.1) + '" y="' + sz*.28 + '" width="' + sz*.2 + '" height="' + sz*.2 + '" rx="1" fill="' + c + '" opacity=".9"/>'
           + '<line x1="' + cx + '" y1="' + sz*.16 + '" x2="' + cx + '" y2="' + sz*.28 + '" stroke="' + c + '" stroke-width="' + sz*.06 + '"/>';
    }
  },
  nuke: {
    color: '#c62828', bgFill: 'rgba(255,255,255,0.92)', label: 'Unverified Report',
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

