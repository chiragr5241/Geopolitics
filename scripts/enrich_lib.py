#!/usr/bin/env python3
"""
Shared enrichment helpers for the two-tier pipeline.

Two tiers of enrichment now live in data/spectator_enriched.csv, distinguished
by the `tier` column:

  base  — written deterministically by base_enrich.py with NO network calls.
          Every raw tweet gets a base row, so the raw->enriched backlog can
          never accumulate (this is what used to spiral for days). Base rows
          have best-effort category/countries/severity from keyword rules,
          source_count=0, and empty context/implications.

  deep  — an agent (the scheduled task) upgrades a *bounded batch* of the most
          significant base rows with WebSearch corroboration, context, and
          implications, then applies them via apply_deep_enrichment.py, which
          flips the row's tier to `deep`.

This module holds the pieces both scripts share: noise detection, deterministic
classification, ISO-2 country extraction (incl. flag emoji), and read/write of
the enriched CSV keyed by tweet `id`.

Nothing here calls the network or an LLM — it is pure, deterministic Python.
"""

import csv
import os
import re
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENRICHED_CSV = os.path.join(ROOT, 'data', 'spectator_enriched.csv')
STORY_IMAGES_CSV = os.path.join(ROOT, 'data', 'story_images.csv')

# Canonical column order for spectator_enriched.csv. `tier` is appended last so
# name-based (DictReader) consumers — sync_enriched_to_intel.py,
# enrich_status.py — are unaffected, and legacy rows simply lack it.
ENRICHED_COLUMNS = [
    'id', 'tweet_id', 'pub_date', 'original_text', 'category', 'subcategory',
    'countries', 'entities_people', 'entities_orgs', 'entities_weapons',
    'entities_locations', 'lat', 'lng', 'sentiment', 'severity', 'is_breaking',
    'summary', 'context', 'implications', 'confirmation_status', 'source_count',
    'sources_json', 'images', 'source', 'source_url', 'perspective',
    'enriched_at', 'tier',
]

# Provenance of an enriched row. Spectator tweets are the historical default;
# wire items (pull_wires.py) carry their outlet name + article URL + the
# reporting-country perspective so the feed can attribute and cross-reference.
DEFAULT_SOURCE = 'spectator'

# Rows written before the two-tier split were all agent-researched, so a
# missing `tier` means the row is already deep.
LEGACY_TIER = 'deep'

NOISE_SUBCATEGORY = 'noise'


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')


# --------------------------------------------------------------------------- #
# Country extraction
# --------------------------------------------------------------------------- #

def _flags_to_iso(text):
    """Every 🇺🇸-style flag is two Unicode regional-indicator symbols
    (U+1F1E6..U+1F1FF = A..Z). Decode consecutive pairs into ISO-2 codes."""
    letters = []
    for ch in text:
        cp = ord(ch)
        if 0x1F1E6 <= cp <= 0x1F1FF:
            letters.append(chr(cp - 0x1F1E6 + ord('A')))
        else:
            letters.append(' ')
    joined = ''.join(letters)
    return re.findall(r'([A-Z])([A-Z])', joined)


