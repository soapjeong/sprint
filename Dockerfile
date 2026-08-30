# 클라우드 배포용 이미지 (Fly.io / Railway / Render / Cloud Run 공통)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SLEEP_DB_PATH=/data/sleep.db \
    PORT=8080

WORKDIR /app

COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server ./server

# SQLite 파일이 사는 곳. 배포 플랫폼에서 볼륨을 이 경로에 붙인다.
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8080

# ADMIN_TOKEN / INGEST_API_KEY 를 설정하지 않으면 서버가 기동을 거부한다(보안).
CMD ["sh", "-c", "uvicorn server.app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
