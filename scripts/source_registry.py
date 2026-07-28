#!/usr/bin/env python3
"""
Source registry — every news source the pipeline is allowed to use, as an
entity with a stable id.

Before this existed, "sources" were three disconnected hardcoded things: the
RSS/GDELT tuples at the top of pull_wires.py, the "prefer Reuters, AP, BBC…"
sentence in the story-tracker routine prompt, and whatever free text an update
happened to carry in story_updates.source_name ("Reuters", "U.S. News /
Reuters", "Reuters (via Internazionale)" — three spellings of one outlet). None
of them could be turned on or off per story, and a user could not add one.

data/sources.csv is now the single list. Columns:

  source_id       stable slug, the id stories and updates refer to
  name            canonical display name
  aliases         ';'-separated alternate names/abbreviations (AP, NYT, SCMP…)
  kind            rss | gdelt | social | web
                    rss/gdelt/social = pull_wires.py / pull_spectator.py fetch it
                    web              = agent WebSearch only (no feed adapter)
  domain          primary domain — also used to resolve a URL back to a source
  feed_url        rss only
  query           gdelt only (the DOC 2.0 query string)
  perspective     the framing label the feed already shows (western-uk, russia…)
  source_country  ISO-2 (or UN) of the reporting country
  scope           wire (auto-pulled) | research (WebSearch)
  status          active | unverified | not_found | retired
                    unverified = a user typed it, the routine hasn't checked yet
                    not_found  = the routine looked and no such outlet exists
                                 → the UI highlights it for the user
                    NOTE: "the outlet exists but published nothing" is NOT a
                    status — that is normal and is reported via last_ok_at /
                    last_items, never as a failure.
  corrected_from  what the user actually typed, when we corrected a misspelling
  last_ok_at      last time this source yielded anything (any story)
  last_items      how many it yielded that time

Resolution (`resolve`) is what makes user-typed names safe: exact id/name/alias/
domain hit first, then a normalised match ("the guardian" == "Guardian"), then
fuzzy (difflib) for misspellings — "Reuter" → Reuters, "Kiyv Independant" →
Kyiv Independent — each reported with a status so callers can mark the
correction rather than silently swallow it.

Library use:
    from source_registry import load_sources, resolve, effective_for_story

CLI (from project root):
    python3 scripts/source_registry.py --list [--kind rss] [--json]
    python3 scripts/source_registry.py --resolve "Kiyv Independant"
    python3 scripts/source_registry.py --for-story st-2026...   [--json]
    python3 scripts/source_registry.py --pending                [--json]
    python3 scripts/source_registry.py --coverage [--story ID]  [--json]
    echo '[{"name":"Kyiv Post","status":"active","domain":"kyivpost.com"}]' \
        | python3 scripts/source_registry.py --upsert
    cat verdicts.json | python3 scripts/source_registry.py --apply-verdicts
    python3 scripts/source_registry.py --record-fetch bbc-world 42
"""

import csv
import difflib
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data')
SOURCES_CSV = os.path.join(DATA_DIR, 'sources.csv')
WATCHLIST_JSON = os.path.join(DATA_DIR, 'watchlist.json')
STORY_UPDATES_CSV = os.path.join(DATA_DIR, 'story_updates.csv')

SOURCE_COLUMNS = [
    'source_id', 'name', 'aliases', 'kind', 'domain', 'feed_url', 'query',
    'perspective', 'source_country', 'scope', 'status', 'added_by', 'added_at',
    'corrected_from', 'last_ok_at', 'last_items', 'notes',
]

VALID_STATUS = {'active', 'unverified', 'not_found', 'retired'}
USABLE_STATUS = {'active', 'unverified'}   # unverified is still worth trying

# Fuzzy threshold. High enough that "Kyiv Post" never resolves to "Kyiv
# Independent", low enough to absorb a transposed letter or a dropped vowel.
FUZZY_CUTOFF = 0.84

