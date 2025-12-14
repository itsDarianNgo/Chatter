FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir fastapi uvicorn[standard] redis jsonschema python-dotenv

COPY apps/chat_gateway ./apps/chat_gateway
COPY packages ./packages
COPY configs ./configs

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import sys,urllib.request; url='http://127.0.0.1:8080/healthz'; try: urllib.request.urlopen(url,timeout=3); except Exception: sys.exit(1); sys.exit(0)"

CMD ["python", "-m", "apps.chat_gateway.src.main"]
