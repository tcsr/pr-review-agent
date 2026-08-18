FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[postgres]"

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY config.example.yaml ./config.yaml

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["python", "-m", "app.main"]
