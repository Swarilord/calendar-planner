# Two stages: Node builds the React app, then a slim Python image runs the
# server with only the built files. Node and node_modules never reach the
# final image.

# --- Stage 1: build the frontend -------------------------------------------
FROM node:24-slim AS web
WORKDIR /web
# Dependencies first: this layer is cached until the lockfile changes.
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- Stage 2: the server -----------------------------------------------------
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# Dependencies first (cached), then our code: a code change doesn't reinstall.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY planner/ planner/
RUN uv sync --locked --no-dev
COPY --from=web /web/dist web/dist

# Never run as root inside the container.
RUN useradd --create-home planner
USER planner

# Secrets are NOT in the image: pass GOOGLE_API_KEY at run time
# (docker run -e ..., or Secret Manager on Cloud Run).
# The hosted demo uses the fake calendar (PLANNER_CALENDAR unset).
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn planner.api.main:app --host 0.0.0.0 --port ${PORT}"]
