#!/usr/bin/env python3
"""
UN General Debate analysis: concern clusters + a pairwise "friendliness" score.

Reads (all under data/un_speeches/unga<N>/):
  speeches.csv      index written by scripts/pull_un_speeches.py
  summaries.json    agent-written via scripts/add_un_summaries.py, keyed by video_id
                    (src = transcript | un_press):
                      address → summary, primary_concern, primary_topic,
                                concerns {topic: 1-3}, mentions [{iso2, stance -2..2, note}],
                                positions {ukr|isr|irn|ord|sanc: -1..1}
                      reply   → pairs [{from, to, stance, note}] + summary
Writes:
  data/un_speeches/unga<N>.json   everything the speeches page renders

Method (kept deliberately simple and explainable — the page prints it):

  Concern vector   the 20-topic weights the agent assigned, L2-normalised.
  Clusters         k-means on those vectors (cosine geometry), k chosen by
                   silhouette over K_RANGE, many seeded restarts → deterministic.
  Map layout       2-D PCA of the same vectors.
  Friendliness     per pair, a weighted mean of whichever signals exist:
                     direct  0.60  what each said ABOUT the other (mention
                                   stances, both directions averaged; a right
                                   of reply between them counts -2)
                     align   0.30  agreement on the five contested positions
                                   (Ukraine, Israel/Gaza, Iran war, world
                                   order, sanctions), needs >= 2 in common
                     concern 0.10  similarity of what they worry about —
                                   standardised and capped at ±0.35, so
                                   different priorities never read as hostility
                   Alignment weight scales with shared stances (full at 3).
                   Scaled to [-1, 1]. `basis` records which signals fed it, so
                   the page can tell "said so" from "inferred".

Usage:  python3 scripts/analyze_un_speeches.py [--session 81]
"""

import argparse
import csv
import json

import os
import random
from datetime import datetime, timezone

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TOPICS = [
    ('gulf_war',        'Gulf war & Hormuz'),
    ('ukraine',         'Ukraine war'),
    ('palestine',       'Gaza & Palestine'),
    ('middle_east',     'Syria, Lebanon & Yemen'),
    ('un_reform',       'UN & Security Council reform'),
    ('sovereignty',     'Sovereignty & rule of force'),
    ('development',     'Development finance & debt'),
    ('climate',         'Climate & sea-level rise'),
    ('trade',           'Trade, tariffs & connectivity'),
    ('food_energy',     'Food & energy security'),
    ('technology',      'AI & technology'),
    ('terrorism',       'Terrorism'),
    ('nuclear',         'Nuclear & disarmament'),
    ('africa_security', 'African conflicts'),
    ('americas',        'Americas: Cuba, Haiti, Venezuela, crime'),
    ('asia_security',   'Asia: Korea, Myanmar, Afghanistan, seas'),
    ('territorial',     'Border disputes & peace deals'),
    ('human_rights',    'Human rights & democracy'),
    ('migration',       'Migration'),
    ('health',          'Health'),
]
TOPIC_KEYS = [k for k, _ in TOPICS]

POSITIONS = [
    ('ukr',  'Ukraine',        'backs Ukraine / condemns Russia', 'Russian framing'),
    ('isr',  'Israel & Gaza',  'critical of Israel',              'backs Israel'),
    ('irn',  'Iran war',       'sides with Iran',                 'condemns Iran'),
    ('ord',  'World order',    'multipolar / anti-hegemony',      'Western-led rules order'),
    ('sanc', 'Sanctions',      'opposes unilateral sanctions',    'supports sanctions'),
]
POS_KEYS = [p[0] for p in POSITIONS]

W_DIRECT, W_ALIGN, W_CONCERN = 0.60, 0.30, 0.10
REPLY_STANCE = -2
CONCERN_CAP = 0.35   # max |friendliness| from concern similarity alone
# Clusters are told apart by marker SHAPE on the page (the site's colour rule
# allows no categorical palette), and seven shapes is where that stays legible.
K_RANGE = range(4, 8)