# Common geopolitical names → ISO-2, for tweets that spell countries out
# instead of using a flag. Conservative: only unambiguous names.
NAME_TO_ISO = {
    'united states': 'US', 'u.s.': 'US', 'us military': 'US', 'america': 'US',
    'washington': 'US', 'russia': 'RU', 'russian': 'RU', 'moscow': 'RU',
    'ukraine': 'UA', 'ukrainian': 'UA', 'kyiv': 'UA', 'kiev': 'UA',
    'israel': 'IL', 'israeli': 'IL', 'tel aviv': 'IL', 'idf': 'IL',
    'iran': 'IR', 'iranian': 'IR', 'tehran': 'IR', 'irgc': 'IR',
    'china': 'CN', 'chinese': 'CN', 'beijing': 'CN', 'taiwan': 'TW',
    'north korea': 'KP', 'south korea': 'KR', 'japan': 'JP', 'india': 'IN',
    'pakistan': 'PK', 'gaza': 'PS', 'palestin': 'PS', 'lebanon': 'LB',
    'hezbollah': 'LB', 'syria': 'SY', 'iraq': 'IQ', 'yemen': 'YE',
    'houthi': 'YE', 'saudi': 'SA', 'qatar': 'QA', 'kuwait': 'KW',
    'bahrain': 'BH', 'uae': 'AE', 'emirates': 'AE', 'turkey': 'TR',
    'turkiye': 'TR', 'egypt': 'EG', 'venezuela': 'VE', 'maduro': 'VE',
    'canada': 'CA', 'mexico': 'MX', 'germany': 'DE', 'france': 'FR',
    'united kingdom': 'GB', 'britain': 'GB', 'england': 'GB', 'poland': 'PL',
    'nato': 'NATO', 'european union': 'EU', 'brussels': 'EU',
}


def extract_countries(text):
    """Return a semicolon-joined, de-duplicated ISO-2 country string."""
    found = []
    for a, b in _flags_to_iso(text):
        code = a + b
        if code not in found:
            found.append(code)
    low = text.lower()
    for name, iso in NAME_TO_ISO.items():
        if name in low and iso not in found:
            found.append(iso)
    return ';'.join(found)


# --------------------------------------------------------------------------- #
# Noise detection (solution C — keep junk out of the deep-research budget)
# --------------------------------------------------------------------------- #

_NOISE_PATTERNS = [
    r'\bworld cup\b', r'\bpremier league\b', r'\bchampions league\b',
    r'\ballianz\b', r'\bman of the match\b', r'\bfull[- ]time\b',
    r'\bkick[- ]?off\b', r'\bequalis|equalize', r'\bgoal!?\b', r'\bhat[- ]trick',
    r'\bmessi\b', r'\bronaldo\b', r'\bsuper bowl\b', r'\bnba\b', r'\bnfl\b',
    r'\bolympics?\b', r'\bgrand slam\b', r'\bwimbledon\b', r'\bformula 1\b|\bf1 gp\b',
    r'\bbeat .* to (advance|reach|win)\b', r'\badvance to the .* final\b',
    r'\bgo \d+[-–]\d+ (up|down|ahead)\b', r'\binjury time\b', r'\bextra time\b',
    r'\b\d+(st|nd|rd|th) minute\b', r'\bequaliser?\b', r'\bpenalty shoot',
    r'\bbitcoin\b|\bethereum\b|\b\$?btc\b|\bcrypto(currency)?\b.*(price|surge|rally)',
    r'\bhappy birthday\b', r'\bmerry christmas\b', r'\bhappy new year\b',
    r'\bweather forecast\b', r'\bbox office\b', r'\bgrammy\b|\boscars?\b',
]
_NOISE_RE = re.compile('|'.join(_NOISE_PATTERNS), re.I)


def is_noise(text):
    return bool(_NOISE_RE.search(text or ''))


# Wire URL sections that are genuinely NOT geopolitics — sport, entertainment,
# lifestyle, quizzes, galleries. Deliberately NARROW: documentaries, explainers,
# long-form, features, opinion and video are the *deep* content the tracker is
# for (Johnny-Harris "understand how the world works"), so they stay in the feed.
_WIRE_LOWVALUE_RE = re.compile(
    r'/(sport|sports|entertainment|lifestyle|celebrity|celebrities|'
    r'quiz|quizzes|gallery|galleries|arts?-and-culture|food|travel|gaming)/',
    re.I,
)


def is_wire_low_value(url):
    """True only for clearly non-news wire URLs (sport/entertainment/etc.)."""
    return bool(_WIRE_LOWVALUE_RE.search(url or ''))


# --------------------------------------------------------------------------- #
# Deterministic classification
# --------------------------------------------------------------------------- #

