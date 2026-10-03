FROM node:22-alpine AS web
WORKDIR /build
COPY platform/web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY platform/web/ ./
RUN npm run build

FROM node:22-bookworm-slim AS review-clis
ARG TARGETARCH
RUN npm install --global --no-audit --no-fund \
    @openai/codex@0.157.0 \
    @google/gemini-cli@0.61.0
# Codex publishes the native executable as a platform-specific npm alias.
# Pin the matching build explicitly because npm can skip optional binaries.
RUN case "$TARGETARCH" in \
      arm64) codex_arch=arm64 ;; \
      amd64) codex_arch=x64 ;; \
      *) echo "Unsupported Codex target architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac && npm install --global --no-audit --no-fund \
      "@openai/codex-linux-${codex_arch}@npm:@openai/codex@0.157.0-linux-${codex_arch}"

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /workspace/platform/backend
COPY --from=review-clis /usr/local/bin/node /usr/local/bin/node
COPY --from=review-clis /usr/local/lib/node_modules/ /usr/local/lib/node_modules/
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && ln -s /usr/local/lib/node_modules/@google/gemini-cli/bundle/gemini.js /usr/local/bin/gemini
# Runtime dependencies only; development tools live in requirements-dev.txt and stay out of the image.
COPY platform/backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Application code, Alembic configuration and migrations (tests are excluded by .dockerignore).
COPY platform/backend/ ./
COPY platform/backend/app/worker/resources/gemini-deny-all.toml /etc/cuautoreview/gemini-deny-all.toml
COPY poc/data/ /workspace/poc/data/
COPY poc/runs/latest/ /workspace/poc/runs/latest/
COPY poc/runs/20260926-225934-c522c/proposals.json /workspace/poc/runs/20260926-225934-c522c/proposals.json
COPY platform/scripts/ /workspace/platform/scripts/
COPY platform/demo-data/*.zip platform/demo-data/manifest.json /workspace/platform/demo-data/
COPY --from=web /build/dist /workspace/platform/web/dist
RUN useradd --uid 10001 --create-home app && mkdir -p var /workspace/platform/.local \
    && chown -R app:app var /workspace/platform/.local \
    && chmod 0444 /etc/cuautoreview/gemini-deny-all.toml
USER app
EXPOSE 8000
# No image-level HEALTHCHECK: the same image runs the API, workers and the migrate job, so each Compose
# service defines its own probe (the API uses /api/ready).
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
