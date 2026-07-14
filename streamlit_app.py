import streamlit as st
import pandas as pd
import plotly.express as px

# 1. 페이지 기본 설정
st.set_page_config(page_title="DormX Active 전용 대시보드", page_icon="🌙", layout="wide")

# ------------------------------------------------------------------
# 2. 사용자 3명 + 각자의 알고리즘 진행 단계(Phase) 메타 정보
# ------------------------------------------------------------------
USER_META = {
    'SUB_01': {
        'name': '조민서',
        'phase': 1,
        'phase_label': 'Phase 1 · 콜드스타트 적정 중',
        'progress': 30,
        'phenotype': None,
    },
    'SUB_02': {
        'name': '성수빈',
        'phase': 2,
        'phase_label': 'Phase 2 · 반응 표현형 분류 중',
        'progress': 60,
        'phenotype': '전기자극 민감 우세형 (잠정)',
    },
    'SUB_03': {
        'name': '정우빈',
        'phase': 3,
        'phase_label': 'Phase 3 · 온라인 적응 학습 중',
        'progress': 85,
        'phenotype': '열 민감 우세형',
    },
}

# ------------------------------------------------------------------
# 3. 피험자별 Active(가온) 조건 데이터 (확장됨)
# ------------------------------------------------------------------
@st.cache_data
def load_active_data():
    raw = {
        'SUB_01': {
            '날짜': ['7/9', '7/11'],
            '조건군': ['가온 단독(38℃)', '가온 단독(40℃)'],
            'SOL_입면시간(분)': [31, 27],
            '각성시간(분)': [12, 10],
            '깊은수면(%)': [14.2, 15.0],
            '코어수면(%)': [56.1, 55.4],
            'REM수면(%)': [26.5, 27.1],
        },
        'SUB_02': {
            '날짜': ['7/3', '7/5', '7/7', '7/9', '7/11', '7/13', '7/15', '7/17'],
            '조건군': ['가온 단독(40℃)', '가온+전기(40℃, 5Hz)', '가온+전기(40℃, 10Hz)', '가온+전기(42℃, 10Hz)', 
                      '가온+전기(42℃, 10Hz)', '가온+전기(42℃, 10Hz)', '가온+전기(42℃, 10Hz)', '가온+전기(42℃, 10Hz)'],
            'SOL_입면시간(분)': [26, 19, 15, 16, 14, 14, 13, 13],
            '각성시간(분)': [9, 7, 6, 7, 6, 6, 5, 5],
            '깊은수면(%)': [15.5, 16.8, 18.2, 17.9, 18.5, 18.8, 19.0, 19.1],
            '코어수면(%)': [55.0, 54.2, 53.6, 53.8, 53.0, 52.8, 52.5, 52.4],
            'REM수면(%)': [27.8, 27.9, 27.0, 27.2, 27.5, 27.6, 27.7, 27.8],
        },
        'SUB_03': {
            '날짜': ['7/4', '7/5', '7/7', '7/9', '7/11', '7/13', '7/15', '7/17', '7/19', '7/21', '7/23', '7/25', '7/27', '7/29', '7/31'],
            '조건군': ['가온 단독(40℃)', '가온+전기(40℃)', '가온+전기(45℃)', '가온+전기(45℃)', '가온+전기(45℃)', 
                      '가온+전기(45℃)', '가온+전기(45℃)', '가온+전기(45℃)', '가온+전기(45℃)', '가온+전기(45℃)', 
                      '가온+전기(45℃)', '가온+전기(45℃)', '가온+전기(45℃)', '가온+전기(45℃)', '가온+전기(45℃)'],
            'SOL_입면시간(분)': [22, 13, 22, 12, 11, 12, 11, 10, 11, 10, 10, 10, 10, 9, 9],
            '각성시간(분)': [3, 14, 8, 7, 7, 6, 6, 5, 5, 5, 4, 4, 4, 3, 3],
            '깊은수면(%)': [17.8, 17.0, 12.5, 18.0, 18.2, 18.5, 18.8, 19.0, 19.2, 19.3, 19.5, 19.6, 19.8, 20.0, 20.2],
            '코어수면(%)': [53.3, 54.3, 57.0, 52.5, 52.3, 52.0, 51.8, 51.6, 51.5, 51.3, 51.2, 51.1, 51.0, 50.8, 50.6],
            'REM수면(%)': [28.9, 28.7, 30.5, 29.5, 29.5, 29.5, 29.4, 29.4, 29.3, 29.4, 29.3, 29.3, 29.2, 29.2, 29.2],
        },
    }

    frames = []
    for sub_id, data in raw.items():
        df = pd.DataFrame(data)
        df.insert(0, '피험자ID', sub_id)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


