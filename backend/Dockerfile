# =============================================================================
# SR Switchgear ERP — production image
#
# Three stages. Only `runtime` ships: no compilers, no git, no headers, no
# Node, no node_modules, no test suite, no docs.
#
# Build context is the REPOSITORY ROOT, not backend/ — this stage copies from
# both backend/ and frontend/, which are siblings. Build it as:
#   docker build -f backend/Dockerfile -t srerp .          (from repo root)
# or via either compose file, which both already set context/dockerfile
# correctly: ../docker-compose.yml (context: ., dockerfile: backend/Dockerfile)
# and backend/compose.yaml (context: .., dockerfile: backend/Dockerfile).
# =============================================================================

# Bases are pinned by digest, not by tag. `python:3.12-slim` is a moving
# target: the same Dockerfile would build a different image next month, and a
# reproducible build is the difference between "it works in staging" being
# evidence and being a coincidence.
#
# Digests resolved 2026-08-24 from registry-1.docker.io:
#   python:3.12-slim  sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a
#   node:22-slim      sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436
# Re-resolve and update these when you deliberately want newer base packages.

# -----------------------------------------------------------------------------
# Stage 1 — build wheels
# -----------------------------------------------------------------------------
FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build dependencies live here and nowhere else. psycopg[binary] ships wheels,
# so in practice nothing compiles — but if a dependency ever does need a
# compiler, it is available in this stage and absent from the one that runs.
RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY backend/pyproject.toml ./
COPY backend/requirements.txt ./

RUN pip wheel --wheel-dir /wheels -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2 — build the SPA
#
# Vite builds with base: "/static/spa/" (frontend/vite.config.ts) to
# frontend/dist. config/settings/base.py mounts that directory under the same
# "spa" static prefix and ahead of templates/ in TEMPLATES["DIRS"], so the
# runtime stage's `render(request, "index.html")` picks up the real built
# shell with its hashed <script> tag, not the templates/index.html
# placeholder.
# -----------------------------------------------------------------------------
FROM node:22-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# -----------------------------------------------------------------------------
# Stage 3 — runtime
# -----------------------------------------------------------------------------
FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    DJANGO_STATIC_ROOT=/tmp/static

# libpq5 is the runtime half of libpq-dev; psql is here so an operator can
# diagnose a connection problem from inside the container without a rebuild.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libpq5 postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Non-root, fixed UID 1000 so a mounted volume's ownership is predictable.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin app

COPY --from=builder /wheels /wheels
COPY backend/requirements.txt ./
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels requirements.txt

WORKDIR /srv/app
COPY --chown=app:app backend/manage.py ./
COPY --chown=app:app backend/config/ ./config/
COPY --chown=app:app backend/apps/ ./apps/
COPY --chown=app:app backend/templates/ ./templates/
COPY --chown=app:app backend/docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --from=frontend-builder --chown=app:app /frontend/dist ./frontend/dist

RUN chmod +x /usr/local/bin/entrypoint.sh

# A fresh media_data volume (docker-compose.yml) is populated from whatever
# exists here at this path — without this, Docker creates the mountpoint as
# root, and every upload 500s (PermissionError) under the non-root app user.
RUN mkdir -p /srv/app/media && chown app:app /srv/app/media

USER app

EXPOSE 8000

# The health check touches PostgreSQL. A process that is up but cannot reach
# the database is not healthy — every request it serves will fail.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz/', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# exec'd by the entrypoint so gunicorn becomes PID 1 and receives signals.
# --worker-tmp-dir /dev/shm because the root filesystem is expected to be
# read-only apart from /tmp, and gunicorn's heartbeat file must be writable
# and fast.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--threads", "2", \
     "--worker-tmp-dir", "/dev/shm", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--timeout", "60", \
     "--graceful-timeout", "30"]
