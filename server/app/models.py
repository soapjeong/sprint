"""요청/응답 스키마."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# 기기 ID 는 칩 MAC 에서 만들어지므로 영숫자만 쓴다
ID_PATTERN = r"^[A-Za-z0-9_.-]{2,32}$"
# 닉네임은 사람이 정하므로 한글도 받는다
NICKNAME_PATTERN = r"^[A-Za-z0-9가-힣ㄱ-ㅎㅏ-ㅣ_.-]{2,16}$"


MIN_PASSWORD_LEN = 4


class UserCreate(BaseModel):
    user_id: str = Field(pattern=NICKNAME_PATTERN, description="닉네임 (한글/영문/숫자, 2~16자)")
    name: str = Field(default="", max_length=64)
    password: str = Field(min_length=MIN_PASSWORD_LEN, max_length=128)


class LoginRequest(BaseModel):
    user_id: str = Field(pattern=NICKNAME_PATTERN)
    password: str = Field(min_length=1, max_length=128)


class AuthResult(BaseModel):
    """로그인/가입 성공 시 앱이 저장하는 값."""

    user: "UserOut"
    access_token: str


class DeviceRegister(BaseModel):
    device_id: str = Field(pattern=ID_PATTERN, description="기기 고유번호(칩 MAC 기반)")
    user_id: str = Field(pattern=NICKNAME_PATTERN)
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
    # 브리지가 알려주는 연결 상태: online | no_data | no_port | unknown
    link_state: str = "unknown"
    link_seen_at: Optional[str] = None
    battery_pct: Optional[float] = None


NOTE_CODES = ("alcohol", "caffeine", "none", "other")


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
    onset_at: Optional[str] = None
    failure_reason: Optional[str] = None
    start_source: str = "app"
    outcome: str
    rating: Optional[int] = None
    note_code: Optional[str] = None
    note_text: Optional[str] = None
    reviewed_at: Optional[str] = None


class TempStat(BaseModel):
    target_temp_c: float
    avg_sol_min: float
    onset_count: int


class SessionReview(BaseModel):
    """아침에 사용자가 남기는 수면 평가."""

    rating: int = Field(ge=1, le=5, description="별점 1~5")
    note_code: str = Field(description="alcohol | caffeine | none | other")
    note_text: str = Field(default="", max_length=200, description="note_code='other' 일 때 필수")

    @field_validator("note_code")
    @classmethod
    def _known_code(cls, v: str) -> str:
        if v not in NOTE_CODES:
            raise ValueError(f"note_code 는 {NOTE_CODES} 중 하나여야 합니다.")
        return v

    @model_validator(mode="after")
    def _other_needs_text(self) -> "SessionReview":
        if self.note_code == "other" and not self.note_text.strip():
            raise ValueError("'기타'를 고르면 내용을 적어야 합니다.")
        return self


class PendingDevice(BaseModel):
    device_id: str
    first_seen_at: str
    last_seen_at: str
    firmware: str = ""


class DeviceAnnounce(BaseModel):
    device_id: str = Field(pattern=ID_PATTERN)
    firmware: str = Field(default="", max_length=64)


class AnnounceResult(BaseModel):
    device_id: str
    registered: bool
    user_id: Optional[str] = None
    detail: str = ""


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
    # 아직 별점을 남기지 않은 가장 최근 세션(있으면 홈 화면에 평가 카드를 띄운다)
    pending_review: Optional[SessionOut] = None
    avg_rating: Optional[float] = None


LINK_STATES = ("online", "no_data", "no_port", "unknown")
COMMANDS = ("start", "abort", "off")


class CommandRequest(BaseModel):
    command: str = Field(description="start | abort | off")

    @field_validator("command")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in COMMANDS:
            raise ValueError(f"command 는 {COMMANDS} 중 하나여야 합니다.")
        return v


class CommandOut(BaseModel):
    command_id: int
    device_id: str
    command: str
    status: str
    created_at: str
    sent_at: Optional[str] = None
    acked_at: Optional[str] = None
    detail: str = ""


class CommandAck(BaseModel):
    status: str = Field(description="done | failed")
    detail: str = Field(default="", max_length=200)

    @field_validator("status")
    @classmethod
    def _ack(cls, v: str) -> str:
        if v not in ("done", "failed"):
            raise ValueError("status 는 done 또는 failed 여야 합니다.")
        return v


class HeartbeatIn(BaseModel):
    """브리지가 주기적으로 보내는 기기 연결 상태."""

    device_id: str = Field(pattern=ID_PATTERN)
    link_state: str = Field(default="unknown")
    battery_pct: Optional[float] = Field(default=None, ge=0, le=100)

    @field_validator("link_state")
    @classmethod
    def _state(cls, v: str) -> str:
        if v not in LINK_STATES:
            raise ValueError(f"link_state 는 {LINK_STATES} 중 하나여야 합니다.")
        return v


class DeviceStatus(BaseModel):
    """홈 화면이 5초마다 물어보는 '지금 기기가 어떤 상태인가'."""

    device: DeviceOut
    online: bool                      # link_seen_at 이 최근인지까지 반영한 값
    session: Optional["SessionOut"] = None      # 진행 중인 세션(없으면 None)
    session_state: Optional[str] = None         # WARMUP | RUNNING | COOLDOWN ...
    safety_state: Optional[str] = None
    skin_c: Optional[float] = None
    duty_pct: Optional[float] = None
    warmup_done: bool = False         # 센서 워밍업이 끝나 가온이 시작됐는가(TTS 시점)
    target_temp_c: Optional[float] = None
    pending_command: Optional[str] = None


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
    avg_rating: Optional[float] = None
    last_session_at: Optional[str] = None