# (compiled regex, category, default subcategory). First match wins; order
# matters (most specific / most severe first).
_CATEGORY_RULES = [
    (re.compile(r'\bnuclear\b|\buranium\b|\benrichment\b|\bIAEA\b|\bwarhead', re.I), 'nuclear', 'nuclear'),
    (re.compile(r'\b(isis|isil|al[- ]qaeda|terror|suicide bomb|car bomb)\b', re.I), 'terrorism', 'attack'),
    (re.compile(r'\b(airstrike|air strike|missile|drone strike|shelling|bombard|artillery|troops|offensive|frontline|killed in|air defen[cs]e|warplane|fighter jet)\b', re.I), 'military', 'strike'),
    (re.compile(r'\bstrikes?\b|\bstruck\b|\battack(ed|s)?\b|\bexplosion', re.I), 'military', 'strike'),
    (re.compile(r'\bcyber ?attack\b|\bhack(ed|ing)?\b|\bransomware\b|\bdata breach\b', re.I), 'cyber', 'cyberattack'),
    (re.compile(r'\bsanction', re.I), 'economic', 'sanctions'),
    (re.compile(r'\btariff', re.I), 'trade', 'tariffs'),
    (re.compile(r'\b(trade deal|export ban|import|gdp|inflation|interest rate|central bank|oil price|opec)\b', re.I), 'economic', ''),
    (re.compile(r'\b(pipeline|refinery|power plant|power grid|desalination|oil field|gas field|energy)\b', re.I), 'energy', ''),
    (re.compile(r'\b(ceasefire|peace (deal|talks|plan)|summit|negotiat|diplomat|ambassador|foreign minister|treaty|accord)\b', re.I), 'diplomatic', ''),
    (re.compile(r'\b(charged|indict|arrest|court|trial|prosecut|corruption|money laundering|bribery)\b', re.I), 'legal', 'charge'),
    (re.compile(r'\b(refugee|famine|humanitarian|civilian casualt|aid convoy|displaced)\b', re.I), 'humanitarian', ''),
    (re.compile(r'\b(spy|espionage|intelligence agency|surveillance|defector)\b', re.I), 'intelligence', ''),
    (re.compile(r'\b(election|president|prime minister|parliament|resign|coup|referendum|impeach|cabinet|minister|sworn in)\b', re.I), 'political', ''),
    (re.compile(r'\b(shooting|stabbing|riot|protest|earthquake|flood|wildfire|hurricane)\b', re.I), 'social', ''),
]

_SUBCATEGORY_RULES = [
    (re.compile(r'\bairstrike|air strike|warplane|fighter jet\b', re.I), 'airstrike'),
    (re.compile(r'\bmissile', re.I), 'missile_strike'),
    (re.compile(r'\bdrone', re.I), 'drone_strike'),
    (re.compile(r'\bceasefire', re.I), 'ceasefire'),
    (re.compile(r'\btariff', re.I), 'tariffs'),
    (re.compile(r'\bsanction', re.I), 'sanctions'),
    (re.compile(r'\bcorruption|money laundering|bribery', re.I), 'corruption'),
    (re.compile(r'\belection|vote|primary', re.I), 'election'),
    (re.compile(r'\bprotest|demonstration', re.I), 'protest'),
    (re.compile(r'\bshooting', re.I), 'mass_shooting'),
]

_HIGH_SEV_RE = re.compile(r'\b(killed|dead|deaths?|dozens|casualties|strikes?|struck|missile|explosion|invasion|attack)\b', re.I)
_MASS_CASUALTY_RE = re.compile(r'\b(dozens|hundreds|thousands|mass|massacre|scores of)\b', re.I)


