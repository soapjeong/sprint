#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API 요청/응답에 쓰이는 pydantic 모델."""

from pydantic import BaseModel


class CommandRequest(BaseModel):
    cmd: str


class MockStatusRequest(BaseModel):
    elapsed_sec: float = 0
    skin_temp_c: float
    heater_temp_c: float
    target_temp_c: float
    heater_power_pct: float = 0
    heart_rate_bpm: float = 0
    safety_state: str = "NORMAL"
    session_state: str = "IDLE"
    sleep_minutes: int = 0
    sleep_judgement: str = "깨어있음"


class MockResultRequest(BaseModel):
    person_id: str = "default"
    session_temp_c: float
    sol_min: float
    converged: bool = True
    best_temp_c: float
    best_sol_min: float
    next_temp_c: float
