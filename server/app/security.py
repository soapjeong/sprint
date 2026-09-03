"""인증.

- 사용자 앱   : 비밀번호 로그인 후 받은 X-User-Token (사용자별)
- 관리자 페이지: X-Admin-Token 헤더 (환경변수 ADMIN_TOKEN)
- 시리얼 브리지: X-API-Key 헤더    (환경변수 INGEST_API_KEY)

인터넷에 공개된 서버에서는 기본 토큰을 그대로 쓰면 시작을 거부한다
(로컬 개발은 SLEEP_ALLOW_DEV_TOKENS=1 로 허용 — server/run.py 가 자동으로 켠다).
"""
from __future__ import annotations

import hashlib
import os
import secrets

from fastapi import Header, HTTPException, status

DEFAULT_ADMIN_TOKEN = "dev-admin-token"
DEFAULT_INGEST_KEY = "dev-ingest-key"

# scrypt 파라미터 (RFC 7914 권장 범위, 서버 부하와 균형)
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16

MIN_PASSWORD_LEN = 4


def admin_token() -> str:
    return os.environ.get("ADMIN_TOKEN", DEFAULT_ADMIN_TOKEN)


def ingest_key() -> str:
    return os.environ.get("INGEST_API_KEY", DEFAULT_INGEST_KEY)


def dev_tokens_allowed() -> bool:
    return os.environ.get("SLEEP_ALLOW_DEV_TOKENS", "") == "1"


def check_startup_config() -> list[str]:
    """기본 토큰을 그대로 쓰고 있으면 문제 목록을 돌려준다(빈 목록이면 정상)."""
    problems = []
    if admin_token() == DEFAULT_ADMIN_TOKEN:
        problems.append("ADMIN_TOKEN 이 기본값입니다.")
    if ingest_key() == DEFAULT_INGEST_KEY:
        problems.append("INGEST_API_KEY 가 기본값입니다.")
    return problems


# ---------------------------------------------------------------- 비밀번호
def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """(salt_hex, hash_hex) 를 돌려준다."""
    salt = salt or secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    _, digest = hash_password(password, salt)
    return secrets.compare_digest(digest, hash_hex)


def new_access_token() -> str:
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------- 의존성
def require_admin(x_admin_token: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_admin_token, admin_token()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "관리자 토큰이 필요합니다.")


def require_ingest_key(x_api_key: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_api_key, ingest_key()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "업로드 API 키가 필요합니다.")
