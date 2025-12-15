FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn[standard] redis jsonschema litellm python-dotenv

COPY apps/stream_perceptor ./apps/stream_perceptor
COPY packages ./packages
COPY configs ./configs
COPY prompts ./prompts
COPY data ./data
COPY pyproject.toml ./

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import sys,urllib.request,json; url='http://127.0.0.1:8100/healthz';\ntry:\n  data=json.loads(urllib.request.urlopen(url,timeout=3).read().decode('utf-8'))\n  sys.exit(0 if data.get('ok') is True else 1)\nexcept Exception:\n  sys.exit(1)\n"

CMD ["python", "-m", "apps.stream_perceptor.src.main"]

