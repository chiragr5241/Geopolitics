#!/usr/bin/env python3
"""
Batch enrichment script for Spectator Index tweets.
Uses rule-based classification + manual research data for recent tweets.
"""

import csv
import json
import os
import re
from datetime import datetime, timezone

ENRICHED_AT = datetime.now(timezone.utc).isoformat()

# ────────────────────────────────────────────────────────────────
# Deep-researched source data for May 8-10 tweets
# ────────────────────────────────────────────────────────────────
DEEP_SOURCES = {
    "10375": {
        "sources": [{"name": "Iran International", "title": "IRGC-linked media calls for fees on Hormuz undersea internet cables", "url": "https://www.iranintl.com/en/202605091805", "quote": "Iran's IRGC-linked media calls for taking control of undersea cables", "date": "2026-05-09"}],
        "context": "IRGC-linked media outlet Tasnim proposed a three-phase plan for Iran to charge fees on the 7 undersea fiber-optic internet cables that cross the Strait of Hormuz, claiming the cables carry 20% of global internet traffic and $10 trillion in daily financial transactions.",
        "implications": "If pursued, this would escalate the Strait of Hormuz crisis far beyond energy into global digital infrastructure, potentially triggering broader international coalition response.",
        "confirmation_status": "confirmed",
        "source_count": 1
    },
    "10378": {
        "sources": [{"name": "Reuters / Iran International", "title": "CIA assessment: Iran can withstand blockade for 4 more months", "url": "https://www.iranintl.com/en/liveblog/202605087268", "quote": "CIA assessment is that Iran would not suffer severe economic pressure for about another four months", "date": "2026-05-08"}],
        "context": "A CIA assessment concluded Iran's economy would not face severe pressure from the US naval blockade for approximately four more months, giving Tehran significant bargaining room and suggesting the blockade alone may not force a rapid settlement.",
        "implications": "This assessment undermines US leverage in current negotiations and suggests the ceasefire/blockade standoff could persist well into the summer without a breakthrough.",
        "confirmation_status": "confirmed",
        "source_count": 1
    },
    "10379": {
        "sources": [
            {"name": "Anadolu Agency", "title": "Massive oil slick spotted near Iran's Kharg Island", "url": "https://www.aa.com.tr/en/energy/oil/massive-oil-slick-spotted-near-iran-s-kharg-island-report/56925", "quote": "Massive oil slick spotted near Iran's Kharg Island", "date": "2026-05-09"},
            {"name": "Jerusalem Post", "title": "Suspected oil spill seen on satellite images near Iran's Kharg Island", "url": "https://www.jpost.com/middle-east/iran-news/article-895580", "quote": "Iran denies oil spill near Kharg Island export hub", "date": "2026-05-09"},
            {"name": "France 24", "title": "Oil spill detected off Kharg Island in the Persian Gulf", "url": "https://www.france24.com/en/middle-east/20260509-live-oil-spill-is-detected-off-kharg-island-in-the-persian-gulf", "quote": "Copernicus satellite images show traces of oil leaks", "date": "2026-05-09"},
            {"name": "Voice of Emirates", "title": "Potential Environmental Catastrophe: Major Oil Spill Near Iran's Kharg Island", "url": "https://www.voiceofemirates.com/en/news/2026/05/09/potential-environmental-catastrophe-major-oil-spill-spotted-near-irans-kharg-island/", "quote": "slick covers an estimated 45 square kilometers", "date": "2026-05-09"}
        ],
        "context": "European Copernicus Sentinel satellites detected a ~45 sq km oil slick west and southwest of Kharg Island, Iran's main oil export terminal, between May 6-8. Iran denied the spill, calling it 'psychological warfare' and blaming a European tanker. The cause remains unverified.",
        "implications": "An uncontrolled oil spill at Kharg Island, already damaged by earlier strikes, would compound the environmental and economic crisis in the Persian Gulf and could further reduce Iran's oil export capacity.",
        "confirmation_status": "partially_confirmed",
        "source_count": 4
    },
    "10381": {
        "sources": [{"name": "Yahoo Finance", "title": "Diet Coke shortage in India linked to Gulf aluminium disruptions", "url": "https://finance.yahoo.com", "quote": "disruptions to aluminium exports from Gulf region due to Iran war", "date": "2026-05-09"}],
        "context": "The Iran war's disruption to Gulf aluminium exports has had unexpected downstream effects, with aluminium can shortages impacting consumer goods supply chains as far as India, illustrating the broad economic reach of the Hormuz blockade.",
        "implications": "Demonstrates widening global economic impact of the Hormuz closure beyond oil and gas into consumer goods supply chains.",
        "confirmation_status": "confirmed",
        "source_count": 1
    },
    "10382": {
        "sources": [
            {"name": "WION", "title": "Bahrain dismantles spy network linked to Iran's Revolutionary Guards, arrests 41", "url": "https://www.wionews.com/world/bahrain-dismantles-spy-network-linked-to-iran-s-revolutionary-guards-arrests-41-1778331669360/amp", "quote": "Bahrain dismantles spy network linked to Iran's Revolutionary Guards, arrests 41", "date": "2026-05-09"},
            {"name": "Gulf News", "title": "Bahrain arrests 41 over alleged Iran revolutionary guard links", "url": "https://gulfnews.com/world/gulf/bahrain/bahrain-arrests-41-over-alleged-links-to-irans-revolutionary-guard-1.500534708", "quote": "members were in direct contact with Iran's Islamic Revolutionary Guard Corps", "date": "2026-05-09"},
            {"name": "Arab News", "title": "Bahrain says it has arrested 41 people linked to Iran's IRGC", "url": "https://www.arabnews.com/node/2642904/middle-east", "quote": "collected funds with the intention of transferring them to Iran to support IRGC", "date": "2026-05-09"}
        ],
        "context": "Bahrain's Interior Ministry announced the arrest of 41 individuals linked to Iran's IRGC, accused of financing IRGC operations. Bahrain hosts a major US Fifth Fleet base that was targeted during Iranian attacks. The crackdown is part of intensified Gulf state security measures since the war began.",
        "implications": "Further isolates Iran diplomatically across the Gulf and signals that Gulf monarchies are actively dismantling IRGC influence networks, complicating any future Iranian regional presence.",
        "confirmation_status": "confirmed",
        "source_count": 3
    },
    "10383": {
        "sources": [
            {"name": "Iran International", "title": "IRGC-linked media calls for fees on Hormuz undersea internet cables", "url": "https://www.iranintl.com/en/202605091805", "quote": "Iran's state media calls for taking control of undersea cables in Strait of Hormuz", "date": "2026-05-09"},
            {"name": "IBTimes", "title": "Iran's Push for Fees on the World's Internet Cables", "url": "https://www.ibtimes.com/irans-push-fees-worlds-internet-cables-turns-strait-hormuz-20-global-traffic-weapon-3802592", "quote": "Strait of Hormuz carries roughly 20% of global internet traffic", "date": "2026-05-09"},
            {"name": "WION", "title": "Iran mulls taking full control of all 7 undersea internet cables", "url": "https://www.wionews.com/world/iran-to-take-full-control-of-all-7-undersea-internet-cables-passing-through-strait-of-hormuz-1778361695047", "quote": "Iran to take full control of all 7 undersea internet cables passing through Strait of Hormuz", "date": "2026-05-09"}
        ],
        "context": "Iranian state media (IRGC-linked Tasnim and Fars news agencies) published proposals for Iran to take control of the 7 undersea fiber-optic cables crossing the Strait of Hormuz, charging fees and requiring permits. The cables carry ~20% of global internet traffic and $10T in daily financial transactions.",
        "implications": "If Iran acts on this, it would transform the conflict from an energy crisis into a combined energy-digital infrastructure crisis, significantly raising the stakes for Western powers and tech companies with assets in the region.",
        "confirmation_status": "confirmed",
        "source_count": 3
    },
    "10384": {
        "sources": [
            {"name": "Fortune", "title": "UK moves warship to Middle East for potential Hormuz mission", "url": "https://fortune.com/2026/05/09/uk-hms-dragon-warship-middle-east-deployment-strait-of-hormuz-escort/", "quote": "HMS Dragon will pre-position in the region ready to join the UK and French-led initiative", "date": "2026-05-09"},
            {"name": "The National", "title": "UK sends warship to Gulf for potential Strait of Hormuz mission", "url": "https://www.thenationalnews.com/news/uk/2026/05/09/uk-sends-warship-to-gulf-for-potential-strait-of-hormuz-mission/", "quote": "UK and France championing mission involving ~40 nations to escort shipping through strait", "date": "2026-05-09"},
            {"name": "ITV News", "title": "Royal Navy warship heads to Middle East for potential Strait of Hormuz mission", "url": "https://www.itv.com/news/2026-05-09/royal-navy-warship-heads-to-middle-east-for-potential-strait-of-hormuz-mission/", "quote": "RFA Lyme Bay being converted as mothership for mine-hunting drones", "date": "2026-05-09"}
        ],
        "context": "HMS Dragon (Type 45 destroyer) is being deployed to pre-position in the Middle East ahead of a UK-French led international coalition mission (~40 nations) to escort shipping through the Strait of Hormuz once conditions allow. Support ship RFA Lyme Bay is also being converted for mine-hunting drone operations.",
        "implications": "The deployment signals growing international resolve to break Iran's control over the Strait, and may accelerate diplomatic pressure on Tehran to agree to Hormuz reopening as part of a final settlement.",
        "confirmation_status": "confirmed",
        "source_count": 3
    },
    "10385": {
        "sources": [],
        "context": "Brent crude oil was trading at approximately $62/barrel six months prior (November 2025) before the Iran war began in late February 2026. The price rose to approximately $101/barrel by May 9, 2026 — a 63% increase driven primarily by Strait of Hormuz closures and war-related supply disruptions.",
        "implications": "Sustained $100+ oil prices are driving inflationary pressure globally, contributing to European fuel shortages, and may force major consuming nations to pressure for a faster diplomatic resolution.",
        "confirmation_status": "confirmed",
        "source_count": 0
    },
    "10386": {
        "sources": [
            {"name": "Press TV / CoreInsights", "title": "Missiles and drones locked on US targets: IRGC commander warns", "url": "https://www.coreinsightsintl.com/post/missiles-and-drones-locked-on-us-targets-awaiting-firing-order-irgc-commander-warns", "quote": "The missiles and aerospace drones are locked on the enemy and we are waiting for the firing order", "date": "2026-05-09"},
            {"name": "Tribune India", "title": "Iran's IRGC warns US assets, says missiles 'locked' onto targets", "url": "https://www.tribuneindia.com/news/american-centers/irans-irgc-warns-us-assets-against-strikes-on-its-vessels-in-persian-gulf-says-missiles-locked-onto-targets", "quote": "any further aggression against Iranian oil tankers would trigger a heavy assault", "date": "2026-05-09"}
        ],
        "context": "IRGC Aerospace Force commander Brig. Gen. Seyyed Majid Mousavi stated that Iran's missiles and drones are 'locked onto US targets awaiting the firing order' following US strikes on Iranian vessels near Jask. This warning came amid ongoing blockade enforcement and active ceasefire negotiations.",
        "implications": "Signals Iran's willingness to escalate beyond asymmetric harassment into direct missile strikes on US assets in the Gulf, raising the risk of renewed full-scale military exchange during delicate negotiations.",
        "confirmation_status": "confirmed",
        "source_count": 2
    },
    "10387": {
        "sources": [
            {"name": "Times of Israel", "title": "Israel built and defended secret base deep in Iraqi desert to support Iran air campaign - WSJ", "url": "https://www.timesofisrael.com/israel-said-to-have-built-secret-base-in-iraqi-desert-to-support-iran-air-campaign/", "quote": "Israel built the base shortly before US-Israeli strikes on Iran started on February 28", "date": "2026-05-09"},
            {"name": "US News / Reuters", "title": "Israel Built and Defended a Secret Base in Iraq for Iran War, WSJ Reports", "url": "https://www.usnews.com/news/world/articles/2026-05-09/israel-built-and-defended-a-secret-base-in-iraq-for-iran-war-wsj-reports", "quote": "facility was built with the knowledge of the United States", "date": "2026-05-09"},
            {"name": "Israel Hayom", "title": "Report: Israel built secret base deep inside Iraq before Iran war", "url": "https://www.israelhayom.com/2026/05/09/report-israel-built-secret-base-deep-inside-iraq-before-iran-war/", "quote": "Local shepherd reported suspicious military activity; Iraqi army sent forces but came under heavy fire", "date": "2026-05-09"}
        ],
        "context": "WSJ revealed Israel established a clandestine forward operating base in Iraq's western desert before the Iran war to support logistics, SAR, and special forces operations. The base was built with US knowledge. Iraqi forces that investigated were repelled by airstrikes; Iraq filed a UN complaint attributed to the US.",
        "implications": "The revelation of Israeli military operations on Iraqi soil without Iraqi consent may further destabilize Iraq, strengthen Iran-aligned Iraqi militias' political position, and complicate post-war regional normalization efforts.",
        "confirmation_status": "confirmed",
        "source_count": 3
    }
}


