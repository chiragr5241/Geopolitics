#!/usr/bin/env python3
"""
Daily pull of Spectator Index tweets → data/spectator_raw.csv + data/spectator_media.csv
Run from repo root: python3 scripts/pull_spectator.py
"""
import csv, re, json, os, sys
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request

def _load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

API_URL = "https://background-xmocz.ondigitalocean.app/spectator/tweets"
BEARER_TOKEN = os.environ.get("SPECTATOR_BEARER_TOKEN")
if not BEARER_TOKEN:
    sys.exit("ERROR: SPECTATOR_BEARER_TOKEN not set (env var or .env file)")
AUTH = f"Bearer {BEARER_TOKEN}"
RAW_CSV = "data/raw_data/spectator_raw.csv"
MEDIA_CSV = "data/raw_data/spectator_media.csv"
RAW_HEADERS = ["id", "tweet_id", "pub_date", "text", "slug", "comment_count", "urls"]
MEDIA_HEADERS = ["id", "tweet_id", "pub_date", "url"]


def strip_html(s):
    return re.sub(r'<[^>]+>', '', s).strip()


def extract_urls(s):
    return re.findall(r'https?://\S+', s)


def fetch_page(page, limit=100):
    req = Request(
        f"{API_URL}?page={page}&limit={limit}",
        headers={"Authorization": AUTH}
    )
    with urlopen(req) as r:
        return json.loads(r.read())


def main():
    # Load existing ids for dedup
    existing_ids = set()
    raw_rows = []
    if os.path.exists(RAW_CSV):
        with open(RAW_CSV, newline='') as f:
            for row in csv.DictReader(f):
                existing_ids.add(int(row['id']))
                raw_rows.append(row)

    media_rows = []
    if os.path.exists(MEDIA_CSV):
        with open(MEDIA_CSV, newline='') as f:
            media_rows = list(csv.DictReader(f))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    new_tweets = []
    new_media = []
    stop = False
    page = 1

    while not stop:
        data = fetch_page(page)
        tweets = data['data']
        if not tweets:
            break
        for t in tweets:
            pub = datetime.fromisoformat(t['pub_date'].replace('Z', '+00:00'))
            if pub < cutoff or int(t['id']) in existing_ids:
                stop = True
                break
            clean = strip_html(t['tweet_text'])
            urls = extract_urls(t['tweet_text'])
            new_tweets.append({
                "id": t['id'],
                "tweet_id": t['tweet_id'],
                "pub_date": t['pub_date'],
                "text": clean,
                "slug": t['slug'],
                "comment_count": t['comment_count'],
                "urls": ",".join(urls),
            })
            for u in urls:
                new_media.append({
                    "id": t['id'],
                    "tweet_id": t['tweet_id'],
                    "pub_date": t['pub_date'],
                    "url": u,
                })
        page += 1

    if not new_tweets:
        print("0 new tweets — nothing to write.")
        return

    # Merge, sort by pub_date ascending, write
    all_rows = raw_rows + new_tweets
    all_rows.sort(key=lambda r: r['pub_date'])

    with open(RAW_CSV, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=RAW_HEADERS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(all_rows)

    all_media = media_rows + new_media
    with open(MEDIA_CSV, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=MEDIA_HEADERS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(all_media)

    print(f"New tweets added: {len(new_tweets)}")
    print(f"URLs extracted:   {len(new_media)}")
    print(f"Date range: {new_tweets[0]['pub_date']} → {new_tweets[-1]['pub_date']}")


if __name__ == "__main__":
    main()
