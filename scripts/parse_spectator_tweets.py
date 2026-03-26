#!/usr/bin/env python3
"""Parse Spectator Index tweets and classify into war/operations subsets."""

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Flag-emoji → ISO-2 mapping
# ---------------------------------------------------------------------------
FLAG_EMOJI_MAP = {
    "\U0001f1fa\U0001f1f8": "US",  # 🇺🇸
    "\U0001f1ee\U0001f1f1": "IL",  # 🇮🇱
    "\U0001f1ee\U0001f1f7": "IR",  # 🇮🇷
    "\U0001f1f7\U0001f1fa": "RU",  # 🇷🇺
    "\U0001f1fa\U0001f1e6": "UA",  # 🇺🇦
    "\U0001f1e8\U0001f1f3": "CN",  # 🇨🇳
    "\U0001f1fe\U0001f1ea": "YE",  # 🇾🇪
    "\U0001f1f1\U0001f1e7": "LB",  # 🇱🇧
    "\U0001f1f5\U0001f1f8": "PS",  # 🇵🇸
    "\U0001f1f5\U0001f1ed": "PH",  # 🇵🇭
    "\U0001f1fb\U0001f1ea": "VE",  # 🇻🇪
    "\U0001f1f8\U0001f1e6": "SA",  # 🇸🇦
    "\U0001f1f8\U0001f1fe": "SY",  # 🇸🇾
    "\U0001f1ee\U0001f1f6": "IQ",  # 🇮🇶
    "\U0001f1f9\U0001f1f7": "TR",  # 🇹🇷
    "\U0001f1f5\U0001f1f0": "PK",  # 🇵🇰
    "\U0001f1ec\U0001f1e7": "GB",  # 🇬🇧
    "\U0001f1eb\U0001f1f7": "FR",  # 🇫🇷
    "\U0001f1e9\U0001f1ea": "DE",  # 🇩🇪
    "\U0001f1ef\U0001f1f5": "JP",  # 🇯🇵
    "\U0001f1f0\U0001f1f7": "KR",  # 🇰🇷
    "\U0001f1e6\U0001f1fa": "AU",  # 🇦🇺
    "\U0001f1ee\U0001f1f3": "IN",  # 🇮🇳
    "\U0001f1f5\U0001f1f1": "PL",  # 🇵🇱
    "\U0001f1f6\U0001f1e6": "QA",  # 🇶🇦
    "\U0001f1ea\U0001f1ec": "EG",  # 🇪🇬
    "\U0001f1ef\U0001f1f4": "JO",  # 🇯🇴
    "\U0001f1f9\U0001f1fc": "TW",  # 🇹🇼
    "\U0001f1f0\U0001f1fc": "KW",  # 🇰🇼
    "\U0001f1e6\U0001f1ea": "AE",  # 🇦🇪
}

# Country-name regex → ISO-2 (order matters for overlapping patterns)
COUNTRY_NAME_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bUnited States\b|\bAmerica(?:n)?\b|\bUS\s(?:military|Navy|official|senator|sailor|Marine|Air Force|Army|force)", re.I), "US"),
    (re.compile(r"\bIsrael[i']?s?\b|\bIDF\b|\bIAF\b|\bTel Aviv\b|\bNetanyahu\b|\bNevatim\b", re.I), "IL"),
    (re.compile(r"\bIran[i']?(?:an|s)?\b|\bTehran\b|\bIRGC\b|\bBushehr\b|\bFordow\b|\bNatanz\b|\bIsfahan\b|\bKharg\b|\bMinab\b", re.I), "IR"),
    (re.compile(r"\bRussia[n']?s?\b|\bMoscow\b|\bKremlin\b|\bPutin\b", re.I), "RU"),
    (re.compile(r"\bUkrain[ei](?:an|'s)?\b|\bKyiv\b|\bZelensky\b|\bDonbas\b|\bCrimea\b|\bBakhmut\b", re.I), "UA"),
    (re.compile(r"\bChin(?:a|ese)\b|\bBeijing\b|\bXi Jinping\b", re.I), "CN"),
    (re.compile(r"\bYemen[i]?\b|\bHouthi[s]?\b|\bSanaa\b|\bAnsar Allah\b", re.I), "YE"),
    (re.compile(r"\bLebanon\b|\bLebanese\b|\bHezbollah\b|\bBeirut\b|\bNasrallah\b", re.I), "LB"),
    (re.compile(r"\bPalestini?(?:an|e)\b|\bGaza\b|\bHamas\b|\bWest Bank\b", re.I), "PS"),
    (re.compile(r"\bPhilippine[s]?\b|\bManila\b|\bSouth China Sea\b", re.I), "PH"),
    (re.compile(r"\bVenezuela[n]?\b|\bCaracas\b|\bMaduro\b", re.I), "VE"),
    (re.compile(r"\bSaudi\b|\bRiyadh\b|\bMBS\b", re.I), "SA"),
    (re.compile(r"\bSyria[n]?\b|\bDamascus\b|\bAssad\b", re.I), "SY"),
    (re.compile(r"\bIraq[i]?\b|\bBaghdad\b", re.I), "IQ"),
    (re.compile(r"\bPakistan[i]?\b|\bIslamabad\b", re.I), "PK"),
    (re.compile(r"\bTaiwan(?:ese)?\b|\bTaipei\b", re.I), "TW"),
    (re.compile(r"\bTurk(?:ey|ish|iye)\b|\bAnkara\b|\bErdogan\b", re.I), "TR"),
    (re.compile(r"\bNorth Korea[n]?\b|\bPyongyang\b|\bKim Jong\b", re.I), "KP"),
]

