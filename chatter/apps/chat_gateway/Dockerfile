FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir fastapi uvicorn[standard] redis jsonschema

COPY apps/chat_gateway ./apps/chat_gateway
COPY packages ./packages
COPY configs ./configs

CMD ["python", "-m", "apps.chat_gateway.src.main"]
