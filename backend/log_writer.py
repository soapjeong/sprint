#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV/이벤트 로그 파일 저장 — serial_csv_logger.py의 SerialCsvLogger 파일 생성/기록 로직을 그대로 이식.
realtime_dashboard.py가 찾는 파일명 규칙(sensor_YYYYMMDD_HHMMSS.csv, events_YYYYMMDD_HHMMSS.log)과
컬럼 포맷을 그대로 유지한다.
"""

import csv
import datetime
import os

from .parsing import CSV_HEADERS


def _timestamp_tag() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class SessionLogWriter:
    def __init__(self, outdir: str):
        os.makedirs(outdir, exist_ok=True)
        tag = _timestamp_tag()
        self.csv_path = os.path.join(outdir, f"sensor_{tag}.csv")
        self.event_path = os.path.join(outdir, f"events_{tag}.log")

        # utf-8-sig: 엑셀에서 한글 CSV 깨짐 방지 (원본과 동일)
        self.csv_file = open(self.csv_path, "w", newline="", encoding="utf-8-sig")
        self.csv_writer = csv.writer(self.csv_file)
        self.event_file = open(self.event_path, "w", encoding="utf-8")
        self._header_written = False

    def write_progress_row(self, csv_row):
        if not self._header_written:
            self.csv_writer.writerow(CSV_HEADERS)
            self._header_written = True
        if csv_row:
            self.csv_writer.writerow(csv_row)
        self.csv_file.flush()

    def write_event_line(self, tagged_line: str):
        self.event_file.write(tagged_line + "\n")
        self.event_file.flush()

    def close(self):
        for f in (self.csv_file, self.event_file):
            try:
                f.close()
            except Exception:
                pass