# ---------------------------------------------------------------------------
# Category keyword patterns
# ---------------------------------------------------------------------------
CATEGORY_PATTERNS: dict[str, list[re.Pattern]] = {
    "military_operations": [
        re.compile(p, re.I) for p in [
            r"\bstrike[sd]?\s",
            r"\bstrike[sd]?\b.*\b(?:on|against|in|at|near|across)\b",
            r"\bmissile[s]?\b",
            r"\bdrone[s]?\s(?:strike|attack|launch|intercept)",
            r"\bairstrike[s]?\b",
            r"\bbomb(?:s|ed|ing|ardment|arded)\b",
            r"\btroops?\b",
            r"\bdeploy(?:s|ed|ing|ment)\b",
            r"\bmilitary\b",
            r"\bnaval\b",
            r"\bwarship[s]?\b",
            r"\bdestroyer[s]?\b",
            r"\bcarrier\b",
            r"\bfighter\s?jet",
            r"\bF-35\b",
            r"\bF-22\b",
            r"\bB-2\b",
            r"\bB-52\b",
            r"\bspecial forces\b",
            r"\bbrigade\b",
            r"\bairborne\b",
            r"\b[Mm]arines?\b",
            r"\bsailors?\b",
            r"\bair\s?defen[cs]e\b",
            r"\bPatriot\b",
            r"\bIron Dome\b",
            r"\bArrow[\s-]?\d\b",
            r"\bintercept(?:s|ed|ion)\b",
            r"\bblast[s]?\b",
            r"\bexplosion[s]?\b",
            r"\bshelling\b",
            r"\bsortie[s]?\b",
            r"\boffensive\b",
            r"\binvasion\b",
            r"\bground\s?(?:operation|invasion|forces|offensive)\b",
            r"\bair\s?campaign\b",
            r"\bsubmarine[s]?\b",
            r"\bblockade\b",
            r"\b82nd\s?Airborne\b",
            r"\bcombat\s?team\b",
            r"\bHouthi[s]?\b",
            r"\bHezbollah\b",
            r"\bHamas\b",
            r"\bIRGC\b",
            r"\bWagner\b",
            r"\bTomahawk\b",
            r"\bMOP\b",
            r"\bJDAM\b",
            r"\bair\s?force\b",
            r"\bhelicopter[s]?\b",
            r"\bbesieg(?:e|ed|ing)\b",
            r"\bNavy\s?vessel[s]?\b",
            r"\bwar(?:plane|ship|head)[s]?\b",
            r"\bescalat(?:e|es|ed|ing|ion)\b",
            r"\bretalia(?:te|tion|tory)\b",
            r"\bweapon[s]?\b",
            r"\bammunition\b",
            r"\barms\b.*\b(?:supply|shipment|embargo|deal)\b",
            r"\bsatellite imagery\b",
            r"\bshot down\b",
            r"\bshoot(?:s|ing)?\s?down\b",
            r"\battack(?:s|ed)?\b.*\b(?:on|against|in)\b",
            r"\boperation\b",
            r"\bStrait of Hormuz\b",
            r"\bKharg Island\b",
        ]
    ],
    "diplomacy_negotiations": [
        re.compile(p, re.I) for p in [
            r"\bceasefire\b",
            r"\bpeace\s?(?:talk|deal|plan|agreement|process|proposal)",
            r"\bnegotiat(?:e|es|ed|ing|ion|ions)\b",
            r"\bdiplomat(?:ic|s|ically)?\b",
            r"\bmediat(?:e|or|ion|ing)\b",
            r"\bultimatum\b",
            r"\btreaty\b",
            r"\bde-?escalat(?:e|ion|ing)\b",
            r"\btalk[s]?\s?(?:with|between|to end|about ending|toward|over)",
            r"\benvoy\b",
            r"\bintermediary\b",
            r"\b\d+-point plan\b",
            r"\bsanctions?\s?(?:lift|relief|waiv|remov)",
            r"\bwar\s?damages?\s?(?:paid|pay)\b",
            r"\bdeal\b.*\b(?:Iran|Russia|China|Ukraine|end the war)\b",
            r"\bpeacekeep(?:er|ing)\b",
            r"\btruce\b",
            r"\bhostage[s]?\b.*\b(?:releas|deal|negotiat|return)",
            r"\bdisarm(?:ament|ed|ing|s)?\b",
            r"\blay down (?:its |their )?arms\b",
        ]
    ],
    "nuclear": [
        re.compile(p, re.I) for p in [
            r"\bnuclear\b",
            r"\benrich(?:ment|ed|ing)\b",
            r"\bIAEA\b",
            r"\buranium\b",
            r"\bcentrifuge[s]?\b",
            r"\bwarhead[s]?\b",
            r"\bBushehr\b",
            r"\bFordow\b",
            r"\bNatanz\b",
            r"\batomic\b",
            r"\bnon-?proliferation\b",
            r"\bNPT\b",
        ]
    ],
    "casualties_humanitarian": [
        re.compile(p, re.I) for p in [
            # "killed" only in conflict context (co-occur with conflict terms)
            r"\b(?:missile|strike|bomb|attack|drone|shelling|airstrike|operation|battle|fighting|clash|raid|offensive|war).*\bkilled\b",
            r"\bkilled\b.*\b(?:missile|strike|bomb|attack|drone|shelling|airstrike|operation|battle|fighting|clash|raid|offensive|war)\b",
            r"\bcasualt(?:y|ies)\b",
            r"\bdeath toll\b",
            r"\bwounded\b.*\b(?:missile|strike|bomb|attack|drone|shelling|battle|soldier|military)\b",
            r"\bhumanitarian\b",
            r"\brefugee[s]?\b",
            r"\bdisplaced\b",
            r"\bcivilian[s]?\b",
            r"\bwar\s?crime[s]?\b",
            r"\bgenocide\b",
            r"\batrocit(?:y|ies)\b",
            r"\bmassacre\b",
            r"\bfamine\b",
            r"\baid\s?(?:convoy|delivery|worker)",
            r"\bsoldier[s]?\s?(?:killed|dead|die[sd])\b",
            r"\bchildren\s?(?:killed|dead|die[sd])\b",
            # Conflict-specific killed patterns
            r"\b(?:IRGC|Guards?|commander|general|minister|spokesman)\b.*\bkilled\b",
            r"\bkilled\b.*\b(?:IRGC|Guards?|commander|general|minister|spokesman)\b",
        ]
    ],
}

