FROM python:3.11-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev

COPY src/ ./src/
COPY api/ ./api/
COPY ui/ ./ui/
COPY results/ ./results/

ENV CSM_PUBLIC_MODE=true
ENV CSM_DATA_DIR=/app/data
ENV PYTHONPATH=/app/src

EXPOSE 8000 8080

CMD ["uv", "run", "python", "ui/main.py"]