# Words that carry no identity — dropped before comparing, so "The Guardian",
# "Guardian News" and "guardian" are one thing.
_NOISE = {'the', 'a', 'an', 'news', 'agency', 'media', 'press', 'daily',
          'online', 'network', 'group', 'com', 'org', 'net'}


def _now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def normalize(name):
    """Comparison key: lowercase, punctuation stripped, noise words dropped."""
    s = (name or '').lower()
    s = re.sub(r'https?://', ' ', s)
    s = re.sub(r'[^a-z0-9]+', ' ', s).strip()
    words = [w for w in s.split() if w and w not in _NOISE]
    return ' '.join(words) if words else s


def slugify(name):
    s = re.sub(r'[^a-z0-9]+', '-', (name or '').lower()).strip('-')
    return s[:48].strip('-') or 'source'


# ── Load / save ──────────────────────────────────────────────────────────── #

def load_sources(path=SOURCES_CSV):
    if not os.path.exists(path):
        return []
    with open(path, newline='', encoding='utf-8') as f:
        rows = [dict(r) for r in csv.DictReader(f)]
    for r in rows:
        for col in SOURCE_COLUMNS:
            r.setdefault(col, '')
    return rows


def save_sources(rows, path=SOURCES_CSV):
    tmp = path + '.tmp'
    with open(tmp, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=SOURCE_COLUMNS, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def by_id(rows=None):
    rows = load_sources() if rows is None else rows
    return {r['source_id']: r for r in rows if r.get('source_id')}


def aliases_of(row):
    return [a.strip() for a in (row.get('aliases') or '').split(';') if a.strip()]


# ── Resolution ───────────────────────────────────────────────────────────── #

class Resolution(dict):
    """dict so it JSON-dumps straight to the CLI, attributes for readability."""

    def __init__(self, status, input_name, source=None, score=1.0):
        super().__init__(
            input=input_name,
            status=status,                                  # exact|corrected|unknown
            source_id=(source or {}).get('source_id', ''),
            name=(source or {}).get('name', ''),
            source_status=(source or {}).get('status', ''),
            score=round(score, 3),
        )
        self.source = source

    @property
    def ok(self):
        return self['status'] != 'unknown'

    @property
    def corrected(self):
        return self['status'] == 'corrected'


def resolve(name, rows=None):
    """Map a free-text source name onto a registry entity.

    Returns a Resolution whose status is:
      exact      — the name (or an alias/id/domain) matched outright
      corrected  — matched after normalisation or fuzzy repair; `name` is the
                   canonical spelling and the caller SHOULD record the change
      unknown    — nothing matched; the caller must verify it exists before
                   trusting it (see the --pending flow)
    """
    rows = load_sources() if rows is None else rows
    raw = (name or '').strip()
    if not raw:
        return Resolution('unknown', raw)

    lowered = raw.lower()

    # 1. Exact: id, canonical name, alias, or domain.
    for r in rows:
        if lowered in {r['source_id'].lower(), (r['name'] or '').lower()}:
            return Resolution('exact', raw, r)
        if lowered in {a.lower() for a in aliases_of(r)}:
            return Resolution('exact', raw, r)
        dom = (r.get('domain') or '').lower()
        if dom and (lowered == dom or lowered == 'www.' + dom):
            return Resolution('exact', raw, r)

    # 2. A URL, or a name with a domain in it → match on the domain.
    host = ''
    m = re.search(r'https?://([^/\s]+)', raw, re.IGNORECASE)
    if m:
        host = m.group(1).lower().lstrip('www.')
    elif re.search(r'\b[a-z0-9-]+\.[a-z]{2,}\b', lowered):
        host = re.search(r'\b[a-z0-9.-]+\.[a-z]{2,}\b', lowered).group(0).lstrip('www.')
    if host:
        for r in rows:
            dom = (r.get('domain') or '').lower()
            if dom and (host == dom or host.endswith('.' + dom) or dom.endswith('.' + host)):
                return Resolution('corrected', raw, r, 0.95)

    # 3. Normalised match — punctuation/case/noise-word differences only.
    key = normalize(raw)
    index = {}
    for r in rows:
        for cand in [r['name'], r['source_id']] + aliases_of(r):
            k = normalize(cand)
            if k:
                index.setdefault(k, r)
    if key in index:
        return Resolution('corrected', raw, index[key], 0.98)

    # 4. Compound credit lines: "U.S. News / Reuters", "Reuters (via
    #    Internazionale)" — take the first part that resolves cleanly.
    parts = [p for p in re.split(r'\s*(?:/|\||,|\(via\b|—|–)\s*', raw) if p.strip()]
    if len(parts) > 1:
        for p in parts:
            sub = resolve(p.strip(' ()'), rows)
            if sub.ok:
                return Resolution('corrected', raw, sub.source, 0.9)

    # 5. Fuzzy — the actual misspelling case.
    if key:
        near = difflib.get_close_matches(key, list(index.keys()), n=1, cutoff=FUZZY_CUTOFF)
        if near:
            score = difflib.SequenceMatcher(None, key, near[0]).ratio()
            return Resolution('corrected', raw, index[near[0]], score)

    return Resolution('unknown', raw)


# An intel_feed row written by the GDELT adapter credits "domain (perspective)"
# — e.g. "russiaherald.com (russia)" — rather than a plain outlet name.
_GDELT_ROW_RE = re.compile(r'^(?P<domain>[a-z0-9.-]+\.[a-z]{2,})\s*\((?P<perspective>[^)]+)\)\s*$',
                           re.IGNORECASE)


def resolve_feed_source(row, rows=None):
    """Map an intel_feed row's `source` column onto a registry entity.

    The feed mixes three shapes: '' / 'spectator' for the tweet stream, a plain
    wire label ('BBC World'), and GDELT's 'domain (perspective)'. All three have
    to land on a source_id or a story's source selection can't govern them.
    """
    rows = load_sources() if rows is None else rows
    raw = (row.get('source') or '').strip()
    if not raw or raw.lower() == 'spectator':
        return resolve('Spectator Index', rows)

    m = _GDELT_ROW_RE.match(raw)
    if m:
        # Prefer the actual publisher when we know it (scmp.com, globaltimes.cn
        # are registered outlets); otherwise credit the GDELT query that
        # surfaced it, so deselecting "GDELT/RU Ukraine" actually stops those.
        pub = resolve(m.group('domain'), rows)
        if pub.ok:
            return pub
        persp = m.group('perspective').strip().lower()
        for r in rows:
            if r['kind'] == 'gdelt' and (r.get('perspective') or '').lower() == persp:
                return Resolution('corrected', raw, r, 0.9)
    return resolve(raw, rows)


def upsert(entry, rows=None):
    """Add or update one source. `entry` is a dict with at least a name (or
    source_id). Returns (row, created)."""
    rows = load_sources() if rows is None else rows
    sid = (entry.get('source_id') or '').strip()
    name = (entry.get('name') or '').strip()
    idx = {r['source_id']: i for i, r in enumerate(rows)}

    if not sid:
        # Reuse an existing entity when the name already resolves — adding
        # "AP News" must not mint a second Associated Press.
        res = resolve(name, rows)
        if res.ok:
            sid = res['source_id']
        else:
            sid = slugify(name)
            base, n = sid, 2
            while sid in idx:
                sid, n = f'{base}-{n}', n + 1

    if sid in idx:
        row = rows[idx[sid]]
        created = False
        # An alias we learned (the user's spelling, or another name for it) is
        # kept so the same input resolves exactly next time.
        extra = [a for a in [entry.get('corrected_from'), entry.get('alias')] if a]
        extra += [a.strip() for a in (entry.get('aliases') or '').split(';') if a.strip()]
        if extra:
            have = {normalize(a) for a in aliases_of(row)} | {normalize(row['name'])}
            merged = aliases_of(row) + [a for a in extra if normalize(a) not in have]
            row['aliases'] = ';'.join(merged)
        for col in ('kind', 'domain', 'feed_url', 'query', 'perspective',
                    'source_country', 'scope', 'status', 'notes'):
            if entry.get(col):
                row[col] = entry[col]
    else:
        created = True
        row = {c: '' for c in SOURCE_COLUMNS}
        row.update({
            'source_id': sid,
            'name': name or sid,
            'aliases': ';'.join(
                [a for a in [entry.get('corrected_from'), entry.get('alias')] if a] +
                [a.strip() for a in (entry.get('aliases') or '').split(';') if a.strip()]),
            'kind': entry.get('kind') or 'web',
            'domain': entry.get('domain', ''),
            'feed_url': entry.get('feed_url', ''),
            'query': entry.get('query', ''),
            'perspective': entry.get('perspective', ''),
            'source_country': entry.get('source_country', ''),
            'scope': entry.get('scope') or ('wire' if entry.get('feed_url') or entry.get('query') else 'research'),
            'status': entry.get('status') or 'unverified',
            'added_by': entry.get('added_by') or 'user',
            'added_at': entry.get('added_at') or _now_iso()[:10],
            'corrected_from': entry.get('corrected_from', ''),
            'notes': entry.get('notes', ''),
        })
        rows.append(row)

    if entry.get('status') in VALID_STATUS:
        row['status'] = entry['status']
    if entry.get('corrected_from') and not row.get('corrected_from'):
        row['corrected_from'] = entry['corrected_from']
    return row, created


def record_fetch(source_id, count, rows=None, persist=True):
    """Stamp a successful reach of a source. `count` may be 0 — a source that
    answered with no new items is healthy, and this is exactly the record that
    lets the routine say 'valid, but nothing new' instead of flagging it."""
    rows = load_sources() if rows is None else rows
    for r in rows:
        if r['source_id'] == source_id:
            r['last_ok_at'] = _now_iso()
            r['last_items'] = str(count)
            if persist:
                save_sources(rows)
            return r
    return None


# ── Per-story source selection ───────────────────────────────────────────── #
#
# A story's `sources` block is an OVERLAY on the registry, never a copy of it:
#
#   {"selected": [id…],        explicitly kept (the default is everything)
#    "excluded": [id…],        deselected on the timeline header → never used
#    "added":    [{input, source_id, status, resolved_name}…]}
#
# Absent block = every active source, which is what "all sources selected by
# default" has to mean for the ~50 stories that predate this feature.

def story_sources(story):
    s = (story or {}).get('sources')
    if not isinstance(s, dict):
        s = {}
    return {
        'selected': [x for x in (s.get('selected') or []) if x],
        'excluded': [x for x in (s.get('excluded') or []) if x],
        'added': [a for a in (s.get('added') or []) if isinstance(a, dict)],
    }


def effective_for_story(story, rows=None):
    """The sources the pipeline may use for this story, in priority order.

    Anything the user deselected is dropped — that is the whole contract of the
    timeline-header picker. Newly registered sources are INCLUDED unless
    excluded, so adding a source to the registry lights it up everywhere
    without touching 50 stories.
    """
    rows = load_sources() if rows is None else rows
    sel = story_sources(story)
    excluded = set(sel['excluded'])
    usable = [r for r in rows
              if r['status'] in USABLE_STATUS and r['source_id'] not in excluded]
    # Explicitly selected ids lead, in the user's order; the rest follow.
    order = {sid: i for i, sid in enumerate(sel['selected'])}
    usable.sort(key=lambda r: (order.get(r['source_id'], 10_000), r['name'].lower()))
    return usable


def is_allowed(story, source_name, rows=None):
    """Is an update credited to `source_name` allowed on this story?

    An UNRESOLVABLE name is allowed — we must not silently drop a real scoop
    from an outlet the registry has never heard of. Only an explicit exclusion
    blocks. Returns (allowed, resolution).
    """
    rows = load_sources() if rows is None else rows
    res = resolve(source_name, rows)
    if not res.ok:
        return True, res
    return res['source_id'] not in set(story_sources(story)['excluded']), res


def pending_for_story(story, rows=None):
    """User-typed sources on this story still needing verification: anything
    marked unverified, plus anything already known to be not_found (kept so the
    UI can keep highlighting it)."""
    rows = load_sources() if rows is None else rows
    index = by_id(rows)
    out = []
    for a in story_sources(story)['added']:
        sid = a.get('source_id') or ''
        row = index.get(sid)
        status = (row or {}).get('status', '') or a.get('status', '')
        if not row or status in ('unverified', 'not_found'):
            out.append({
                'input': a.get('input') or a.get('name') or '',
                'source_id': sid,
                'status': status or 'unverified',
                'resolved_name': (row or {}).get('name', a.get('resolved_name', '')),
            })
    return out


# ── Watchlist / coverage helpers (CLI) ───────────────────────────────────── #

def load_watchlist():
    if not os.path.exists(WATCHLIST_JSON):
        return {'stories': []}
    with open(WATCHLIST_JSON, encoding='utf-8') as f:
        return json.load(f)


def save_watchlist(doc):
    doc['updated_at'] = _now_iso()
    tmp = WATCHLIST_JSON + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, WATCHLIST_JSON)


