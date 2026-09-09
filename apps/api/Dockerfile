FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Keep the resolver version explicit so the image uses the committed uv.lock
# consistently in local and Render builds.
RUN pip install --no-cache-dir uv==0.12.10

COPY pyproject.toml uv.lock ./
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src

RUN uv sync --frozen --no-dev

EXPOSE 8000

# Render supplies PORT. The fallback keeps `docker run` useful locally.
CMD ["sh", "-c", "exec uvicorn memoryos.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