df_all = load_active_data()

# ------------------------------------------------------------------
# 4. 세션 상태 초기화 및 사이드바 로직 (이전과 동일)
# ------------------------------------------------------------------
if 'user_role' not in st.session_state:
    st.session_state['user_role'] = '일반 사용자(개인용 뷰)'
if 'selected_user' not in st.session_state:
    st.session_state['selected_user'] = 'SUB_01'

st.sidebar.title("🔐 권한 제어 센터")
role_options = ['일반 사용자(개인용 뷰)', '실험 운영자(대조 관리용 뷰)']
selected_role = st.sidebar.selectbox("접속 권한을 선택하세요:", options=role_options, index=role_options.index(st.session_state['user_role']))
st.session_state['user_role'] = selected_role

if st.session_state['user_role'] == '일반 사용자(개인용 뷰)':
    user_ids = list(USER_META.keys())
    user_labels = [f"{uid} · {USER_META[uid]['name']}" for uid in user_ids]
    current_index = user_ids.index(st.session_state['selected_user'])
    picked_label = st.sidebar.selectbox("🙋 사용자 계정 선택 (데모용):", options=user_labels, index=current_index)
    st.session_state['selected_user'] = user_ids[user_labels.index(picked_label)]

st.sidebar.divider()

# ==================================================================
# [CASE 1] 일반 사용자(개인용 뷰)
# ==================================================================
if st.session_state['user_role'] == '일반 사용자(개인용 뷰)':
    sub_id = st.session_state['selected_user']
    meta = USER_META[sub_id]
    df_user = df_all[df_all['피험자ID'] == sub_id].reset_index(drop=True)

    st.title("DormX 수면 케어 리포트")
    st.caption(f"피험자 ID: {sub_id}")
    st.markdown("Active 자극 조건에서의 수면 개선 효과와 개인 맞춤형 알고리즘 상태입니다.")
    st.divider()

    st.subheader("개인화 알고리즘 학습 진행도")
    step_cols = st.columns(3)
    phase = meta['phase']

    def render_step(col, step_no, label, current_phase):
        with col:
            if step_no < current_phase: st.success(f"✅ **Phase {step_no}**\n\n{label} 완료")
            elif step_no == current_phase: st.info(f"🔄 **Phase {step_no}**\n\n{label} 진행 중")
            else: st.warning(f"⏳ **Phase {step_no}**\n\n{label} 대기")

    render_step(step_cols[0], 1, "콜드스타트 적정", phase)
    render_step(step_cols[1], 2, "반응 표현형 분류", phase)
    render_step(step_cols[2], 3, "온라인 적응 학습", phase)
    st.progress(meta['progress'])
    st.caption(f"현재 {meta['phase_label']} 단계입니다. (진행도 {meta['progress']}%)")

    # [코칭 메시지 생략 - 동일]
    
    st.divider()
    col1, col2, col3 = st.columns(3)
    if not df_user.empty:
        col1.metric(label="⏱️ 최단 입면 시간", value=f"{df_user['SOL_입면시간(분)'].min()} 분")
    col2.metric(label="🎯 현재 알고리즘 신뢰도", value=f"{meta['progress']} %")
    col3.metric(label="📅 자극 참여 횟수", value=f"{len(df_user)} 회")
    
    st.divider()
    st.subheader("📈 나의 자극 조건별 입면 잠복기(SOL) 변화")
    if not df_user.empty:
        fig_personal = px.line(df_user, x='날짜', y='SOL_입면시간(분)', text='SOL_입면시간(분)', markers=True)
        fig_personal.update_traces(textposition="top center")
        st.plotly_chart(fig_personal, width='stretch')

# ==================================================================
# [CASE 2] 실험 운영자 / 연구자(대조 관리용 뷰)
# ==================================================================
else:
    # [운영자 뷰 로직 생략 - 동일]
    st.title("🔬 DormX 실험 운영자 및 연구자 관리 시스템")
    st.subheader("👥 피험자별 알고리즘 진행 현황")
    # (연구자 뷰 구현부는 이전 코드 그대로 사용하시면 됩니다.)