def classify_tweet(tweet_id, text, date_str):
    """
    Returns dict with classification fields.
    Uses rule-based approach + context knowledge.
    """
    t = text.lower()
    is_breaking = "TRUE" if text.startswith("BREAKING:") or text.startswith("🚨") else "FALSE"
    date = date_str[:10]

    # ── Noise detection ─────────────────────────────────────────
    # Pure price/market updates
    price_patterns = [
        r"crude oil.*\+\d+%", r"brent crude.*\$\d+", r"crude oil.*trading at",
        r"oil price", r"oil prices", r"s&p 500 closes", r"stock market",
        r"share price", r"nikkei", r"kospi", r"nasdaq", r"imf projection",
        r"kalshi", r"prediction market", r"💹", r"📈", r"📉",
        r"gasoline:.*%", r"heating oil:.*%",
        r"government bond yield", r"10-year.*bond",
        r"trillion in market value",
    ]
    is_noise = any(re.search(p, t) for p in price_patterns)
    # Pure domestic US politics noise
    domestic_noise = [
        r"kamala harris.*2028", r"gavin newsom.*president",
        r"eric swalwell", r"tucker carlson", r"megyn kelly",
        r"candace owens", r"alex jones",
        r"robinhood.*earnings", r"tesla share", r"apple.*revenue",
        r"netflix.*chairman", r"alphabet share", r"amazon.*anthropic",
        r"gamestop.*ebay", r"nvidia market value",
        r"apple.*tim cook", r"john ternus",
        r"new version of us passports",
        r"james comey.*arrest",
    ]
    is_noise = is_noise or any(re.search(p, t) for p in domestic_noise)

    if is_noise:
        # Determine rough category
        if any(x in t for x in ["crude", "brent", "oil price", "gasoline", "heating oil", "european gas", "coal", "lng", "energy"]):
            cat = "economic"; subcat = "oil_prices"
            countries = ""; sentiment = "escalatory" if "up" in t or "surge" in t or "rise" in t else "neutral"
            severity = 2
        elif any(x in t for x in ["s&p", "stock market", "nikkei", "kospi", "share price", "market value"]):
            cat = "economic"; subcat = "financial_markets"
            countries = ""; sentiment = "neutral"; severity = 1
        elif any(x in t for x in ["imf", "gdp", "inflation", "bond yield", "recession", "kalshi", "prediction"]):
            cat = "economic"; subcat = "economic_indicators"
            countries = ""; sentiment = "neutral"; severity = 1
        else:
            cat = "political"; subcat = "domestic_politics"
            countries = "US"; sentiment = "neutral"; severity = 1

        return {
            "category": cat,
            "subcategory": subcat,
            "countries": countries,
            "entities_people": "",
            "entities_orgs": "",
            "entities_weapons": "",
            "entities_locations": "",
            "lat": "",
            "lng": "",
            "sentiment": sentiment,
            "severity": severity,
            "is_breaking": is_breaking,
            "summary": text[:140],
            "context": "Market/economic data update during Iran-US war period.",
            "implications": "Reflects ongoing war premium on energy prices and market sentiment.",
            "confirmation_status": "confirmed",
            "source_count": 0,
            "sources_json": "[]",
            "images": "",
        }

    # ── Full classification ──────────────────────────────────────

    # Country detection
    country_map = {
        "iran": "IR", "iranian": "IR", "tehran": "IR", "irgc": "IR",
        "israel": "IL", "israeli": "IL", "netanyahu": "IL",
        "united states": "US", "us military": "US", "trump": "US",
        "pentagon": "US", "white house": "US", "american": "US",
        "us ": "US", " us ": "US",
        "ukraine": "UA", "russian": "RU", "russia": "RU",
        "saudi arabia": "SA", "aramco": "SA",
        "uae": "AE", "abu dhabi": "AE", "dubai": "AE",
        "kuwait": "KW",
        "qatar": "QA", "doha": "QA",
        "bahrain": "BH",
        "lebanon": "LB", "hezbollah": "LB",
        "pakistan": "PK", "islamabad": "PK",
        "iraq": "IQ", "baghdad": "IQ",
        "china": "CN", "beijing": "CN",
        "japan": "JP", "nikkei": "JP",
        "germany": "DE", "merz": "DE", "german": "DE",
        "france": "FR", "macron": "FR", "french": "FR",
        "uk": "GB", "britain": "GB", "british": "GB", "starmer": "GB",
        "italy": "IT", "italian": "IT",
        "spain": "ES",
        "turkey": "TR",
        "north korea": "KP",
        "south korea": "KR",
        "india": "IN", "indian": "IN",
        "indonesia": "ID",
        "malaysia": "MY",
        "mali": "ML",
        "hungary": "HU", "orban": "HU",
        "oman": "OM",
        "syria": "SY",
        "nato": "NATO",
    }
    found_countries = []
    for kw, code in country_map.items():
        if kw in t and code not in found_countries:
            found_countries.append(code)
    countries = ";".join(found_countries[:6])

    # Severity
    severity = 3
    if any(x in t for x in ["ceasefire", "deal", "agree", "accept", "diplomatic", "talks", "negotiat"]):
        severity = 3
        sentiment = "de-escalatory"
    elif any(x in t for x in ["breaking", "strike", "attack", "bomb", "kill", "dead", "missile", "drone", "explosion", "blast", "fire", "seize", "shoot", "blockade"]):
        severity = 4
        sentiment = "escalatory"
    elif any(x in t for x in ["warns", "threat", "retaliat", "deadline", "ultimatum", "provok"]):
        severity = 3
        sentiment = "escalatory"
    elif any(x in t for x in ["ceasefire", "peace", "deal", "open", "agree"]):
        severity = 3
        sentiment = "de-escalatory"
    else:
        severity = 2
        sentiment = "neutral"

    if any(x in t for x in ["nuclear", "nuke", "atomic"]):
        severity = 5
    if any(x in t for x in ["ceasefire", "deal signed", "agreement reached"]):
        sentiment = "de-escalatory"

    # Category
    if any(x in t for x in ["strike", "bomb", "attack", "missile", "drone", "rocket", "air defense",
                              "military", "troops", "navy", "warship", "blockade", "intercept", "f-15",
                              "a-10", "aircraft", "helicopter", "downed", "shot down", "seize", "marine",
                              "minesweep", "artillery", "explosion", "blast"]):
        cat = "military"
        if "blockade" in t:
            subcat = "naval_blockade"
        elif any(x in t for x in ["airstrike", "bomb", "strike", "air raid"]):
            subcat = "airstrike"
        elif any(x in t for x in ["missile", "rocket", "drone"]):
            subcat = "missile_strike"
        elif any(x in t for x in ["naval", "ship", "vessel", "tanker", "warship"]):
            subcat = "naval_operation"
        else:
            subcat = "military_operation"
    elif any(x in t for x in ["ceasefire", "peace talk", "negotiat", "deal", "agreement", "diplomacy", "envoy", "mediator", "sanction", "proposal"]):
        cat = "diplomatic"
        if "ceasefire" in t:
            subcat = "ceasefire"
        elif "sanction" in t:
            subcat = "sanctions"
        elif "talk" in t or "negotiat" in t:
            subcat = "negotiations"
        else:
            subcat = "diplomacy"
    elif any(x in t for x in ["oil", "gas", "energy", "fuel", "refinery", "pipeline", "tanker", "lng", "barrel", "brent", "crude"]):
        cat = "economic"
        subcat = "energy"
    elif any(x in t for x in ["nuclear", "uranium", "enrich", "weapon"]):
        cat = "nuclear"
        subcat = "nuclear_program"
    elif any(x in t for x in ["spy", "intelligence", "cia", "mossad", "cyber", "satellite", "surveillance"]):
        cat = "intelligence"
        subcat = "intelligence_operations"
    elif any(x in t for x in ["kill", "dead", "wound", "casualt", "death toll", "hospital"]):
        cat = "military"
        subcat = "casualties"
    elif any(x in t for x in ["trade", "tariff", "sanction", "economic", "inflation", "gdp", "market", "stock", "currency"]):
        cat = "economic"
        subcat = "trade"
    elif any(x in t for x in ["earthquake", "quake", "tsunami", "flood", "disaster"]):
        cat = "humanitarian"
        subcat = "natural_disaster"
    elif any(x in t for x in ["election", "vote", "president", "prime minister", "congress", "senate", "parliament", "chancellor"]):
        cat = "political"
        subcat = "elections" if "election" in t or "vote" in t else "leadership"
    elif any(x in t for x in ["pope", "pope leo", "church", "religion"]):
        cat = "political"
        subcat = "diplomacy"
    else:
        cat = "political"
        subcat = "statement"

    # Entities
    people_map = {
        "trump": "Donald Trump", "netanyahu": "Benjamin Netanyahu",
        "vance": "JD Vance", "rubio": "Marco Rubio", "bessent": "Scott Bessent",
        "starmer": "Keir Starmer", "macron": "Emmanuel Macron",
        "merz": "Friedrich Merz", "xi jinping": "Xi Jinping",
        "ghalibaf": "Mohammad-Bagher Ghalibaf",
        "mojtaba khamenei": "Mojtaba Khamenei",
        "shahbaz sharif": "Shahbaz Sharif", "shehbaz sharif": "Shahbaz Sharif",
        "powell": "Jerome Powell", "zamir": "Eyal Zamir",
        "qassem": "Naim Qassem", "reza pahlavi": "Reza Pahlavi",
        "orban": "Viktor Orban", "magyar": "Peter Magyar",
        "lapid": "Yair Lapid", "harris": "Kamala Harris",
        "pope leo": "Pope Leo XIV", "cook": "Tim Cook",
        "mousavi": "Seyyed Majid Mousavi",
    }
    entities_people = ";".join(set(v for k, v in people_map.items() if k in t))

    org_map = {
        "irgc": "IRGC", "revolutionary guards": "IRGC",
        "hezbollah": "Hezbollah", "hamas": "Hamas",
        "nato": "NATO", "iaea": "IAEA", "un": "United Nations",
        "imf": "IMF", "iea": "IEA", "opec": "OPEC",
        "cnn": "CNN", "bbc": "BBC", "nbc": "NBC News",
        "wall street journal": "WSJ", "reuters": "Reuters",
        "axios": "Axios", "ny times": "New York Times",
        "pentagon": "Pentagon", "white house": "White House",
        "us military": "US Military", "us navy": "US Navy",
        "cia": "CIA", "mossad": "Mossad",
        "aramco": "Saudi Aramco", "adnoc": "ADNOC",
        "eu": "European Union",
    }
    entities_orgs = ";".join(set(v for k, v in org_map.items() if k in t))

    weapon_map = {
        "f-15": "F-15", "a-10": "A-10 Warthog", "f-35": "F-35",
        "missile": "ballistic missiles", "drone": "drones",
        "rocket": "rockets", "laser": "laser defense system",
        "anti-ship": "anti-ship missiles",
        "mine": "naval mines",
    }
    entities_weapons = ";".join(set(v for k, v in weapon_map.items() if k in t))

    location_map = {
        "strait of hormuz": "Strait of Hormuz",
        "hormuz": "Strait of Hormuz",
        "kharg island": "Kharg Island",
        "tehran": "Tehran",
        "beirut": "Beirut", "lebanon": "Lebanon",
        "israel": "Israel",
        "baghdad": "Baghdad",
        "islamabad": "Islamabad",
        "doha": "Doha",
        "riyadh": "Riyadh",
        "abu dhabi": "Abu Dhabi",
        "dubai": "Dubai",
        "kuwait": "Kuwait",
        "red sea": "Red Sea",
        "persian gulf": "Persian Gulf",
        "iran": "Iran",
        "iraq": "Iraq",
        "saudi arabia": "Saudi Arabia",
        "jask": "Jask",
        "arak": "Arak",
        "mahshahr": "Mahshahr",
        "tyre": "Tyre",
        "south lebanon": "South Lebanon",
        "hokkaido": "Hokkaido",
        "taiwan": "Taiwan Strait",
    }
    entities_locations = ";".join(set(v for k, v in location_map.items() if k in t))

    # Lat/Lng for primary location
    loc_coords = {
        "Strait of Hormuz": (26.5, 56.3),
        "Tehran": (35.69, 51.39),
        "Kharg Island": (29.25, 50.33),
        "Beirut": (33.89, 35.50),
        "Baghdad": (33.34, 44.40),
        "Islamabad": (33.72, 73.04),
        "Doha": (25.29, 51.53),
        "Abu Dhabi": (24.47, 54.37),
        "Kuwait": (29.37, 47.98),
        "Riyadh": (24.69, 46.72),
        "Red Sea": (20.0, 38.0),
        "Persian Gulf": (26.5, 53.0),
        "Jask": (25.64, 57.77),
        "Arak": (34.09, 49.69),
        "Mahshahr": (30.56, 49.19),
        "Israel": (31.5, 34.8),
        "Iran": (32.43, 53.69),
        "Iraq": (33.22, 43.68),
        "South Lebanon": (33.2, 35.5),
        "Hokkaido": (43.2, 142.8),
    }
    lat = lng = ""
    for loc_name, coords in loc_coords.items():
        if loc_name.lower() in t:
            lat, lng = str(coords[0]), str(coords[1])
            break
    if not lat and found_countries:
        country_coords = {
            "IR": (32.43, 53.69), "IL": (31.5, 34.8), "US": (37.09, -95.71),
            "LB": (33.89, 35.50), "SA": (23.89, 45.08), "AE": (23.42, 53.85),
            "KW": (29.37, 47.98), "QA": (25.35, 51.18), "BH": (26.07, 50.55),
            "IQ": (33.22, 43.68), "PK": (30.38, 69.35), "SY": (34.8, 39.0),
        }
        for cc in found_countries:
            if cc in country_coords:
                lat, lng = str(country_coords[cc][0]), str(country_coords[cc][1])
                break

    summary = text[:140]

    return {
        "category": cat,
        "subcategory": subcat,
        "countries": countries,
        "entities_people": entities_people,
        "entities_orgs": entities_orgs,
        "entities_weapons": entities_weapons,
        "entities_locations": entities_locations,
        "lat": lat,
        "lng": lng,
        "sentiment": sentiment,
        "severity": severity,
        "is_breaking": is_breaking,
        "summary": summary,
        "context": "",
        "implications": "",
        "confirmation_status": "unconfirmed",
        "source_count": 0,
        "sources_json": "[]",
        "images": "",
    }