def load(session):
    sdir = os.path.join(ROOT, 'data', 'un_speeches', f'unga{session}')
    with open(os.path.join(sdir, 'speeches.csv'), encoding='utf-8') as f:
        index = list(csv.DictReader(f))
    with open(os.path.join(sdir, 'summaries.json'), encoding='utf-8') as f:
        summaries = json.load(f)
    return index, summaries


# ── Clustering ────────────────────────────────────────────────────────────────

def kmeans(X, k, seed):
    rng = random.Random(seed)
    # k-means++ seeding on cosine distance (X rows are unit vectors)
    centers = [X[rng.randrange(len(X))]]
    while len(centers) < k:
        d = np.min(1 - X @ np.array(centers).T, axis=1).clip(0)
        total = d.sum()
        if total <= 0:
            centers.append(X[rng.randrange(len(X))])
            continue
        r, acc = rng.random() * total, 0.0
        for i, di in enumerate(d):
            acc += di
            if acc >= r:
                centers.append(X[i])
                break
    C = np.array(centers)
    labels = None
    for _ in range(100):
        new = np.argmax(X @ C.T, axis=1)
        if labels is not None and (new == labels).all():
            break
        labels = new
        for j in range(k):
            members = X[labels == j]
            if len(members):
                c = members.mean(axis=0)
                C[j] = c / (np.linalg.norm(c) or 1)
    inertia = float(np.sum(1 - np.sum(X * C[labels], axis=1)))
    return labels, inertia


def silhouette(X, labels):
    D = 1 - X @ X.T
    s = []
    for i in range(len(X)):
        same = labels == labels[i]
        if same.sum() <= 1:
            s.append(0.0)
            continue
        a = D[i, same].sum() / (same.sum() - 1)
        b = min(D[i, labels == j].mean() for j in set(labels.tolist()) if j != labels[i])
        s.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)
    return float(np.mean(s))