def classify(text):
    """Return a dict of deterministic base-tier classification fields."""
    text = text or ''
    breaking = bool(re.match(r'\s*BREAKING\b', text, re.I)) or 'BREAKING:' in text

    if is_noise(text):
        return {
            'category': 'social', 'subcategory': NOISE_SUBCATEGORY,
            'countries': extract_countries(text), 'sentiment': 'neutral',
            'severity': 1, 'is_breaking': 'TRUE' if breaking else 'FALSE',
        }

    category, subcategory = 'political', ''
    for rx, cat, sub in _CATEGORY_RULES:
        if rx.search(text):
            category, subcategory = cat, sub
            break

    for rx, sub in _SUBCATEGORY_RULES:
        if rx.search(text):
            subcategory = sub
            break

    severity = 2
    if category in ('military', 'nuclear', 'terrorism') and _HIGH_SEV_RE.search(text):
        severity = 4
    elif category in ('economic', 'trade', 'diplomatic', 'legal', 'energy'):
        severity = 3
    if breaking:
        severity = min(5, severity + 1)
    if _MASS_CASUALTY_RE.search(text) and severity >= 4:
        severity = 5

    escalatory = category in ('military', 'nuclear', 'terrorism', 'cyber')
    sentiment = 'escalatory' if escalatory else 'neutral'
    if re.search(r'\bceasefire|peace deal|de[- ]escalat|withdraw', text, re.I):
        sentiment = 'de-escalatory'

    return {
        'category': category, 'subcategory': subcategory,
        'countries': extract_countries(text), 'sentiment': sentiment,
        'severity': severity, 'is_breaking': 'TRUE' if breaking else 'FALSE',
    }


# --------------------------------------------------------------------------- #
# Deterministic image matching (mirrors findImage() in js/home.js /
# js/tracker.js — first story_images.csv row whose semicolon-split keyword is a
# substring of the item text; rows are ordered most-specific first).
# --------------------------------------------------------------------------- #

_STORY_IMAGES = None


def load_story_images():
    """Return the story_images.csv rows in priority order (cached). Each row is
    {keywords,label,url,caption,credit}."""
    global _STORY_IMAGES
    if _STORY_IMAGES is None:
        rows = []
        if os.path.exists(STORY_IMAGES_CSV):
            with open(STORY_IMAGES_CSV, newline='', encoding='utf-8') as f:
                rows = list(csv.DictReader(f))
        _STORY_IMAGES = rows
    return _STORY_IMAGES


def match_image(text, countries=''):
    """Return the URL of the first keyword-matching hero image, or '' if none.

    Deterministic and offline. Country-gated: a row that declares `countries`
    only matches when the item shares at least one of them. This stops a generic
    keyword from cross-assigning a wrong-country photo — e.g. an Indian election
    story matching the US "voting" image, or a non-US airstrike grabbing the B-2.
    Rows with no `countries` (generic munitions, oil, stadiums) match anything;
    when the item itself has no countries we can't gate, so keyword-only applies.
    """
    hay = (text or '').lower()
    if not hay:
        return ''
    item_cs = {c.strip().upper() for c in (countries or '').replace(',', ';').split(';') if c.strip()}
    for row in load_story_images():
        row_cs = {c.strip().upper() for c in (row.get('countries') or '').split(';') if c.strip()}
        # Gate: if both the row and the item name countries and they don't
        # overlap, this image is the wrong place — skip it.
        if row_cs and item_cs and not (row_cs & item_cs):
            continue
        for kw in (row.get('keywords') or '').lower().split(';'):
            kw = kw.strip()
            if kw and kw in hay:
                return row.get('url', '') or ''
    return ''


def base_record(raw_row):
    """Build a full base-tier enriched row (dict) from a raw tweet row."""
    text = raw_row.get('text', '') or ''
    cls = classify(text)
    summary = ' '.join(text.split())
    if len(summary) > 140:
        summary = summary[:137].rstrip() + '...'
    return {
        'id': raw_row.get('id', ''),
        'tweet_id': raw_row.get('tweet_id', ''),
        'pub_date': raw_row.get('pub_date', ''),
        'original_text': text,
        'category': cls['category'],
        'subcategory': cls['subcategory'],
        'countries': cls['countries'],
        'entities_people': '',
        'entities_orgs': '',
        'entities_weapons': '',
        'entities_locations': '',
        'lat': '',
        'lng': '',
        'sentiment': cls['sentiment'],
        'severity': str(cls['severity']),
        'is_breaking': cls['is_breaking'],
        'summary': summary,
        'context': '',
        'implications': '',
        'confirmation_status': 'unconfirmed',
        'source_count': '0',
        'sources_json': '[]',
        'images': match_image(text, cls['countries']),
        'source': DEFAULT_SOURCE,
        'source_url': '',
        'perspective': '',
        'enriched_at': now_iso(),
        'tier': 'base',
    }


