# API image. Build from the repo root:  docker build -f backend/Dockerfile -t oncall-api .
FROM python:3.12-slim

# HOI platform code for the fault simulator (public repo, pinned commit). Set HOI_REF="" to build without the simulator.
ARG HOI_REPO=https://github.com/Ashu-Stark/Hospitality-.git
ARG HOI_REF=a679ba4ad40da302d9a4c35aef0b172f0d6b7e02
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*  && if [ -n "$HOI_REF" ]; then git clone --filter=blob:none "$HOI_REPO" /srv/hoi && git -C /srv/hoi checkout "$HOI_REF"     && rm -rf /srv/hoi/.git /srv/hoi/website /srv/hoi/dashboard /srv/hoi/ml; fi
ENV HOI_PLATFORM_PATH=/srv/hoi/platform_api PYTHONUNBUFFERED=1 APP_ENV=production

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY copilot copilot
COPY harness harness
COPY runbooks runbooks
COPY eval/results.json eval/results.json
COPY backend backend

RUN useradd --create-home --uid 10001 app
USER app
EXPOSE 8000
# migrate, then serve; one worker because the simulator and the SSE poller are per-process
CMD ["sh", "-c", "alembic -c backend/alembic.ini upgrade head && uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
