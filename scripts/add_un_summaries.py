#!/usr/bin/env python3
"""
Validated merge of agent-written UN General Debate summaries into
data/un_speeches/unga<N>/summaries.json (keyed by video_id).

The summaries themselves are editorial: an agent reads each speech (full
transcript, or the UN's per-speaker meeting coverage when YouTube blocks
transcript downloads) and writes one compact record. This script only
validates and merges them — use it instead of hand-editing the JSON.

stdin: a JSON array of compact records.

  Address (one nation's speech):
    {"v":   "<video_id>"            — OR —   "iso": "IN", "name": "India"
     "src": "transcript" | "un_press",       (default transcript)
     "url": "<press.un.org release when src=un_press>",
     "sp":  "Speaker name",
     "s":   "3-5 sentence summary",
     "pc":  "Primary concern, one phrase",
     "pt":  "<topic key>",                   primary topic (see TOPICS)
     "c":   {"<topic key>": 1-3, ...},        weights of the 3-6 main concerns
     "m":   [["PK", -2, "note"], ...],        every explicit statement about another
                                              nation: -2 hostile, -1 critical, 0 neutral,
                                              +1 supportive, +2 strong support/alliance
     "p":   {"ukr": -1..1, "isr": .., "irn": .., "ord": .., "sanc": ..}
                                              only positions the speech actually takes:
                                              ukr +1 backs Ukraine / -1 Russian framing
                                              isr +1 critical of Israel / -1 backs Israel
                                              irn +1 sides with Iran / -1 condemns Iran
                                              ord +1 multipolar, anti-hegemony / -1 Western-led order
                                              sanc +1 opposes unilateral sanctions / -1 supports them
    }
    "iso" resolves to that country's address row in speeches.csv; a nation with
    no UN video gets a synthetic 'press-<ISO>' index row (needs "name").

  Right of reply (a session where delegations rebut each other):
    {"v": "<video_id>", "src": ..., "url": ..., "s": "summary",
     "pairs": [["PK", "IN", -2, "note"], ...]}      from, to, stance, note

A transcript-based summary is never replaced by a coverage-based one; a
coverage-based one IS replaced when a transcript-based record arrives.

Usage:
  python3 scripts/add_un_summaries.py [--session 81] < records.json
  python3 scripts/add_un_summaries.py --todo      # list index rows still unsummarised,
                                                  # and press-based ones whose transcript
                                                  # is now on disk (upgrade candidates)
Then: python3 scripts/analyze_un_speeches.py
"""
import argparse
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOPICS = {'gulf_war', 'ukraine', 'palestine', 'middle_east', 'un_reform', 'climate', 'development',
          'sovereignty', 'trade', 'terrorism', 'nuclear', 'africa_security', 'americas',
          'asia_security', 'territorial', 'technology', 'migration', 'human_rights', 'health',
          'food_energy'}
POS = {'ukr', 'isr', 'irn', 'ord', 'sanc'}


def paths(session):
    d = os.path.join(ROOT, 'data', 'un_speeches', f'unga{session}')
    return d, os.path.join(d, 'summaries.json'), os.path.join(d, 'speeches.csv')


def todo(session):
    d, sp, ip = paths(session)
    cur = json.load(open(sp, encoding='utf-8')) if os.path.exists(sp) else {}
    rows = list(csv.DictReader(open(ip, encoding='utf-8')))
    has_tx = lambda v: os.path.exists(os.path.join(d, 'transcripts', f'{v}.txt'))
    missing = [r for r in rows if r['video_id'] not in cur]
    upgrade = [r for r in rows if cur.get(r['video_id'], {}).get('src') == 'un_press' and has_tx(r['video_id'])]
    print(f'Unsummarised ({len(missing)}):')
    for r in missing:
        print(f"  {r['video_id']}  {r['kind']:<8} {r['iso2']:<3} {r['country']}"
              f"{'  [transcript on disk]' if has_tx(r['video_id']) else ''}")
    print(f'Press-based with transcript now on disk — upgrade candidates ({len(upgrade)}):')
    for r in upgrade:
        print(f"  {r['video_id']}  {r['iso2']:<3} {r['country']}")


def merge(session, records):
    _, sp, ip = paths(session)
    cur = json.load(open(sp, encoding='utf-8')) if os.path.exists(sp) else {}
    with open(ip, encoding='utf-8') as f:
        rd = csv.DictReader(f)
        cols, rows = rd.fieldnames, list(rd)
    added_rows, skipped = 0, 0
    for r in records:
        vid = r.get('v')
        if not vid:
            hits = [x for x in rows if x['kind'] == 'address' and x['iso2'] == r['iso']]
            if hits:
                vid = hits[0]['video_id']
            else:
                vid = 'press-' + r['iso']
                if not any(x['video_id'] == vid for x in rows):
                    row = {c: '' for c in cols}
                    row.update(video_id=vid, kind='address', iso2=r['iso'], country=r['name'],
                               speaker_role=r.get('role', ''), url=r.get('url', ''),
                               title=f"{r['name']} (UN press coverage only)", transcript_status='none')
                    rows.append(row)
                    added_rows += 1
        src = r.get('src', 'transcript')
        prev = cur.get(vid)
        if prev and prev.get('src', 'transcript') == 'transcript' and src == 'un_press':
            skipped += 1
            continue   # never downgrade a transcript-based summary
        if 'pairs' in r:
            for p in r['pairs']:
                assert len(p[0]) == 2 and len(p[1]) == 2 and -2 <= p[2] <= 2, (vid, p)
            cur[vid] = {'summary': r['s'], 'src': src, 'source_url': r.get('url', ''),
                        'pairs': [{'from': a, 'to': b, 'stance': st, 'note': n} for a, b, st, n in r['pairs']]}
            continue
        assert r['pt'] in TOPICS, (vid, r['pt'])
        for k, w in r['c'].items():
            assert k in TOPICS and 1 <= w <= 3, (vid, k, w)
        for k in r.get('p', {}):
            assert k in POS, (vid, k)
        for m in r.get('m', []):
            assert len(m[0]) == 2 and -2 <= m[1] <= 2, (vid, m)
        cur[vid] = {'speaker': r['sp'], 'summary': r['s'], 'primary_concern': r['pc'],
                    'primary_topic': r['pt'], 'concerns': r['c'],
                    'mentions': [{'iso2': m[0], 'stance': m[1], 'note': m[2]} for m in r.get('m', [])],
                    'positions': r.get('p', {}), 'src': src, 'source_url': r.get('url', '')}
    with open(sp, 'w', encoding='utf-8') as f:
        json.dump(cur, f, indent=1, ensure_ascii=False)
    if added_rows:
        with open(ip, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols, quoting=csv.QUOTE_ALL)
            w.writeheader()
            w.writerows(rows)
    print(f'summaries: {len(cur)} | new index rows: {added_rows} | kept transcript-based: {skipped}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--session', type=int, default=81)
    ap.add_argument('--todo', action='store_true')
    a = ap.parse_args()
    if a.todo:
        todo(a.session)
    else:
        merge(a.session, json.load(sys.stdin))


if __name__ == '__main__':
    main()