# ---------------------------------------------------------------------------
# Operation linking rules
# ---------------------------------------------------------------------------
OPERATION_RULES = [
    {
        "name": "Op. Swords of Iron",
        "start": "2023-10-07",
        "end": "2026-12-31",
        "countries": {"IL", "PS"},
        "require_any": True,
        "keywords": [re.compile(p, re.I) for p in [
            r"\bGaza\b", r"\bHamas\b", r"\bWest Bank\b", r"\bSwords of Iron\b",
            r"\bIDF\b.*\bGaza\b", r"\bhostage[s]?\b",
        ]],
    },
    {
        "name": "Op. Northern Arrows",
        "start": "2024-04-01",
        "end": "2024-10-31",
        "countries": {"IL", "IR", "LB"},
        "require_any": True,
        "keywords": [re.compile(p, re.I) for p in [
            r"\bNorthern Arrows\b", r"\bHezbollah\b", r"\bLebanon\b",
            r"\bNasrallah\b", r"\bBeirut\b",
        ]],
    },
    {
        "name": "Russia-Ukraine War",
        "start": "2022-02-24",
        "end": "2026-12-31",
        "countries": {"RU", "UA"},
        "require_any": True,
        "keywords": [re.compile(p, re.I) for p in [
            r"\bUkrain", r"\bKyiv\b", r"\bBakhmut\b", r"\bWagner\b",
            r"\bCrimea\b", r"\bDonbas\b", r"\bZelensky\b",
            r"\bRussia.*(?:war|invasi|attack|offensive|front)",
        ]],
    },
    {
        "name": "Op. Midnight Hammer",
        "start": "2025-06-01",
        "end": "2025-06-30",
        "countries": {"US"},
        "require_any": False,
        "keywords": [re.compile(p, re.I) for p in [
            r"\bMidnight Hammer\b", r"\bB-2\b.*\b(?:Iran|Fordow|Natanz)\b",
            r"\bMOP\b", r"\bFordow\b", r"\bNatanz\b",
        ]],
    },
    {
        "name": "12-Day War (IDF)",
        "start": "2025-06-01",
        "end": "2025-06-30",
        "countries": {"IL", "US"},
        "require_any": True,
        "keywords": [re.compile(p, re.I) for p in [
            r"\b12-?Day War\b", r"\bIsrael.*(?:strike|bomb|attack).*Iran",
            r"\bIDF.*Iran\b",
        ]],
    },
    {
        "name": "Op. Absolute Resolve",
        "start": "2025-12-01",
        "end": "2026-01-31",
        "countries": {"US"},
        "require_any": False,
        "keywords": [re.compile(p, re.I) for p in [
            r"\bAbsolute Resolve\b", r"\bVenezuela\b", r"\bMaduro\b",
            r"\bCaracas\b",
        ]],
    },
    {
        "name": "Op. Southern Spear",
        "start": "2026-01-01",
        "end": "2026-01-31",
        "countries": {"US"},
        "require_any": False,
        "keywords": [re.compile(p, re.I) for p in [
            r"\bSouthern Spear\b",
        ]],
    },
    {
        "name": "Op. Epic Fury",
        "start": "2026-02-20",
        "end": "2026-03-31",
        "countries": {"US", "IL"},
        "require_any": True,
        "keywords": [re.compile(p, re.I) for p in [
            r"\bEpic Fury\b",
            r"\b(?:US|America|Israel).*(?:strike|bomb|attack|offensive).*Iran",
            r"\bstrike[sd]?\b.*\bTehran\b",
            r"\bstrike[sd]?\b.*\b(?:Iran|nuclear)\b",
        ]],
    },
    {
        "name": "Op. Roaring Lion",
        "start": "2026-02-20",
        "end": "2026-03-31",
        "countries": {"US", "IL"},
        "require_any": True,
        "keywords": [re.compile(p, re.I) for p in [
            r"\bRoaring Lion\b",
        ]],
    },
    {
        "name": "Task Force Scorpion Strike",
        "start": "2025-12-01",
        "end": "2026-02-28",
        "countries": {"US"},
        "require_any": False,
        "keywords": [re.compile(p, re.I) for p in [
            r"\bScorpion Strike\b",
        ]],
    },
    {
        "name": "Iran Retaliation",
        "start": "2026-02-01",
        "end": "2026-03-31",
        "countries": {"IR", "YE"},
        "require_any": True,
        "keywords": [re.compile(p, re.I) for p in [
            r"\bIran.*(?:launch|retalia|missile|ballistic|wave)\b",
            r"\bmissile.*(?:from Iran|towards? Israel|at Israel)\b",
            r"\bIran.*(?:strike|attack).*Israel\b",
            r"\bIran.*(?:fight|war will continue)\b",
        ]],
    },
    {
        "name": "Houthi / Proxies",
        "start": "2025-01-01",
        "end": "2026-12-31",
        "countries": {"YE", "IR"},
        "require_any": True,
        "keywords": [re.compile(p, re.I) for p in [
            r"\bHouthi[s]?\b", r"\bAnsar Allah\b",
            r"\bRed Sea\b.*\b(?:attack|ship|strike)\b",
            r"\bYemen.*(?:missile|drone|strike|attack)\b",
        ]],
    },
    {
        "name": "China SCS Operations",
        "start": "2025-01-01",
        "end": "2026-12-31",
        "countries": {"CN", "PH"},
        "require_any": True,
        "keywords": [re.compile(p, re.I) for p in [
            r"\bSouth China Sea\b", r"\bSCS\b",
            r"\bScarborough\b", r"\bSpratly\b",
            r"\bPhilippine.*(?:China|vessel|ship|coast guard)\b",
            r"\bChina.*(?:Philippine|Manila|territorial)\b",
        ]],
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_statistics_table(text: str) -> bool:
    """Detect list-format statistical tweets (multiple countries + data)."""
    flag_count = len(re.findall(r"[\U0001F1E0-\U0001F1FF]{2}", text))
    colon_numbers = len(re.findall(r":\s*[\d$%.,']+", text))
    return flag_count >= 3 and colon_numbers >= 3


def extract_countries(text: str) -> list[str]:
    """Extract ISO-2 country codes from flag emojis and country name mentions."""
    codes: set[str] = set()
    # Flag emojis
    for emoji, code in FLAG_EMOJI_MAP.items():
        if emoji in text:
            codes.add(code)
    # Name patterns
    for pattern, code in COUNTRY_NAME_PATTERNS:
        if pattern.search(text):
            codes.add(code)
    return sorted(codes)


def classify_tweet(text: str) -> list[str]:
    """Return list of matching category labels for a tweet."""
    if is_statistics_table(text):
        return []
    categories = []
    for cat, patterns in CATEGORY_PATTERNS.items():
        for pat in patterns:
            if pat.search(text):
                categories.append(cat)
                break
    return categories


def match_operations(text: str, date_str: str, countries: list[str]) -> list[str]:
    """Match tweet to known operations by date + country + keyword context."""
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return []
    country_set = set(countries)
    matched = []
    for rule in OPERATION_RULES:
        start = datetime.strptime(rule["start"], "%Y-%m-%d")
        end = datetime.strptime(rule["end"], "%Y-%m-%d")
        if not (start <= dt <= end):
            continue
        # Check country overlap
        has_country = bool(country_set & rule["countries"])
        # Check keyword match
        has_keyword = any(kw.search(text) for kw in rule["keywords"])
        if has_country and has_keyword:
            matched.append(rule["name"])
        elif has_keyword and not rule.get("require_any", False):
            # For ops that don't require country match, keyword alone suffices
            matched.append(rule["name"])
    return matched


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Classify Spectator Index tweets into war/operations subsets.")
    parser.add_argument("--input", default="data/raw_data/spectator_index_tweets.csv", help="Input CSV path")
    parser.add_argument("--output-dir", default="data", help="Output directory for CSVs")
    parser.add_argument("--dry-run", action="store_true", help="Print stats without writing files")
    parser.add_argument("--verbose", action="store_true", help="Print sample matches per category")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)

    # Load CSV
    rows = []
    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    print(f"Loaded {len(rows)} tweets from {input_path}")

    # Classify each tweet
    results = []
    category_counts: dict[str, int] = {}
    category_samples: dict[str, list[str]] = {}
    stats_filtered = 0
    no_category = 0

    for row in rows:
        text = row.get("full_text", "")
        date = row.get("created_at", "")

        countries = extract_countries(text)
        categories = classify_tweet(text)
        operations = match_operations(text, date, countries)

        if is_statistics_table(text):
            stats_filtered += 1
        if not categories:
            no_category += 1

        for cat in categories:
            category_counts[cat] = category_counts.get(cat, 0) + 1
            if cat not in category_samples:
                category_samples[cat] = []
            if len(category_samples[cat]) < 5:
                category_samples[cat].append(text[:120])

        results.append({
            "created_at": date,
            "full_text": text,
            "categories": ";".join(categories),
            "countries": ";".join(countries),
            "operations": ";".join(operations),
        })

    # Print summary
    print(f"\n--- Classification Summary ---")
    print(f"Total tweets:       {len(rows)}")
    print(f"Stats tables:       {stats_filtered} (filtered out)")
    print(f"No category (other):{no_category}")
    for cat in CATEGORY_PATTERNS:
        count = category_counts.get(cat, 0)
        pct = count / len(rows) * 100 if rows else 0
        print(f"  {cat:30s}: {count:5d} ({pct:5.1f}%)")

    # Operation matches
    op_counts: dict[str, int] = {}
    for r in results:
        for op in r["operations"].split(";"):
            if op:
                op_counts[op] = op_counts.get(op, 0) + 1
    if op_counts:
        print(f"\n--- Operation Matches ---")
        for op, count in sorted(op_counts.items(), key=lambda x: -x[1]):
            print(f"  {op:35s}: {count:5d}")

    # Verbose: sample matches
    if args.verbose:
        print(f"\n--- Sample Matches ---")
        for cat, samples in category_samples.items():
            print(f"\n  [{cat}]")
            for s in samples:
                print(f"    - {s}")

    if args.dry_run:
        print("\n(dry run — no files written)")
        return

    # Write combined CSV
    output_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = ["created_at", "full_text", "categories", "countries", "operations"]

    combined_path = output_dir / "spectator_tweets_classified.csv"
    with open(combined_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote {len(results)} rows to {combined_path}")

    # Write per-category subsets
    for cat in CATEGORY_PATTERNS:
        subset = [r for r in results if cat in r["categories"].split(";")]
        if not subset:
            continue
        cat_path = output_dir / f"tweets_{cat}.csv"
        with open(cat_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(subset)
        print(f"Wrote {len(subset)} rows to {cat_path}")


if __name__ == "__main__":
    main()