def wire_base_record(wire_row):
    """Build a base-tier enriched row from a wire_raw.csv item (pull_wires.py).

    Wire items already carry an outlet, an article URL, a reporting-country
    perspective, and often a native image — all richer than a bare tweet, so we
    thread them straight through. The headline+lede feed the same deterministic
    classifier tweets use, and the native image beats the keyword match."""
    title = (wire_row.get('title') or '').strip()
    lede = (wire_row.get('lede') or '').strip()
    text = title if not lede else f'{title} — {lede}'
    cls = classify(text)
    # Editorial/video/long-form sections → mark noise so the feed hides them.
    if is_wire_low_value(wire_row.get('url', '')):
        cls = dict(cls, category='social', subcategory=NOISE_SUBCATEGORY, severity=1)
    summary = ' '.join(title.split())
    if len(summary) > 140:
        summary = summary[:137].rstrip() + '...'
    native = (wire_row.get('image') or '').strip()
    return {
        'id': wire_row.get('id', ''),
        'tweet_id': '',
        'pub_date': wire_row.get('pub_date', ''),
        'original_text': text,
        'category': cls['category'],
        'subcategory': cls['subcategory'],
        'countries': cls['countries'],
        'entities_people': '',
        'entities_orgs': '',
        'entities_weapons': '',
        'entities_locations': '',
        'lat': '',
        'lng': '',
        'sentiment': cls['sentiment'],
        'severity': str(cls['severity']),
        'is_breaking': cls['is_breaking'],
        'summary': summary,
        'context': '',
        'implications': '',
        'confirmation_status': 'unconfirmed',
        'source_count': '1',
        'sources_json': '[]',
        'images': native or match_image(text, cls['countries']),
        'source': wire_row.get('source', '') or 'wire',
        'source_url': wire_row.get('url', ''),
        'perspective': wire_row.get('perspective', ''),
        'enriched_at': now_iso(),
        'tier': 'base',
    }


# --------------------------------------------------------------------------- #
# Enriched CSV read / write (keyed by tweet id)
# --------------------------------------------------------------------------- #

def load_enriched():
    """Return (rows, by_id). Each row is normalized to ENRICHED_COLUMNS with a
    `tier` value (legacy rows -> 'deep')."""
    rows = []
    if os.path.exists(ENRICHED_CSV):
        with open(ENRICHED_CSV, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                norm = {c: (r.get(c) or '') for c in ENRICHED_COLUMNS}
                if not norm['tier']:
                    norm['tier'] = LEGACY_TIER
                rows.append(norm)
    by_id = {r['id']: r for r in rows}
    return rows, by_id


def write_enriched(rows):
    """Atomically rewrite the enriched CSV in canonical column order."""
    tmp = ENRICHED_CSV + '.tmp'
    with open(tmp, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=ENRICHED_COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, '') for c in ENRICHED_COLUMNS})
    os.replace(tmp, ENRICHED_CSV)


def load_raw():
    raw_path = os.path.join(ROOT, 'data', 'raw_data', 'spectator_raw.csv')
    if not os.path.exists(raw_path):
        return []
    with open(raw_path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def load_wire_raw():
    """Rows from data/raw_data/wire_raw.csv (pull_wires.py), or [] if absent."""
    raw_path = os.path.join(ROOT, 'data', 'raw_data', 'wire_raw.csv')
    if not os.path.exists(raw_path):
        return []
    with open(raw_path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))
