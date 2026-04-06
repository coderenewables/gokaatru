FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY server/ server/
COPY data/ data/

RUN pip install --no-cache-dir ".[ml]"

EXPOSE 8080

CMD ["python", "-m", "server.main", "--transport", "sse", "--host", "0.0.0.0", "--port", "8080"]
