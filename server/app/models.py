"""요청/응답 스키마."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

ID_PATTERN = r"^[A-Za-z0-9_.-]{2,32}$"


class UserCreate(BaseModel):
    user_id: str = Field(pattern=ID_PATTERN, description="사용자 ID (영문/숫자/._-, 2~32자)")
    name: str = Field(default="", max_length=64)


class DeviceRegister(BaseModel):
    device_id: str = Field(pattern=ID_PATTERN, description="기기 고유번호 (기기 뒷면 라벨)")
    user_id: str = Field(pattern=ID_PATTERN)
    label: str = Field(default="", max_length=64, description="사용자가 붙이는 기기 별칭")


class UserOut(BaseModel):
    user_id: str
    name: str
    created_at: str


class DeviceOut(BaseModel):
    device_id: str
    user_id: str
    label: str
    registered_at: str
    last_seen_at: Optional[str] = None


class SessionOut(BaseModel):
    session_id: int
    user_id: str
    device_id: str
    started_at: str
    ended_at: Optional[str] = None
    target_temp_c: Optional[float] = None
    resting_bpm: Optional[float] = None
    threshold_bpm: Optional[float] = None
    sol_min: Optional[float] = None
    outcome: str


class TempStat(BaseModel):
    target_temp_c: float
    avg_sol_min: float
    onset_count: int


class UserSummary(BaseModel):
    user: UserOut
    devices: list[DeviceOut]
    session_count: int
    onset_count: int
    avg_sol_min: Optional[float] = None
    best_sol_min: Optional[float] = None
    best_temp_c: Optional[float] = None
    temp_stats: list[TempStat]
    recent_sessions: list[SessionOut]


class EventIn(BaseModel):
    device_id: str = Field(pattern=ID_PATTERN)
    flag: str = Field(max_length=32)
    device_ms: int = 0
    values: list[float] = Field(default_factory=list)
    raw: str = Field(default="", max_length=512)

    @field_validator("values")
    @classmethod
    def _cap_values(cls, v: list[float]) -> list[float]:
        return v[:8]


class SampleIn(BaseModel):
    device_ms: int
    skin_c: Optional[float] = None
    heater_c: Optional[float] = None
    target_c: Optional[float] = None
    duty_pct: Optional[float] = None
    bpm: Optional[float] = None
    resting_bpm: Optional[float] = None
    threshold_bpm: Optional[float] = None
    sensor_state: Optional[str] = None
    safety_state: Optional[str] = None
    session_state: Optional[str] = None
    quiet_min: Optional[int] = None
    asleep: bool = False


class SampleBatch(BaseModel):
    device_id: str = Field(pattern=ID_PATTERN)
    samples: list[SampleIn] = Field(default_factory=list, max_length=500)


class IngestResult(BaseModel):
    stored: int
    skipped: int = 0
    session_id: Optional[int] = None
    detail: str = ""


class AdminUserRow(BaseModel):
    user_id: str
    name: str
    created_at: str
    device_count: int
    session_count: int
    onset_count: int
    avg_sol_min: Optional[float] = None
    last_session_at: Optional[str] = None
