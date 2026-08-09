#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESP32가 시리얼로 보내는 원문 라인을 해석하는 모듈.

기존 serial_csv_logger.py의 handle_line() 파싱 규칙을 그대로 이식했다:
  - "[진행상태] 시간:.. | 피부온도:.. | ..."  -> CSV 한 줄 + 실시간 상태 dict
  - "@RESULT,person,temp,sol,converged,bestTemp,bestSol,nextTemp" -> 세션 결과 dict
  - 그 외 "#", "=" 로 시작하거나 "ESP32" 를 포함하는 줄 -> 이벤트 로그 한 줄
CSV 헤더/컬럼 순서는 realtime_dashboard.py가 그대로 읽을 수 있도록 원본과 동일하게 유지한다.
"""

import datetime
import re

CSV_HEADERS = [
    "시간(초)", "피부온도(C)", "히터온도(C)", "목표온도(C)",
    "PWM(%)", "심박수(BPM)", "안전상태", "세션상태", "연속수면(분)", "수면판정",
]

# "[진행상태]" 라인에서 "|"로 나뉘는 필드들의 순서 (펌웨어 logCsv()와 동일한 순서)
_PROGRESS_KEYS = [
    "시간", "피부온도", "히터온도", "목표", "히터파워",
    "심박수", "안전", "세션", "연속수면(분)", "판정",
]

RESULT_RE = re.compile(
    r"@RESULT,(?P<person>[^,]+),(?P<session_temp>[^,]+),(?P<sol>[^,]+),"
    r"(?P<converged>[^,]+),(?P<best_temp>[^,]+),(?P<best_sol>[^,]+),(?P<next_temp>[^,]+)"
)

START_REJECTED_MARKER = "START 거부"


def now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="milliseconds")


def parse_progress_line(line: str):
    """'[진행상태] ...' 원문 한 줄 -> (csv_row, status_dict)."""
    parts = line.replace("[진행상태]", "").split("|")
    csv_row = []
    raw_values = {}
    for part, key in zip(parts, _PROGRESS_KEYS):
        if ":" not in part:
            continue
        val = part.split(":", 1)[1].strip()
        clean = val.replace("℃", "").replace("초", "").replace("%", "").replace("BPM", "")
        csv_row.append(clean)
        raw_values[key] = clean

    def _f(key):
        try:
            return float(raw_values[key])
        except (KeyError, ValueError):
            return None

    skin = _f("피부온도")
    heater = _f("히터온도")
    status = {
        "ts": now_iso(),
        "elapsed_sec": _f("시간"),
        # -99 는 펌웨어가 센서 이상(NaN)을 나타내기 위해 쓰는 값 (realtime_dashboard.py와 동일 규칙)
        "skin_temp_c": None if skin is not None and skin <= -98 else skin,
        "heater_temp_c": None if heater is not None and heater <= -98 else heater,
        "target_temp_c": _f("목표"),
        "heater_power_pct": _f("히터파워"),
        "heart_rate_bpm": _f("심박수"),
        "safety_state": raw_values.get("안전"),
        "session_state": raw_values.get("세션"),
        "sleep_minutes": _f("연속수면(분)"),
        "sleep_judgement": raw_values.get("판정"),
    }
    return csv_row, status


def parse_result_event(line: str):
    """'@RESULT,...' 이벤트 한 줄 -> 결과 dict (매칭 안되면 None)."""
    m = RESULT_RE.search(line)
    if not m:
        return None
    return {
        "ts": now_iso(),
        "person_id": m.group("person"),
        "session_temp_c": float(m.group("session_temp")),
        "sol_min": float(m.group("sol")),
        "converged": m.group("converged") == "1",
        "best_temp_c": float(m.group("best_temp")),
        "best_sol_min": float(m.group("best_sol")),
        "next_temp_c": float(m.group("next_temp")),
    }
