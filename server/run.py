"""어느 폴더에서 실행해도 되는 서버 실행 스크립트.

    python server/run.py          (레포 안에서)
    python C:\\Users\\grace\\sprint\\server\\run.py   (어디서든)

환경변수
    ADMIN_TOKEN      관리자 페이지 토큰   (기본값: dev-admin-token)
    INGEST_API_KEY   브리지 업로드 키     (기본값: dev-ingest-key)
    PORT / HOST      기본 8000 / 0.0.0.0
    SLEEP_DB_PATH    DB 파일 위치        (기본 server/data/sleep.db)
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))            # 실행 위치와 상관없이 server 패키지를 찾게 한다


def lan_ip() -> str:
    """폰에서 접속할 때 쓸 이 PC 의 LAN IP (인터넷 연결 없이도 추정)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> None:
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    admin = os.environ.get("ADMIN_TOKEN", "dev-admin-token")
    key = os.environ.get("INGEST_API_KEY", "dev-ingest-key")

    print("=" * 62)
    print("  DormX 백엔드 서버")
    print("=" * 62)
    print(f"  앱 첫 화면의 '서버 주소' 에 입력  :  http://{lan_ip()}:{port}")
    print(f"  API 문서(브라우저)                :  http://localhost:{port}/docs")
    print(f"  관리자 토큰                       :  {admin}")
    print(f"  브리지 API 키 (--api-key)         :  {key}")
    print(f"  DB 파일                           :  "
          f"{os.environ.get('SLEEP_DB_PATH', ROOT / 'server' / 'data' / 'sleep.db')}")
    if admin == "dev-admin-token" or key == "dev-ingest-key":
        print("  ! 기본 토큰을 쓰고 있습니다. 공유 네트워크에서는 ADMIN_TOKEN /")
        print("    INGEST_API_KEY 환경변수로 바꿔서 실행하세요.")
    print("  종료: Ctrl+C")
    print("=" * 62)

    uvicorn.run("server.app.main:app", host=host, port=port)


if __name__ == "__main__":
    main()
