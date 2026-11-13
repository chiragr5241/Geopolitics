"""
Geopolitics read API — FastAPI over the Neo4j mirror.

Run locally (from the repo root):

    api/.venv/bin/uvicorn main:app --app-dir api --port 8787 --reload

Endpoints (all GET, all read-only):

  /api/health                          liveness + the data's load stamp
  /api/bootstrap?scope=feed|full       ≙ data/feed.json | data/database.json
  /api/feed?before=&limit=&q=&story=   paged feed, newest first (cursor in `next`)
  /api/stories                         the story catalog, counters computed live
  /api/stories/{story_id}/timeline     merged + deduped timeline, every linked row
  /api/map                             incidents / operations / imagery / timeline
  /api/speeches/{session}              ≙ data/un_speeches/unga<N>.json
  /api/sources                         the source registry
  /api/un/reports?branch=&organ=&before=&limit=

Heavy payloads are built once per data load (see graph.load_stamp) and served
from memory with an ETag, so a 304 costs one tiny query at most.

Config (environment or the repo's .env): NEO4J_URI, NEO4J_USERNAME,
NEO4J_PASSWORD, NEO4J_DATABASE; API_CORS_ORIGINS (comma-separated, added to the
built-in GitHub Pages + localhost list).
"""

import gzip
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

import graph


@asynccontextmanager
async def lifespan(app):
    yield
    graph.close()


app = FastAPI(title='Geopolitics read API', version='1.0', lifespan=lifespan,
              docs_url='/api/docs', openapi_url='/api/openapi.json', redoc_url=None)

ORIGINS = ['https://chiragr5241.github.io'] + [
    o.strip() for o in graph.ENV.get('API_CORS_ORIGINS', '').split(',') if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_origin_regex=r'https?://(localhost|127\.0\.0\.1)(:\d+)?',
    allow_methods=['GET'],
    allow_headers=['*'],
    expose_headers=['ETag'],
    max_age=86400,
)


def _send(request, raw, gz=None, etag=None, max_age=60):
    headers = {'Cache-Control': f'public, max-age={max_age}', 'Vary': 'Accept-Encoding'}
    if etag:
        headers['ETag'] = etag
        if request.headers.get('if-none-match') == etag:
            return Response(status_code=304, headers=headers)
    if 'gzip' in request.headers.get('accept-encoding', '') and len(raw) > 1024:
        headers['Content-Encoding'] = 'gzip'
        raw = gz if gz is not None else gzip.compress(raw, compresslevel=6)
    return Response(content=raw, media_type='application/json', headers=headers)


def _json(request, payload, max_age=60):
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return _send(request, raw, max_age=max_age)


def _cached(request, key, build):
    stamp, raw, gz = graph.cache.get(key, build)
    return _send(request, raw, gz, etag=f'"{key}@{stamp}"')


# Sync (def) handlers: FastAPI runs them in its threadpool, which suits the
# blocking Neo4j driver.

@app.get('/api/health')
def health(request: Request):
    try:
        stamp = graph.load_stamp()
    except Exception as e:                      # noqa: BLE001 — report, don't crash
        return Response(json.dumps({'ok': False, 'error': type(e).__name__}),
                        status_code=503, media_type='application/json')
    return _json(request, {'ok': True, 'loaded_at': stamp}, max_age=0)


@app.get('/api/bootstrap')
def bootstrap(request: Request, scope: str = Query('feed', pattern='^(feed|full)$')):
    return _cached(request, f'bootstrap-{scope}', lambda: graph.bootstrap(scope))


@app.get('/api/feed')
def feed(request: Request,
         before: str | None = Query(None, max_length=200),
         limit: int = Query(100, ge=1, le=500),
         q: str | None = Query(None, max_length=200),
         story: str | None = Query(None, max_length=120)):
    return _json(request, graph.feed_page(before=before, limit=limit,
                                          text=(q or '').strip() or None, story=story))


@app.get('/api/stories')
def stories(request: Request):
    return _cached(request, 'stories', graph.stories)


@app.get('/api/stories/{story_id}/timeline')
def timeline(request: Request, story_id: str):
    def build():
        t = graph.story_timeline(story_id)
        return t if t is not None else {'missing': True}
    stamp, raw, gz = graph.cache.get(f'timeline-{story_id}', build)
    if raw == b'{"missing":true}':
        raise HTTPException(404, 'no such story')
    return _send(request, raw, gz, etag=f'"timeline-{story_id}@{stamp}"')


@app.get('/api/map')
def map_data(request: Request):
    return _cached(request, 'map', graph.map_payload)


@app.get('/api/speeches/{session}')
def speeches(request: Request, session: int):
    def build():
        s = graph.speeches(session)
        return s if s is not None else {'missing': True}
    stamp, raw, gz = graph.cache.get(f'speeches-{session}', build)
    if raw == b'{"missing":true}':
        raise HTTPException(404, 'no analysis for that session')
    return _send(request, raw, gz, etag=f'"speeches-{session}@{stamp}"')


@app.get('/api/sources')
def sources(request: Request):
    return _cached(request, 'sources', graph.sources)


@app.get('/api/un/reports')
def un_reports(request: Request,
               branch: str | None = Query(None, max_length=60),
               organ: str | None = Query(None, max_length=60),
               before: str | None = Query(None, max_length=40),
               limit: int = Query(100, ge=1, le=500)):
    return _json(request, graph.un_reports(branch=branch, organ=organ, before=before, limit=limit))
