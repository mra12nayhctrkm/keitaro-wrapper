# --- frontend build ---
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- backend + built frontend ---
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    DATABASE_URL=sqlite+aiosqlite:////data/keitaro_wrapper.db

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist

RUN mkdir -p /data && useradd --system --uid 1000 app && chown app /data
USER app
VOLUME ["/data"]
EXPOSE 8000

# Apply migrations, then serve API + UI.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000"]