def cluster(X):
    if len(X) < 12:
        k_range = [max(2, len(X) // 4)]
    else:
        k_range = [k for k in K_RANGE if k < len(X) // 3] or [3]
    best = None
    for k in k_range:
        runs = [kmeans(X, k, seed) for seed in range(40)]
        labels, _ = min(runs, key=lambda r: r[1])
        score = silhouette(X, labels)
        if best is None or score > best[0]:
            best = (score, k, labels)
    return best


def pca2(X):
    """2-D PCA → (coords scaled to [-1, 1], per-axis loadings over TOPIC_KEYS)."""
    Xc = X - X.mean(axis=0)
    _, _, vt = np.linalg.svd(Xc, full_matrices=False)
    L = vt[:2].copy()
    # Deterministic orientation (SVD signs are arbitrary): make each axis's
    # heaviest loading positive, so reruns don't mirror the map.
    for ax in range(2):
        if L[ax, np.argmax(np.abs(L[ax]))] < 0:
            L[ax] *= -1
    P = Xc @ L.T
    span = np.abs(P).max(axis=0)
    span[span == 0] = 1
    return P / span, L


def axis_labels(L):
    """What each map direction MEANS — the topics loading hardest on either end."""
    out = []
    for ax in range(2):
        order = np.argsort(L[ax])
        out.append({
            'plus':  [TOPIC_KEYS[t] for t in order[::-1][:2] if L[ax, t] > 0.15],
            'minus': [TOPIC_KEYS[t] for t in order[:2] if L[ax, t] < -0.15],
        })
    return out


# ── Friendliness ──────────────────────────────────────────────────────────────

def direct_stances(nations, summaries, index):
    """(a, b) → [(stance, note, 'speech'|'reply'), …] that a expressed about b."""
    by_iso = {n['iso2'] for n in nations}
    said = {}
    for n in nations:
        for m in n['mentions']:
            if m['iso2'] in by_iso and m['iso2'] != n['iso2']:
                said.setdefault((n['iso2'], m['iso2']), []).append((m['stance'], m.get('note', ''), 'speech'))
    replies = []
    for r in index:
        if r['kind'] != 'reply' or r['video_id'] not in summaries:
            continue
        s = summaries[r['video_id']]
        for p in s.get('pairs', []):
            said.setdefault((p['from'], p['to']), []).append(
                (p.get('stance', REPLY_STANCE), p.get('note', ''), 'reply'))
        replies.append({'video_id': r['video_id'], 'title': r['country'], 'url': r['url'],
                        'summary': s.get('summary', ''), 'pairs': s.get('pairs', []),
                        'src': s.get('src', 'transcript'), 'source_url': s.get('source_url', '')})
    return said, replies


def friendliness(nations, said, X):
    n = len(nations)
    iso = [x['iso2'] for x in nations]
    pos = [x['positions'] for x in nations]
    # Concern similarity is a NUDGE, not a verdict: worrying about different
    # things is not hostility. Standardise it across all pairs and cap it, so
    # a pair known only by its concerns lands near neutral (|F| <= CONCERN_CAP)
    # instead of at -1 just because their topics don't overlap.
    S = X @ X.T
    upper = S[np.triu_indices(n, 1)]
    mu, sd = float(upper.mean()), float(upper.std() or 1)
    F, basis = {}, {}
    for i in range(n):
        for j in range(i + 1, n):
            a, b = iso[i], iso[j]
            parts, weights, used = [], [], []
            dirs = [np.mean([t[0] for t in said[k]]) for k in ((a, b), (b, a)) if k in said]
            if dirs:
                parts.append(float(np.mean(dirs)) / 2)
                weights.append(W_DIRECT)
                used.append('direct')
            shared = [k for k in POS_KEYS if k in pos[i] and k in pos[j]]
            if len(shared) >= 2:
                agree = np.mean([1 - abs(pos[i][k] - pos[j][k]) for k in shared])
                parts.append(float(agree))
                # Two shared stances is thin evidence; full weight from three.
                weights.append(W_ALIGN * min(1.0, len(shared) / 3))
                used.append('align')
            z = (float(S[i, j]) - mu) / sd
            parts.append(max(-CONCERN_CAP, min(CONCERN_CAP, z * CONCERN_CAP / 2)))
            weights.append(W_CONCERN)
            used.append('concern')
            F[(i, j)] = sum(p * w for p, w in zip(parts, weights)) / sum(weights)
            basis[(i, j)] = used
    return F, basis


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--session', type=int, default=81)
    args = ap.parse_args()
    index, summaries = load(args.session)

    nations = []
    for r in index:
        if r['kind'] != 'address' or r['video_id'] not in summaries:
            continue
        s = summaries[r['video_id']]
        nations.append({
            'video_id': r['video_id'], 'iso2': r['iso2'], 'country': r['country'],
            'role': r['speaker_role'], 'speaker': s['speaker'], 'url': r['url'],
            'published': r.get('published', ''), 'words': int(r.get('words') or 0),
            'summary': s['summary'], 'primary_concern': s['primary_concern'],
            'primary_topic': s['primary_topic'], 'concerns': s['concerns'],
            'mentions': s['mentions'], 'positions': s['positions'],
            # 'transcript' = read from the full speech; 'un_press' = read from the
            # UN's official per-speaker meeting coverage (used while YouTube
            # blocks transcript downloads; upgraded when a transcript lands).
            'src': s.get('src', 'transcript'), 'source_url': s.get('source_url', ''),
        })
    nations.sort(key=lambda x: x['country'])
    if len(nations) < 4:
        raise SystemExit('need at least 4 summarised addresses')

    X = np.array([[x['concerns'].get(k, 0) for k in TOPIC_KEYS] for x in nations], float)
    X /= np.linalg.norm(X, axis=1, keepdims=True).clip(1e-9)

    sil, k, labels = cluster(X)
    xy, loadings = pca2(X)

    # Name each cluster by its two heaviest topics (mean weight inside it).
    raw = np.array([[x['concerns'].get(t, 0) for t in TOPIC_KEYS] for x in nations], float)
    clusters = []
    order = sorted(range(k), key=lambda c: -(labels == c).sum())
    remap = {old: new for new, old in enumerate(order)}
    labels = np.array([remap[l] for l in labels])
    label_of = dict(TOPICS)
    for c in range(k):
        members = labels == c
        mean = raw[members].mean(axis=0)
        top = [TOPIC_KEYS[t] for t in np.argsort(-mean)[:3] if mean[t] > 0]
        clusters.append({
            'id': c,
            'label': ' + '.join(label_of[t].split(' & ')[0].split(':')[0] for t in top[:2]),
            'top_topics': [{'key': t, 'weight': round(float(mean[TOPIC_KEYS.index(t)]), 2)} for t in top],
            'members': [nations[i]['iso2'] for i in np.where(members)[0]],
        })

    said, replies = direct_stances(nations, summaries, index)
    F, basis = friendliness(nations, said, X)

    for i, x in enumerate(nations):
        x['cluster'] = int(labels[i])
        x['xy'] = [round(float(xy[i, 0]), 4), round(float(xy[i, 1]), 4)]

    n = len(nations)
    iso = [x['iso2'] for x in nations]
    # One edge per unordered pair, carrying every statement in both directions
    # so the page can show WHAT was said, not just a number.
    pairs = {}
    for (a_iso, b_iso), items in said.items():
        if a_iso not in iso or b_iso not in iso:
            continue
        key = tuple(sorted((a_iso, b_iso)))
        for stance, note, src in items:
            pairs.setdefault(key, []).append(
                {'from': a_iso, 'to': b_iso, 'stance': stance, 'note': note, 'src': src})
    edges = [{'a': a, 'b': b, 'stance': round(float(np.mean([x['stance'] for x in said_])), 2),
              'said': said_} for (a, b), said_ in sorted(pairs.items())]
    # Flat upper triangle, row-major, 2 d.p. — ~n²/2 numbers the page indexes into.
    tri = [round(F[(i, j)], 2) for i in range(n) for j in range(i + 1, n)]
    tri_basis = [''.join(p[0] for p in basis[(i, j)]) for i in range(n) for j in range(i + 1, n)]

    out = {
        'session': args.session,
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'topics': [{'key': k_, 'label': l} for k_, l in TOPICS],
        'positions': [{'key': p[0], 'label': p[1], 'plus': p[2], 'minus': p[3]} for p in POSITIONS],
        'weights': {'direct': W_DIRECT, 'align': W_ALIGN, 'concern': W_CONCERN},
        'silhouette': round(sil, 3),
        'axes': axis_labels(loadings),
        'nations': nations,
        'clusters': clusters,
        'edges': edges,
        'replies': replies,
        'friendliness': {'order': iso, 'tri': tri, 'basis': tri_basis},
        'coverage': {
            'indexed': sum(1 for r in index if r['kind'] == 'address'),
            'summarised': n,
            'from_transcript': sum(1 for x in nations if x['src'] == 'transcript'),
            'from_press': sum(1 for x in nations if x['src'] == 'un_press'),
        },
    }
    path = os.path.join(ROOT, 'data', 'un_speeches', f'unga{args.session}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    print(f'{n} nations · k={k} (silhouette {sil:.2f}) · {len(edges)} direct edges · '
          f'{len(replies)} reply sessions → {os.path.relpath(path, ROOT)} '
          f'({os.path.getsize(path) // 1024} KB)')
    for c in clusters:
        print(f"  [{c['id']}] {c['label']}: {' '.join(c['members'])}")


if __name__ == '__main__':
    main()
