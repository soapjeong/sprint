"""아주 단순한 토큰 인증.

- 관리자 페이지: X-Admin-Token 헤더 (환경변수 ADMIN_TOKEN)
- 시리얼 브리지 업로드: X-API-Key 헤더 (환경변수 INGEST_API_KEY)

데모/연구용 수준의 보호이며, 실제 서비스에서는 사용자별 계정 인증으로 교체해야 한다.
"""
from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException, status

DEFAULT_ADMIN_TOKEN = "dev-admin-token"
DEFAULT_INGEST_KEY = "dev-ingest-key"


def admin_token() -> str:
    return os.environ.get("ADMIN_TOKEN", DEFAULT_ADMIN_TOKEN)


def ingest_key() -> str:
    return os.environ.get("INGEST_API_KEY", DEFAULT_INGEST_KEY)


def require_admin(x_admin_token: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_admin_token, admin_token()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "관리자 토큰이 필요합니다.")


def require_ingest_key(x_api_key: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_api_key, ingest_key()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "업로드 API 키가 필요합니다.")
