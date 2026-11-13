# Read API image. Build from the REPO ROOT (it needs two pipeline modules):
#   docker build -f api/Dockerfile -t geopolitics-api .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

# graph.py imports these for the derived fields (badge colours, timeline,
# story counters), so the API computes them exactly as build_db.py does.
COPY scripts/build_db.py scripts/story_stats.py scripts/
COPY api/graph.py api/main.py api/

RUN useradd --system --no-create-home app
USER app

EXPOSE 8787
# PORT is set by Fly.io / Render / Railway / Cloud Run; 8787 otherwise.
CMD ["sh", "-c", "exec uvicorn main:app --app-dir api --host 0.0.0.0 --port ${PORT:-8787} --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips '*'"]