def apply_verdicts(verdicts, dry_run=False):
    """Record the routine's findings about user-typed sources.

    This is the ONLY sanctioned way to write a source verdict back — the
    routine must never hand-edit watchlist.json. Each verdict:

      {"story_id": "st-…", "input": "<exactly what the user typed>",
       "verdict": "found" | "corrected" | "not_found",
       ...plus registry fields (name, domain, perspective, source_country)
          for found, or "source_id" for corrected}

    found      → register the outlet as active and select it on the story
    corrected  → point the entry at the existing source it really meant
    not_found  → mark the registry entry not_found so the UI highlights it

    "not_found" means NO SUCH OUTLET EXISTS. A real outlet that simply had no
    news for this story is not a verdict at all — leave it alone; the coverage
    report already says so.
    """
    rows = load_sources()
    doc = load_watchlist()
    stories = {s.get('story_id'): s for s in doc.get('stories', [])}
    report = []

    for v in verdicts:
        typed = (v.get('input') or '').strip()
        verdict = (v.get('verdict') or '').strip()
        story = stories.get(v.get('story_id'))
        if not typed or verdict not in ('found', 'corrected', 'not_found'):
            report.append(('skip', typed, f'bad verdict {verdict!r}'))
            continue

        if verdict == 'corrected':
            sid = v.get('source_id') or resolve(v.get('name') or typed, rows)['source_id']
            row = by_id(rows).get(sid)
            if not row:
                report.append(('skip', typed, f'no such source_id {sid!r}'))
                continue
            upsert({'source_id': sid, 'corrected_from': typed}, rows)
            status, name = 'corrected', row['name']
        elif verdict == 'found':
            row, _ = upsert({
                'name': v.get('name') or typed,
                'domain': v.get('domain', ''),
                'perspective': v.get('perspective', ''),
                'source_country': v.get('source_country', ''),
                'kind': v.get('kind') or 'web',
                'feed_url': v.get('feed_url', ''),
                'scope': v.get('scope') or ('wire' if v.get('feed_url') else 'research'),
                'status': 'active',
                'corrected_from': typed if (v.get('name') and v['name'] != typed) else '',
                'notes': v.get('notes', ''),
            }, rows)
            sid, name = row['source_id'], row['name']
            status = 'corrected' if name != typed else 'ok'
        else:                                   # not_found
            row, _ = upsert({'name': typed, 'status': 'not_found',
                             'notes': v.get('notes') or 'Verified: no such outlet found'}, rows)
            sid, name, status = row['source_id'], row['name'], 'not_found'

        report.append((verdict, typed, name))

        # Mirror the verdict onto the story that introduced the name, so the
        # picker stops flagging a resolved one and keeps flagging a bad one.
        if story is None:
            continue
        sel = story.setdefault('sources', {'selected': [], 'excluded': [], 'added': []})
        sel.setdefault('selected', [])
        sel.setdefault('excluded', [])
        for a in sel.setdefault('added', []):
            if (a.get('input') or '').strip().lower() == typed.lower():
                a['source_id'] = sid
                a['status'] = status
                a['resolved_name'] = name
        if verdict != 'not_found':
            if sid in sel['excluded']:
                sel['excluded'].remove(sid)
            if sid not in sel['selected']:
                sel['selected'].append(sid)

    for verdict, typed, name in report:
        if verdict == 'not_found':
            print(f'  NOT FOUND  {typed!r} — flagged for the user')
        elif verdict == 'skip':
            print(f'  skipped    {typed!r}: {name}')
        elif name != typed:
            print(f'  corrected  {typed!r} -> {name!r}')
        else:
            print(f'  registered {name!r}')

    if dry_run:
        print('Dry run — nothing written.')
        return report
    save_sources(rows)
    save_watchlist(doc)
    print(f'Applied {len(report)} verdict(s) to sources.csv and watchlist.json.')
    return report


