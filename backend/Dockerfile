FROM python:3.12.16-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/data/ai_gateway.sqlite3
WORKDIR /srv
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 appgroup \
    && useradd --create-home --uid 10001 --gid 10001 appuser \
    && mkdir -p /data \
    && chown 10001:10001 /data
COPY app.py prompt.py db_admin.py rotate_encryption_key.py ./
COPY ai_gateway ./ai_gateway
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
