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
# 3. 피험자별 Active(가온) 조건 파일럿 데이터
#    - Phase 1(콜드스타트): 데이터 포인트가 아직 적음
#    - Phase 2(표현형 분류): 여러 조건을 탐색 중, 데이터 다소 축적
#    - Phase 3(온라인 학습): 데이터가 충분히 쌓여 추천 Arm이 확정됨
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
            '날짜': ['7/3', '7/5', '7/7', '7/9'],
            '조건군': ['가온 단독(40℃)', '가온+전기자극(40℃, 5Hz)',
                     '가온+전기자극(40℃, 10Hz)', '가온+전기자극(42℃, 10Hz)'],
            'SOL_입면시간(분)': [26, 19, 15, 16],
            '각성시간(분)': [9, 7, 6, 7],
            '깊은수면(%)': [15.5, 16.8, 18.2, 17.9],
            '코어수면(%)': [55.0, 54.2, 53.6, 53.8],
            'REM수면(%)': [27.8, 27.9, 27.0, 27.2],
        },
        'SUB_03': {
            '날짜': ['7/4', '7/5', '7/7'],
            '조건군': ['가온 단독(40℃)', '가온+전기자극(40℃)', '가온+전기자극(45℃)'],
            'SOL_입면시간(분)': [22, 13, 22],
            '각성시간(분)': [3, 14, 8],
            '깊은수면(%)': [17.8, 17.0, 12.5],
            '코어수면(%)': [53.3, 54.3, 57.0],
            'REM수면(%)': [28.9, 28.7, 30.5],
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
# 4. 세션 상태 초기화
# ------------------------------------------------------------------
if 'user_role' not in st.session_state:
    st.session_state['user_role'] = '일반 사용자(개인용 뷰)'
if 'selected_user' not in st.session_state:
    st.session_state['selected_user'] = 'SUB_01'

# ------------------------------------------------------------------
# 5. 사이드바 - 권한 전환 컨트롤러
# ------------------------------------------------------------------
st.sidebar.title("🔐 권한 제어 센터")
role_options = ['일반 사용자(개인용 뷰)', '실험 운영자(대조 관리용 뷰)']
selected_role = st.sidebar.selectbox(
    "접속 권한을 선택하세요:",
    options=role_options,
    index=role_options.index(st.session_state['user_role']),
)
st.session_state['user_role'] = selected_role

# 일반 사용자 모드에서는 데모를 위해 3명 중 누구로 로그인할지 선택
if st.session_state['user_role'] == '일반 사용자(개인용 뷰)':
    user_ids = list(USER_META.keys())
    user_labels = [f"{uid} · {USER_META[uid]['name']}" for uid in user_ids]
    current_index = user_ids.index(st.session_state['selected_user'])
    picked_label = st.sidebar.selectbox(
        "🙋 사용자 계정 선택 (데모용):",
        options=user_labels,
        index=current_index,
    )
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

    # 알고리즘 진행 단계 인디케이터 (사용자의 실제 Phase에 맞춰 표시)
    st.subheader("개인화 알고리즘 학습 진행도")

    step_cols = st.columns(3)
    phase = meta['phase']

    def render_step(col, step_no, label, current_phase):
        with col:
            if step_no < current_phase:
                st.success(f"✅ **Phase {step_no}**\n\n{label} 완료")
            elif step_no == current_phase:
                st.info(f"🔄 **Phase {step_no}**\n\n{label} 진행 중")
            else:
                st.warning(f"⏳ **Phase {step_no}**\n\n{label} 대기")

    render_step(step_cols[0], 1, "콜드스타트 적정", phase)
    render_step(step_cols[1], 2, "반응 표현형 분류", phase)
    render_step(step_cols[2], 3, "온라인 적응 학습", phase)

    st.progress(meta['progress'])
    st.caption(f"현재 {meta['phase_label']} 단계입니다. (진행도 {meta['progress']}%)")

    # 코칭 메시지: Phase에 따라 내용을 다르게 구성
    if phase == 1:
        st.warning(
            "🧪 **오늘 밤 수면 코칭 (콜드스타트 진행 중)**\n\n"
            "아직 회원님의 반응 데이터가 충분히 쌓이지 않았습니다. "
            "현재는 기본 세팅인 **[ 38~40℃ 가온 단독 ]** 조건으로 반응을 탐색하고 있으며, "
            "데이터가 더 모이면 맞춤 추천이 시작됩니다."
        )
    elif phase == 2:
        st.info(
            f"🔎 **오늘 밤 수면 코칭 (표현형 분류 중)**\n\n"
            f"현재까지의 반응 경향으로 볼 때 회원님은 **'{meta['phenotype']}'**에 가까운 것으로 잠정 분류되었습니다. "
            "정확한 분류를 위해 오늘 밤은 **[ 40℃ 가온 + 10Hz 전기자극 ]** 조합으로 반응을 한 번 더 확인합니다."
        )
    else:
        st.success(
            f"💡 **오늘 밤 수면 코칭 (추천 세팅)**\n\n"
            f"알고리즘 분석 결과, 회원님은 **'{meta['phenotype']}'**으로 분류되었습니다. "
            "현재까지의 데이터를 바탕으로 오늘 밤 가장 입면 효율이 높을 것으로 계산된 "
            "**[ 40℃ 가온 + 10Hz 전기자극 ]** 조합을 기기에 세팅합니다."
        )

    st.divider()

    # 주요 개인 지표 요약
    col1, col2, col3 = st.columns(3)
    if not df_user.empty:
        best_sol = df_user['SOL_입면시간(분)'].min()
        col1.metric(label="⏱️ 최단 입면 시간", value=f"{best_sol} 분")
    else:
        col1.metric(label="⏱️ 최단 입면 시간", value="데이터 없음")

    col2.metric(label="🎯 현재 알고리즘 신뢰도", value=f"{meta['progress']} %")
    col3.metric(label="📅 자극 참여 횟수", value=f"{len(df_user)} 회")
    st.divider()

    # 개인 차트: 자극 조건별 입면 시간 추이
    st.subheader("📈 나의 자극 조건별 입면 잠복기(SOL) 변화")
    if not df_user.empty:
        fig_personal = px.line(
            df_user,
            x='날짜',
            y='SOL_입면시간(분)',
            text='SOL_입면시간(분)',
            markers=True,
            title="자극 세팅 변화에 따른 잠드는 시간 추이",
        )
        fig_personal.update_traces(textposition="top center")
        fig_personal.update_layout(yaxis_title="잠드는 데 걸린 시간 (분)", xaxis_title="실험 일자")
        st.plotly_chart(fig_personal, width='stretch')
    else:
        st.info("아직 표시할 데이터가 없습니다.")

# ==================================================================
# [CASE 2] 실험 운영자 / 연구자(대조 관리용 뷰)
# ==================================================================
else:
    st.title("🔬 DormX 실험 운영자 및 연구자 관리 시스템")
    st.markdown("전체 피험자(3명)의 Active 조건 원시 데이터 분석 및 수면 구조 통계 화면입니다.")
    st.divider()

    # 피험자별 Phase 현황 요약
    st.subheader("👥 피험자별 알고리즘 진행 현황")
    summary_cols = st.columns(3)
    for col, (sub_id, meta) in zip(summary_cols, USER_META.items()):
        with col:
            st.markdown(f"**{sub_id} · {meta['name']}**")
            st.caption(meta['phase_label'])
            st.progress(meta['progress'])
    st.divider()

    # 연구자용 필터: 피험자 + Active 세팅
    st.subheader("🔍 데이터 세부 필터링")
    filter_col1, filter_col2 = st.columns(2)

    with filter_col1:
        selected_subjects = st.multiselect(
            "분석할 피험자 선택:",
            options=list(USER_META.keys()),
            default=list(USER_META.keys()),
        )

    # 선택된 피험자 범위 내에서만 조건군 옵션 구성 (존재하지 않는 조합 방지)
    subject_scoped_df = df_all[df_all['피험자ID'].isin(selected_subjects)] if selected_subjects else df_all.iloc[0:0]
    condition_options = subject_scoped_df['조건군'].unique() if not subject_scoped_df.empty else []

    with filter_col2:
        selected_condition = st.multiselect(
            "분석할 Active 세팅 선택:",
            options=condition_options,
            default=list(condition_options),
        )

    # 필터 적용 데이터
    if selected_subjects and selected_condition:
        filtered_df = subject_scoped_df[subject_scoped_df['조건군'].isin(selected_condition)]
    else:
        filtered_df = df_all.iloc[0:0]

    st.divider()

    # 연구자용 고도화 시각화: 수면 단계 구성비(Melt 구조)
    st.subheader("📊 필터링된 Active 데이터의 수면 단계 구성비")
    if not filtered_df.empty:
        melted_df = filtered_df.melt(
            id_vars=['피험자ID', '날짜', '조건군'],
            value_vars=['깊은수면(%)', '코어수면(%)', 'REM수면(%)'],
            var_name='수면단계',
            value_name='비율(%)',
        )
        fig_research = px.bar(
            melted_df,
            x='날짜',
            y='비율(%)',
            color='수면단계',
            facet_col='피험자ID',
            hover_data=['조건군'],
            barmode='stack',
            color_discrete_map={
                '깊은수면(%)': '#312c66',
                '코어수면(%)': '#4e89ff',
                'REM수면(%)': '#5bcaf0',
            },
        )
        st.plotly_chart(fig_research, width='stretch')

        # 원본 데이터 테이블 및 다운로드 기능
        st.subheader("📋 모니터링 원본 데이터셋")
        st.dataframe(filtered_df, width='stretch', hide_index=True)

        # CSV 다운로드 버튼
        csv = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 선택된 데이터 CSV 다운로드",
            data=csv,
            file_name="DormX_Active_Data.csv",
            mime="text/csv",
        )
    else:
        st.warning("필터 조건에 부합하는 데이터가 없습니다. 피험자와 세팅을 하나 이상 선택해주세요.")
