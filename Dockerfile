# 배포용 이미지 (Render / Railway / Cloud Run 등 Docker 를 받는 곳 공통)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server ./server
COPY admin-web ./admin-web

EXPOSE 8000

# DATABASE_URL 이 있으면 PostgreSQL, 없으면 컨테이너 안 SQLite(재배포 시 사라짐).
# ADMIN_TOKEN / INGEST_API_KEY 를 설정하지 않으면 서버가 기동을 거부한다(보안).
CMD ["sh", "-c", "uvicorn server.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