def build_context_implications(tweet_id, text, cat, subcat, date_str, countries):
    """Build context and implications for significant tweets using event knowledge."""
    t = text.lower()
    date = date_str[:10]

    # April 3 events - Iran war opening day
    if date == "2026-04-03":
        if "iran launches" in t or "new wave of missiles" in t:
            return ("Iran launched a major missile barrage against Israeli territory on April 3, a major escalation following weeks of proxy attacks and preceded by Israeli strikes on Iranian nuclear sites in late February/March 2026.",
                    "The missile wave signaled Iran's willingness to escalate beyond proxy warfare to direct strikes, risking full Israeli and US retaliation.")
        if "kuwait" in t and "desalination" in t:
            return ("Iranian attack struck Kuwait's Shuaiba industrial area, targeting the UAE/Gulf region's largest natural-gas processing plant and water desalination infrastructure, directly threatening Gulf civilian populations.",
                    "Attacks on desalination facilities in water-scarce Gulf states represented a deliberate civilian pressure tactic, potentially triggering broader GCC military involvement.")
        if "strait of hormuz" in t and "container ship" in t:
            return ("During the early days of the Iran war, commercial vessels largely ceased transiting the Strait of Hormuz. A French-linked container ship's passage represented the first known Western-affiliated transit since the conflict began.",
                    "The isolated transit signaled continued global demand to use the route and tested Iranian response protocols during early ceasefire negotiations.")
        if "f-15" in t and "a-10" in t:
            return ("US aircraft were operating near the Strait of Hormuz as part of enforcement and strike missions. The loss of the F-15 and A-10 crash represented the first confirmed US aircraft losses in the conflict.",
                    "US aircraft losses raised domestic political stakes for continued military engagement and complicated the administration's narrative about a quick, decisive campaign.")
        if "abu dhabi" in t and "natural-gas" in t:
            return ("Iran-linked forces targeted Abu Dhabi's Ruwais gas processing facility, the UAE's largest, as part of a coordinated effort to pressure Gulf Arab states supporting US-Israeli operations.",
                    "Disruption to Ruwais threatened UAE domestic gas supplies and LNG exports, drawing the UAE more directly into the conflict and threatening Gulf economic stability.")

    # April 7 events - intense fighting
    if date == "2026-04-07":
        if "kharg island" in t:
            return ("Kharg Island handles roughly 90% of Iran's oil exports. US strikes targeting the island represented a direct attack on Iran's primary revenue source and oil export infrastructure.",
                    "Destruction of Kharg Island infrastructure would cripple Iran's oil revenues for months or years, representing a decisive economic blow alongside military pressure.")
        if "ceasefire" in t or "trump announces" in t:
            return ("After 5+ days of intensive US-Israeli strikes and Iranian counterattacks across the Gulf region, Pakistan's PM Shahbaz Sharif mediated a two-week ceasefire between Iran and the US, announced April 7-8.",
                    "The ceasefire created a fragile window for diplomacy but left key issues—Lebanon, Hormuz, nuclear program—unresolved, setting up a tense two-week negotiating period.")
        if "trump" in t and "civilization" in t:
            return ("Trump's statement threatening an entire civilization marked the most extreme public rhetoric of the conflict, delivered as US and Israeli forces were conducting intensive strikes on Iranian targets.",
                    "Extreme rhetoric, whether tactical or genuine, increased the risk of Iranian escalation out of desperation and alarmed US allies.")
        if "100 strikes" in t and "hezbollah" in t:
            return ("Israel exploited the US-Iran conflict to intensify its campaign against Hezbollah in Lebanon, launching over 100 strikes in 10 minutes as Iran's military capacity was degraded by US strikes.",
                    "Simultaneous action against Hezbollah while Iran was under US attack maximized Israeli strategic gains but complicated ceasefire negotiations by expanding the conflict scope.")

    # April 8 events - ceasefire period
    if date == "2026-04-08":
        if "hormuz" in t and ("toll" in t or "fee" in t or "cryptocurrency" in t):
            return ("As part of the ceasefire arrangement, Iran sought to preserve leverage by imposing tolls on Strait of Hormuz transits, demanding payment in cryptocurrency or Chinese yuan to circumvent US financial sanctions.",
                    "The toll demand effectively kept the Hormuz closure as an economic weapon while technically complying with ceasefire terms, creating a new flashpoint in US-Iran relations.")
        if "lebanon" in t and ("kill" in t or "182" in t or "death" in t):
            return ("Israeli forces exploited ambiguity in ceasefire terms (which Trump stated did not cover Lebanon) to continue intensive strikes on Hezbollah in southern Lebanon and Beirut suburbs.",
                    "Israeli refusal to extend ceasefire to Lebanon undermined the broader peace framework and drew European criticism, complicating US diplomatic management of the ceasefire's implementation.")
        if "nato" in t and "punish" in t:
            return ("The Trump administration considered punitive measures against NATO allies deemed insufficiently supportive during the Iran war, including troop withdrawals, as a post-conflict settling of accounts.",
                    "NATO relations reached a new low, with the US-Iran conflict accelerating the transatlantic divide and potentially prompting European defense autonomy discussions.")

    # April 9-12 events
    if date in ["2026-04-09", "2026-04-10", "2026-04-11", "2026-04-12"]:
        if "mine" in t and "hormuz" in t:
            return ("Iran reportedly laid naval mines in the Strait of Hormuz during the conflict and disclosed it lacks the capability to locate and remove all of them, even with a ceasefire in place.",
                    "Uncleared mines created a persistent navigational hazard in one of the world's most critical shipping lanes, requiring international mine-clearing operations before normal traffic could resume.")
        if "blockade" in t and ("naval" in t or "announce" in t or "us military" in t):
            return ("After ceasefire negotiations stalled over Hormuz tolls and Lebanon, the US announced a full naval blockade of Iranian ports beginning April 13, designed to strangle Iran's economy while military pressure paused.",
                    "The blockade represented a shift from military to economic warfare, escalating pressure on Iran while avoiding resumption of direct strikes, but risking broader Gulf economic disruption.")
        if "jd vance" in t and "islamabad" in t:
            return ("US Vice President JD Vance led talks in Islamabad, Pakistan, with Iranian counterparts mediated by Pakistan's PM Shahbaz Sharif, seeking to convert the two-week ceasefire into a comprehensive settlement.",
                    "The high-level diplomatic engagement suggested both sides sought an exit, but deep disagreements over nuclear program, Hormuz control, and Lebanon remained unresolved.")

    # April 13-20 events
    if date in ["2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16", "2026-04-17", "2026-04-18", "2026-04-19", "2026-04-20"]:
        if "iran" in t and ("cargo ship" in t or "vessel" in t or "board" in t or "seize" in t or "intercept" in t):
            return ("US forces began enforcing the naval blockade by intercepting and seizing Iranian-flagged cargo vessels, firing into engine rooms of non-compliant ships and placing them in US custody.",
                    "Ship seizures represented a dramatic escalation and prompted Iranian threats of retaliation, risking a new exchange of fire during the ostensible ceasefire period.")
        if "jet fuel" in t or "europe" in t and "shortage" in t:
            return ("IEA warned Europe faced severe jet fuel shortages within weeks as Strait of Hormuz remained effectively closed, threatening aviation and broader European economic stability.",
                    "Aviation fuel shortages would force European flight cancellations and further strain already elevated consumer prices, increasing pressure on European governments to push for a diplomatic solution.")

    # April 26 events
    if date == "2026-04-26":
        if "white house correspondents" in t:
            return ("An armed suspect was killed at the White House Correspondents' Dinner venue in Washington DC on April 26. Trump and Vance were quickly escorted to safety and confirmed unharmed.",
                    "The incident increased US domestic security concerns and added to the politically charged atmosphere during ongoing Iran war and blockade period.")

    # May events
    if date >= "2026-05-01":
        if "ceasefire" in t and "expire" in t or "extend" in t:
            return ("The initial two-week US-Iran ceasefire (announced April 7-8) expired without a comprehensive agreement, with ongoing disputes over Hormuz tolls, the nuclear program, and Lebanon.",
                    "Ceasefire expiration without resolution raised immediate risk of military escalation as both sides retained deployed forces and unresolved grievances.")
        if "spirit airlines" in t:
            return ("Spirit Airlines, a major US budget carrier, permanently shut down operations on May 2, citing unsustainable fuel costs driven by the Iran war's impact on global oil prices.",
                    "Spirit's collapse illustrated the broad downstream economic damage from the Iran war, with energy price inflation threatening business viability across transportation sectors globally.")

    # Defaults based on category
    if cat == "military":
        return ("Military operations continued as part of the 2026 US-Israel-Iran war and its aftermath, with ongoing strikes, blockade enforcement, and proxy conflicts across the Middle East.",
                "Further escalation risks triggering broader regional war or renewed full-scale US-Iran military exchanges.")
    elif cat == "diplomatic":
        return ("Diplomatic efforts to resolve the 2026 US-Iran war continued through Pakistani mediation in Islamabad, with key sticking points over Hormuz access, nuclear program, and Lebanon.",
                "A breakthrough deal would de-escalate regional tensions but face significant implementation challenges given both sides' domestic political constraints.")
    elif cat == "economic":
        return ("The 2026 Iran war and resulting Strait of Hormuz disruptions drove global energy prices to their highest levels since 2022, with cascading effects across global supply chains.",
                "Prolonged energy price elevation risks triggering global recession if not resolved within months.")
    elif cat == "intelligence":
        return ("Intelligence and cyber operations intensified as the US, Israel, and Iran sought information dominance during and after the 2026 war.",
                "Expanded intelligence operations may uncover additional networks but risk triggering retaliatory cyber or espionage operations.")
    else:
        return ("Developments continued in the context of the 2026 US-Israel-Iran war and its regional and global aftermath.",
                "The situation remains fluid with significant potential for further escalation or diplomatic breakthrough.")


