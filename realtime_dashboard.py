#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
realtime_dashboard.py
----------------------------------------------------------------------------
백엔드(backend/main.py, 구 serial_csv_logger.py 역할 흡수)가 생성하는
  - logs/sensor_YYYYMMDD_HHMMSS.csv   (실시간 센서 CSV)
  - logs/events_YYYYMMDD_HHMMSS.log   (@RESULT 등 이벤트 로그)
두 파일을 읽어서 실시간 모니터링 대시보드로 보여주는 Streamlit 앱입니다.
파일 포맷은 원본과 동일하므로 이 파일의 파싱 로직은 손대지 않았습니다.

실행 방법:
    streamlit run realtime_dashboard.py

필요 패키지:
    pip install streamlit pandas plotly requests
----------------------------------------------------------------------------
"""

import glob
import os
import re
import time

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# ============================================================================
# 0. 페이지 기본 설정
# ============================================================================
st.set_page_config(
    page_title="DormX 수면 실시간 모니터링",
    page_icon="🌙",
    layout="wide",
)

CSV_COLUMNS = [
    "시간(초)", "피부온도(C)", "히터온도(C)", "목표온도(C)",
    "PWM(%)", "심박수(BPM)", "안전상태", "세션상태", "연속수면(분)", "수면판정",
]
NUMERIC_COLUMNS = ["시간(초)", "피부온도(C)", "히터온도(C)", "목표온도(C)", "PWM(%)", "심박수(BPM)", "연속수면(분)"]

RESULT_RE = re.compile(
    r"\[(?P<ts>[^\]]+)\]\s*@RESULT,(?P<person>[^,]+),(?P<session_temp>[^,]+),"
    r"(?P<sol>[^,]+),(?P<converged>[^,]+),(?P<best_temp>[^,]+),"
    r"(?P<best_sol>[^,]+),(?P<next_temp>[^,]+)"
)

# ============================================================================
# 1. 사이드바 - 로그 폴더 / 새로고침 / 백엔드 주소 설정
# ============================================================================
st.sidebar.title("⚙️ 설정")

# 백엔드(backend/main.py)의 기본 로그 폴더(--logdir)와 동일한 값을 기본값으로 사용합니다.
logdir = st.sidebar.text_input("로그 폴더 경로", value="./logs")

auto_refresh = st.sidebar.checkbox("자동 새로고침 사용", value=True)
refresh_sec = st.sidebar.slider("새로고침 주기(초)", min_value=1, max_value=10, value=2)

st.sidebar.divider()
st.sidebar.caption(
    "backend/main.py(백엔드) 실행 시 만들어지는 `sensor_*.csv`, `events_*.log` "
    "중 가장 최근 파일을 자동으로 찾아서 보여줍니다."
)

st.sidebar.divider()
backend_url = st.sidebar.text_input("백엔드 주소", value="http://localhost:8000")


def get_phone_url(backend_base: str):
    """백엔드의 /api/network 를 조회해 폰에서 접속할 LAN URL을 만든다. 실패하면 None."""
    try:
        resp = requests.get(f"{backend_base.rstrip('/')}/api/network", timeout=1.5)
        resp.raise_for_status()
        info = resp.json()
        return f"http://{info['lan_ip']}:{info['http_port']}/"
    except Exception:
        return None


phone_url = get_phone_url(backend_url)

# ============================================================================
# 2. 최신 CSV / 이벤트 로그 파일 찾기
# ============================================================================
def find_latest(pattern):
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


csv_path = find_latest(os.path.join(logdir, "sensor_*.csv"))
log_path = find_latest(os.path.join(logdir, "events_*.log"))

if csv_path is None:
    st.warning(
        f"'{logdir}' 폴더에서 sensor_*.csv 파일을 찾을 수 없습니다. "
        "백엔드(python run.py)를 먼저 실행해서 로깅을 시작해주세요."
    )
    st.stop()


# ============================================================================
# 3. 센서 CSV 읽기
# ============================================================================
def load_sensor_csv(path):
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as e:
        st.error(f"CSV 읽기 오류: {e}")
        return pd.DataFrame(columns=CSV_COLUMNS)

    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # -99 는 로거가 NaN(센서 이상)을 표시하기 위한 값
    if "피부온도(C)" in df.columns:
        df.loc[df["피부온도(C)"] <= -98, "피부온도(C)"] = None
    if "히터온도(C)" in df.columns:
        df.loc[df["히터온도(C)"] <= -98, "히터온도(C)"] = None

    return df


df_sensor = load_sensor_csv(csv_path)


# ============================================================================
# 4. 이벤트 로그에서 @RESULT (입면 잠복기 / 추천 온도) 파싱
# ============================================================================
def load_results(path):
    rows = []
    if path is None or not os.path.exists(path):
        return pd.DataFrame(
            columns=["시각", "설정온도", "SOL(분)", "수렴여부", "최적온도", "최적SOL(분)", "다음추천온도"]
        )
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = RESULT_RE.search(line)
            if not m:
                continue
            rows.append(
                {
                    "시각": m.group("ts"),
                    "설정온도": float(m.group("session_temp")),
                    "SOL(분)": float(m.group("sol")),
                    "수렴여부": m.group("converged") == "1",
                    "최적온도": float(m.group("best_temp")),
                    "최적SOL(분)": float(m.group("best_sol")),
                    "다음추천온도": float(m.group("next_temp")),
                }
            )
    df = pd.DataFrame(rows)
    if not df.empty:
        df["시각"] = pd.to_datetime(df["시각"], errors="coerce")
    return df


df_results = load_results(log_path)

# ============================================================================
# 5. 상단 타이틀
# ============================================================================
title_col, link_col = st.columns([3, 1])
with title_col:
    st.title("🌙 ESP32 수면 온도 실시간 모니터링")
    st.caption(f"센서 CSV: `{csv_path}`   |   이벤트 로그: `{log_path or '없음'}`")
with link_col:
    if phone_url:
        st.link_button("📱 폰 컨트롤 페이지 열기", phone_url, use_container_width=True)
        st.caption(f"같은 Wi-Fi에서: {phone_url}")
    else:
        st.caption(f"백엔드({backend_url})에 연결할 수 없어 폰 링크를 표시할 수 없습니다.")
st.divider()

if df_sensor.empty:
    st.info("아직 수신된 센서 데이터가 없습니다. 잠시 후 다시 확인해주세요.")
else:
    latest = df_sensor.iloc[-1]

    # ------------------------------------------------------------------
    # 5-1. 현재 상태 지표 (심박수 / 피부온도 / 히터온도 / 목표온도)
    # ------------------------------------------------------------------
    st.subheader("📟 현재 상태")
    c1, c2, c3, c4, c5, c6 = st.columns(6)

    c1.metric("❤️ 현재 심박수", f"{latest['심박수(BPM)']:.0f} BPM" if pd.notna(latest["심박수(BPM)"]) else "—")
    c2.metric("🧑 현재 피부온도", f"{latest['피부온도(C)']:.1f} ℃" if pd.notna(latest["피부온도(C)"]) else "—")
    c3.metric("🔥 현재 히터온도", f"{latest['히터온도(C)']:.1f} ℃" if pd.notna(latest["히터온도(C)"]) else "—")
    c4.metric("🎯 목표 온도", f"{latest['목표온도(C)']:.1f} ℃" if pd.notna(latest["목표온도(C)"]) else "—")

    safety = str(latest.get("안전상태", "—"))
    session = str(latest.get("세션상태", "—"))
    c5.metric("🛡️ 안전상태", safety, delta=None, delta_color="off" if safety == "NORMAL" else "inverse")
    c6.metric("📋 세션상태", session)

    if safety != "NORMAL":
        st.error(f"⚠️ 안전 FAULT 상태입니다: {safety}. 하드웨어를 확인하고 'r' 명령으로 리셋하세요.")

    st.caption(
        f"연속 수면 에폭: {int(latest['연속수면(분)']) if pd.notna(latest['연속수면(분)']) else 0}  |  "
        f"수면판정: {latest.get('수면판정', '—')}  |  경과시간: {latest['시간(초)']:.0f}초"
    )

    st.divider()

    # ------------------------------------------------------------------
    # 5-2. 실시간 온도 / 심박수 추이 그래프
    # ------------------------------------------------------------------
    st.subheader("📈 실시간 센서 추이")
    tab1, tab2 = st.tabs(["온도 (피부/히터/목표)", "심박수"])

    with tab1:
        fig_temp = go.Figure()
        fig_temp.add_trace(go.Scatter(x=df_sensor["시간(초)"], y=df_sensor["피부온도(C)"],
                                       mode="lines", name="피부온도(C)", line=dict(color="#ff6b6b")))
        fig_temp.add_trace(go.Scatter(x=df_sensor["시간(초)"], y=df_sensor["히터온도(C)"],
                                       mode="lines", name="히터온도(C)", line=dict(color="#f7b733")))
        fig_temp.add_trace(go.Scatter(x=df_sensor["시간(초)"], y=df_sensor["목표온도(C)"],
                                       mode="lines", name="목표온도(C)", line=dict(color="#4e89ff", dash="dash")))
        fig_temp.update_layout(xaxis_title="경과 시간(초)", yaxis_title="온도(℃)", height=380,
                                legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig_temp, use_container_width=True)

    with tab2:
        fig_hr = px.line(df_sensor, x="시간(초)", y="심박수(BPM)")
        fig_hr.update_traces(line_color="#e63946")
        fig_hr.update_layout(xaxis_title="경과 시간(초)", yaxis_title="심박수(BPM)", height=380)
        st.plotly_chart(fig_hr, use_container_width=True)

    st.divider()

# ============================================================================
# 6. 입면 잠복기(SOL) 변화 + 오늘의 추천 온도
# ============================================================================
st.subheader("😴 입면 잠복기(SOL) 변화 및 추천 온도")

col_left, col_right = st.columns([2, 1])

with col_left:
    if df_results.empty:
        st.info("아직 확정된 입면(SOL) 기록이 없습니다. 세션이 완료되면 이곳에 표시됩니다.")
    else:
        fig_sol = px.scatter(
            df_results, x="시각", y="SOL(분)", color="수렴여부", size=[10] * len(df_results),
            hover_data=["설정온도", "최적온도", "다음추천온도"],
            color_discrete_map={True: "#2a9d8f", False: "#e76f51"},
        )
        fig_sol.add_trace(
            go.Scatter(x=df_results["시각"], y=df_results["SOL(분)"], mode="lines",
                       line=dict(color="rgba(120,120,120,0.4)"), showlegend=False)
        )
        fig_sol.update_layout(
            xaxis_title="세션 시각", yaxis_title="입면 잠복기 SOL(분)", height=380,
            legend_title_text="탐색 수렴 여부",
        )
        st.plotly_chart(fig_sol, use_container_width=True)

with col_right:
    if df_results.empty:
        st.metric("🌡️ 오늘 추천 온도", "데이터 부족")
        st.caption("첫 세션이 끝나야 추천 온도가 계산됩니다.")
    else:
        last_result = df_results.iloc[-1]
        st.metric("🌡️ 다음 추천 온도", f"{last_result['다음추천온도']:.1f} ℃")
        st.metric("🏆 현재까지 최적 온도", f"{last_result['최적온도']:.1f} ℃  ({last_result['최적SOL(분)']:.1f}분)")
        if last_result["수렴여부"]:
            st.success("✅ 탐색이 수렴했습니다. 이 온도를 계속 사용해도 좋습니다.")
        else:
            st.warning("🔎 아직 탐색 중입니다. 온도를 조정해가며 최적값을 찾고 있어요.")

    st.caption(f"총 세션 기록: {len(df_results)}회")

st.divider()

# ============================================================================
# 7. 최근 원본 데이터 (옵션)
# ============================================================================
with st.expander("📋 최근 센서 원본 데이터 보기"):
    if not df_sensor.empty:
        st.dataframe(df_sensor.tail(50), use_container_width=True, hide_index=True)
    else:
        st.write("데이터 없음")

st.caption(f"마지막 업데이트: {time.strftime('%Y-%m-%d %H:%M:%S')}")

# ============================================================================
# 8. 자동 새로고침
# ============================================================================
if auto_refresh:
    time.sleep(refresh_sec)
    st.rerun()
