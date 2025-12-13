FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install minimal runtime dependencies
RUN pip install --no-cache-dir fastapi uvicorn[standard] redis jsonschema

# Copy required application files
COPY apps/persona_workers ./apps/persona_workers
COPY packages ./packages
COPY configs ./configs
COPY pyproject.toml ./

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python - <<'PY'
import sys
import urllib.request
try:
    with urllib.request.urlopen('http://localhost:8090/healthz', timeout=2) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception:
    sys.exit(1)
PY

CMD ["python", "-m", "apps.persona_workers.src.main"]