def load_updates():
    if not os.path.exists(STORY_UPDATES_CSV):
        return []
    with open(STORY_UPDATES_CSV, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def coverage(story_id=None, rows=None):
    """Per story × source: how many updates that source has actually produced.

    This is the 'valid source, no news' signal — a source with 0 here is not
    broken, it just hasn't had anything for this story.
    """
    rows = load_sources() if rows is None else rows
    updates = load_updates()
    stories = load_watchlist().get('stories', [])
    if story_id:
        stories = [s for s in stories if s.get('story_id') == story_id]

    counts = {}
    for u in updates:
        sid = u.get('source_id') or ''
        if not sid:
            r = resolve(u.get('source_name', ''), rows)
            sid = r['source_id'] or ('?' + (u.get('source_name') or 'unknown'))
        counts.setdefault(u['story_id'], {})
        counts[u['story_id']][sid] = counts[u['story_id']].get(sid, 0) + 1

    out = []
    for s in stories:
        sid = s.get('story_id')
        per = counts.get(sid, {})
        eff = effective_for_story(s, rows)
        out.append({
            'story_id': sid,
            'title': s.get('title', ''),
            'sources': [{
                'source_id': r['source_id'],
                'name': r['name'],
                'kind': r['kind'],
                'status': r['status'],
                'updates': per.get(r['source_id'], 0),
            } for r in eff],
            'excluded': story_sources(s)['excluded'],
            'pending': pending_for_story(s, rows),
        })
    return out


# ── CLI ──────────────────────────────────────────────────────────────────── #

def _arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    args = sys.argv[1:]
    as_json = '--json' in args
    rows = load_sources()

    if not args or '--help' in args or '-h' in args:
        print(__doc__)
        return 0

    if '--list' in args:
        kind = _arg('--kind')
        sel = [r for r in rows if not kind or r['kind'] == kind]
        if as_json:
            print(json.dumps(sel, indent=2))
        else:
            print(f'{len(sel)} sources' + (f' (kind={kind})' if kind else ''))
            for r in sel:
                flag = '' if r['status'] == 'active' else f"  [{r['status']}]"
                print(f"  {r['source_id']:22s} {r['name']:28s} {r['kind']:7s} {r['scope']:9s}{flag}")
        return 0

    if '--resolve' in args:
        names = [a for a in args[args.index('--resolve') + 1:] if not a.startswith('--')]
        if not names and not sys.stdin.isatty():
            payload = json.loads(sys.stdin.read() or '[]')
            names = payload if isinstance(payload, list) else [payload]
        results = [resolve(n if isinstance(n, str) else n.get('name', ''), rows) for n in names]
        if as_json:
            print(json.dumps(results, indent=2))
        else:
            for r in results:
                if r['status'] == 'unknown':
                    print(f"  {r['input']!r} → UNKNOWN (verify it exists before use)")
                elif r['status'] == 'corrected':
                    print(f"  {r['input']!r} → {r['name']} ({r['source_id']})  CORRECTED  score={r['score']}")
                else:
                    print(f"  {r['input']!r} → {r['name']} ({r['source_id']})")
        return 0

    if '--for-story' in args:
        sid = _arg('--for-story')
        story = next((s for s in load_watchlist().get('stories', [])
                      if s.get('story_id') == sid), None)
        if story is None:
            print(f'No such story: {sid}', file=sys.stderr)
            return 1
        eff = effective_for_story(story, rows)
        if as_json:
            print(json.dumps(eff, indent=2))
        else:
            excl = story_sources(story)['excluded']
            print(f"{story.get('title','')}  — {len(eff)} sources in use")
            for r in eff:
                print(f"  {r['source_id']:22s} {r['name']:28s} {r['kind']:7s} {r['scope']}")
            if excl:
                print(f"  excluded by the user ({len(excl)}): {', '.join(excl)}")
        return 0

    if '--pending' in args:
        out = []
        for s in load_watchlist().get('stories', []):
            p = pending_for_story(s, rows)
            if p:
                out.append({'story_id': s['story_id'], 'title': s.get('title', ''), 'pending': p})
        # Registry-level unverified entries not attached to any story.
        loose = [r for r in rows if r['status'] == 'unverified']
        if as_json:
            print(json.dumps({'stories': out, 'unverified_sources': loose}, indent=2))
        else:
            if not out and not loose:
                print('No user-added sources awaiting verification.')
            for o in out:
                print(f"{o['story_id']}  {o['title'][:60]}")
                for p in o['pending']:
                    print(f"    {p['input']!r}  status={p['status']}")
            if loose:
                print(f"\nRegistry entries still unverified: "
                      f"{', '.join(r['source_id'] for r in loose)}")
        return 0

    if '--coverage' in args:
        out = coverage(_arg('--story'), rows)
        if as_json:
            print(json.dumps(out, indent=2))
        else:
            for o in out:
                silent = [s for s in o['sources'] if not s['updates']]
                used = [s for s in o['sources'] if s['updates']]
                print(f"{o['story_id']}  {o['title'][:60]}")
                print(f"    produced news: " + (', '.join(f"{s['name']} ({s['updates']})" for s in used) or 'none'))
                print(f"    no news yet ({len(silent)}): " +
                      ', '.join(s['name'] for s in silent[:8]) + ('…' if len(silent) > 8 else ''))
                for p in o['pending']:
                    tag = 'NOT FOUND' if p['status'] == 'not_found' else 'unverified'
                    print(f"    ! {p['input']!r} — {tag}")
        return 0

    if '--upsert' in args:
        payload = json.loads(sys.stdin.read() or '[]')
        entries = payload if isinstance(payload, list) else [payload]
        created = updated = 0
        for e in entries:
            row, was_new = upsert(e, rows)
            created += was_new
            updated += (not was_new)
            verb = 'added' if was_new else 'updated'
            note = f" (corrected from {row['corrected_from']!r})" if row.get('corrected_from') else ''
            print(f"  {verb}: {row['source_id']:22s} {row['name']}  [{row['status']}]{note}")
        if '--dry-run' not in args:
            save_sources(rows)
            print(f'Wrote {len(rows)} sources ({created} new, {updated} updated).')
        else:
            print('Dry run — nothing written.')
        return 0

    if '--apply-verdicts' in args:
        payload = json.loads(sys.stdin.read() or '[]')
        apply_verdicts(payload if isinstance(payload, list) else [payload],
                       dry_run='--dry-run' in args)
        return 0

    if '--record-fetch' in args:
        i = args.index('--record-fetch')
        sid = args[i + 1]
        count = int(args[i + 2]) if len(args) > i + 2 else 0
        row = record_fetch(sid, count)
        print(f"  {sid}: last_ok_at={row['last_ok_at']} last_items={count}" if row
              else f'  no such source: {sid}')
        return 0

    print('Nothing to do. See --help.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
