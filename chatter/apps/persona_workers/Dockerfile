FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install minimal runtime dependencies
RUN pip install --no-cache-dir fastapi uvicorn[standard] redis jsonschema litellm

# Copy required application files
COPY apps/persona_workers ./apps/persona_workers
COPY packages ./packages
COPY configs ./configs
COPY pyproject.toml ./

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import sys,urllib.request; url='http://127.0.0.1:8090/healthz'; try: urllib.request.urlopen(url,timeout=3); except Exception: sys.exit(1); sys.exit(0)"

CMD ["python", "-m", "apps.persona_workers.src.main"]
