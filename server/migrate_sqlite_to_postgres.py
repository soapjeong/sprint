"""로컬 SQLite 에 쌓인 데이터를 PostgreSQL 로 옮긴다.

    python server/migrate_sqlite_to_postgres.py \
        --sqlite server/data/sleep.db \
        --postgres "postgresql://user:pw@ep-xxx.neon.tech/neondb?sslmode=require"

대상 PostgreSQL 이 비어 있다고 가정한다(이미 데이터가 있으면 --force 로 덮어쓴다).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 외래키 순서대로
TABLES = ["users", "auth_tokens", "devices", "sessions", "samples", "events", "pending_devices"]
# 자동 증가 키를 쓰는 테이블 (옮긴 뒤 시퀀스를 맞춰야 한다)
SEQUENCES = {"sessions": "session_id", "samples": "sample_id", "events": "event_id"}


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite -> PostgreSQL 데이터 이전")
    parser.add_argument("--sqlite", required=True, help="원본 SQLite 파일")
    parser.add_argument("--postgres", required=True, help="대상 PostgreSQL 연결 문자열")
    parser.add_argument("--force", action="store_true", help="대상 테이블을 비우고 옮긴다")
    args = parser.parse_args()

    import psycopg

    from server.app import db as appdb

    appdb.DATABASE_URL = args.postgres
    appdb.init_db()                      # 대상에 스키마부터 만든다

    src = sqlite3.connect(args.sqlite)
    src.row_factory = sqlite3.Row

    with psycopg.connect(args.postgres) as dst:
        if args.force:
            for table in reversed(TABLES):
                dst.execute(f"DELETE FROM {table}")

        for table in TABLES:
            rows = src.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"  {table}: 0")
                continue
            columns = rows[0].keys()
            placeholders = ",".join(["%s"] * len(columns))
            sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
            dst.cursor().executemany(sql, [tuple(r[c] for c in columns) for r in rows])
            print(f"  {table}: {len(rows)}")

        # 자동 증가 키가 옮겨온 최대값 다음부터 나오도록 맞춘다
        for table, column in SEQUENCES.items():
            dst.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'),"
                f" COALESCE((SELECT MAX({column}) FROM {table}), 1))"
            )
        dst.commit()

    src.close()
    print("이전 완료.")


if __name__ == "__main__":
    main()