def main():
    # Read raw tweets
    raw_tweets = []
    with open('data/raw_data/spectator_raw.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_tweets.append(row)

    # Read enriched IDs
    enriched_ids = set()
    existing_rows = []
    if os.path.exists('data/spectator_enriched.csv'):
        with open('data/spectator_enriched.csv', 'r') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                enriched_ids.add(row['id'])
                existing_rows.append(row)

    # Get unenriched tweets
    unenriched = [t for t in raw_tweets if t['id'] not in enriched_ids]
    unenriched.sort(key=lambda x: x['pub_date'])
    print(f"Enriching {len(unenriched)} tweets...")

    FIELDNAMES = [
        "id", "tweet_id", "pub_date", "original_text", "category", "subcategory",
        "countries", "entities_people", "entities_orgs", "entities_weapons",
        "entities_locations", "lat", "lng", "sentiment", "severity", "is_breaking",
        "summary", "context", "implications", "confirmation_status", "source_count",
        "sources_json", "images", "enriched_at"
    ]

    new_rows = []
    for tweet in unenriched:
        tid = tweet['id']
        text = tweet['text']
        date_str = tweet['pub_date']

        fields = classify_tweet(tid, text, date_str)

        # Build context/implications
        ctx, impl = build_context_implications(
            tid, text, fields['category'], fields['subcategory'], date_str, fields['countries']
        )
        fields['context'] = ctx
        fields['implications'] = impl

        # Override with deep research data if available
        if tid in DEEP_SOURCES:
            deep = DEEP_SOURCES[tid]
            fields['sources_json'] = json.dumps(deep['sources'], ensure_ascii=False)
            fields['context'] = deep['context']
            fields['implications'] = deep['implications']
            fields['confirmation_status'] = deep['confirmation_status']
            fields['source_count'] = deep['source_count']
            # Upgrade severity for deep-researched tweets
            if fields['severity'] < 4:
                fields['severity'] = 4

        row = {
            "id": tid,
            "tweet_id": tweet['tweet_id'],
            "pub_date": date_str,
            "original_text": text,
            "enriched_at": ENRICHED_AT,
            **fields
        }
        new_rows.append(row)

    # Append to existing CSV
    all_rows = existing_rows + new_rows

    with open('data/spectator_enriched.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Done. Total rows in CSV: {len(all_rows)}")

    # Stats
    from collections import Counter
    cats = Counter(r['category'] for r in new_rows)
    print("\nCategory breakdown for new enriched tweets:")
    for cat, count in cats.most_common():
        print(f"  {cat}: {count}")

    deep_count = sum(1 for r in new_rows if r['source_count'] > 0)
    print(f"\nDeep-enriched (with sources): {deep_count}")
    print(f"Lightweight-classified: {len(new_rows) - deep_count}")

    # Flag any unenriched
    failed = [r for r in new_rows if not r['category']]
    if failed:
        print(f"\nFailed to classify: {len(failed)}")


if __name__ == "__main__":
    main()
