FROM python:3.11-slim

ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY frontend/ ./frontend/
# Repo folder is `assets/` but runtime expects `/app/Assets/` (card templates).
COPY assets/ ./Assets/
RUN mkdir -p /app/data

# Python-based, not curl — curl is not installed in this image (see
# reference/container-health-check.md) and adding it just for this would be an
# unnecessary dependency when Python is already present.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
