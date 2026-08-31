"""관리자 대시보드를 단독으로 띄운다(API 서버와 별도 사이트로 운영할 때).

    python admin-web/serve.py            # http://localhost:8080
    python admin-web/serve.py --port 9000

API 서버에 이미 얹혀 있으므로(https://<서버>/admin/) 보통은 필요 없다.
"""
from __future__ import annotations

import argparse
import http.server
import os
from functools import partial

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    parser = argparse.ArgumentParser(description="DormX 관리자 대시보드 정적 서버")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    handler = partial(http.server.SimpleHTTPRequestHandler, directory=HERE)
    print(f"관리자 대시보드: http://localhost:{args.port}  (종료 Ctrl+C)")
    http.server.ThreadingHTTPServer(("0.0.0.0", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
