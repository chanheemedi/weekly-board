import streamlit as st
import pandas as pd
from datetime import datetime
import os
import json

import gspread
from google.oauth2.service_account import Credentials

# ---------------------------
# 0. 페이지 기본 설정
# ---------------------------
st.set_page_config(
    page_title="Weekly Board - Period Mode (Google Sheets)",
    layout="wide"
)

# ---------------------------
# 1. 공통 설정 (경로, 시트 URL, 스코프)
# ---------------------------

# app.py가 있는 폴더 경로
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 네가 준 구글 시트 전체 URL
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1khJ4XMVEb9N3oQbwVqnz6loVM-yvMkRik-6NMQH6IKA/edit?gid=1896609182#gid=1896609182"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def get_credentials():
    """
    1) Cloud / 로컬 둘 다에서 st.secrets["gcp_service_account"] 먼저 사용
    2) 그래도 없으면, 로컬 개발용으로 google_service_account.json 파일 시도
    3) 둘 다 없으면 명확한 에러
    """
    # 1) secrets에 있는 경우 (Cloud에서 사용)
    if "gcp_service_account" in st.secrets:
        info = st.secrets["gcp_service_account"]

        # secrets.toml에 JSON 문자열로 넣었을 때 (""" { ... } """)
        if isinstance(info, str):
            service_account_info = json.loads(info)
        else:
            # [gcp_service_account] 형태의 TOML 테이블로 넣었을 때
            service_account_info = dict(info)

        return Credentials.from_service_account_info(service_account_info, scopes=SCOPES)

    # 2) 로컬 json 파일 (Cloud에는 없음)
    service_account_file = os.path.join(BASE_DIR, "google_service_account.json")
    if os.path.exists(service_account_file):
        return Credentials.from_service_account_file(service_account_file, scopes=SCOPES)

    # 3) 둘 다 없으면 명확하게 죽이기
    raise FileNotFoundError(
        "No credentials found. Set 'gcp_service_account' in Streamlit secrets "
        "or put google_service_account.json next to app.py."
    )


# 인증 및 시트 열기
try:
    credentials = get_credentials()
    gc = gspread.authorize(credentials)
    sh = gc.open_by_url(SPREADSHEET_URL)
    worksheet = sh.worksheet("주간업무")  # 탭 이름이 정확히 '주간업무' 여야 함
except Exception as e:
    st.error("❌ Google Sheet 연결 중 오류가 발생했습니다.")
    st.write("아래 항목들을 다시 확인해 주세요:")
    st.write("1) SPREADSHEET_URL이 실제 주간업무 시트 주소인지")
    st.write("2) 로컬이면 google_service_account.json 파일이 폴더 안에 있는지")
    st.write("3) Cloud면 secrets에 gcp_service_account가 제대로 설정됐는지")
    st.write("4) 서비스 계정 이메일이 해당 시트에 '공유'되어 있는지")
    st.write("5) 시트 탭 이름이 정확히 '주간업무'인지")
    st.exception(e)
    st.stop()

# ---------------------------
# 2. 시트 데이터를 DataFrame으로 변환
# ---------------------------

# 모든 셀 값 가져오기 (리스트의 리스트)
raw_values = worksheet.get_all_values()
raw_df = pd.DataFrame(raw_values)

# 1행(0번째 row)에 부서명/구분이 들어있음
dept_row = raw_df.iloc[0]         # 부서 이름들이 있는 행
data_df = raw_df.iloc[1:].copy()  # 실제 데이터(주차별 업무)

# 컬럼명 재구성: 첫 컬럼은 WEEK, 나머지는 dept_row에 적힌 부서명 사용
new_columns = []
for idx, cell in enumerate(dept_row):
    header_value = str(cell).strip()

    if header_value.upper() == "WEEK":
        new_columns.append("WEEK")
    elif header_value != "":
        new_columns.append(header_value)  # 전략기획실, 행정부, 간호부 등
    else:
        # 부서명이 비어 있으면 임시 이름
        new_columns.append(f"col_{idx}")

data_df.columns = new_columns

# WEEK 컬럼 기준으로 유효한 행만 남기기
data_df = data_df[data_df["WEEK"].astype(str).str.strip() != ""].copy()

# 이 데이터프레임을 앱의 기본 데이터로 사용
base_df = data_df.reset_index(drop=True)

WEEK_COL = "WEEK"

# ---------------------------
# 2-1. 세션 상태 초기화 (df, departments)
# ---------------------------
if "df" not in st.session_state:
    st.session_state.df = base_df.copy()

if "departments" not in st.session_state:
    st.session_state.departments = [c for c in base_df.columns if c != WEEK_COL]

# 매번 사용하기 쉽게 로컬 변수로 꺼내기
df = st.session_state.df
DEPARTMENTS = st.session_state.departments

# ---------------------------
# 2-2. WEEK 문자열 → 날짜/라벨 변환 함수
# ---------------------------
def parse_week_range(week_label: str):
    """'2025.11.10~2025.11.23' -> (date(2025,11,10), date(2025,11,23))"""
    week_label = str(week_label).replace(" ", "")
    start_str, end_str = week_label.split("~")
    start = datetime.strptime(start_str, "%Y.%m.%d").date()
    end = datetime.strptime(end_str, "%Y.%m.%d").date()
    return start, end


def make_period_label(week_label: str) -> str:
    """
    '2025.11.10~2025.11.23' ->
    '2025-11-10 ~ 11-23 (2-weekly)' 이런 식의 라벨로 변환
    """
    start, end = parse_week_range(week_label)

    # 날짜 포맷: 2025-11-10 ~ 11-23 (뒤쪽은 연도 생략)
    date_part = f"{start.year}-{start.month:02d}-{start.day:02d} ~ {end.month:02d}-{end.day:02d}"

    # 기간 길이에 따라 weekly / 2-weekly 등 표시
    days = (end - start).days + 1  # 양 끝 포함
    weeks = max(1, round(days / 7))

    if weeks == 1:
        cycle = "weekly"
    else:
        cycle = f"{weeks}-weekly"

    return f"{date_part} ({cycle})"


# ---------------------------
# 3. Sidebar - Filters (Period + Department)
# ---------------------------
st.sidebar.title("Filters")

# 3-1. 회의 기간(주차) 선택
period_options = df[WEEK_COL].tolist()
selected_period = st.sidebar.selectbox(
    "Select Period",
    options=period_options,
    format_func=make_period_label,
)

# 3-2. 부서 선택
selected_department = st.sidebar.selectbox(
    "Select Department",
    options=["All"] + DEPARTMENTS
)

# ---------------------------
# 4. Sidebar - Department Management (하단)
# ---------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("Department Management")

# 새 부서 이름 입력
new_dept_name = st.sidebar.text_input(
    "New department name",
    placeholder="e.g. Radiology",
    key="new_dept_name"
)

# 부서 추가 버튼
if st.sidebar.button("+ Add Dept", key="add_dept_button"):
    name = new_dept_name.strip()
    if not name:
        st.sidebar.warning("Please enter a department name.")
    elif name in DEPARTMENTS:
        st.sidebar.warning("This department already exists.")
    elif name == WEEK_COL:
        st.sidebar.warning("This name is reserved.")
    else:
        # 세션 상태 업데이트: 부서 리스트 + df 컬럼 추가
        st.session_state.departments.append(name)
        st.session_state.df[name] = ""  # 새 부서는 일단 빈 내용
        st.sidebar.success(f"Department '{name}' added.")

        # 로컬 변수도 다시 반영
        DEPARTMENTS = st.session_state.departments
        df = st.session_state.df

# 삭제할 부서 선택 (현재 부서 리스트에서 선택)
if DEPARTMENTS:
    dept_to_remove = st.sidebar.selectbox(
        "Department to remove",
        options=DEPARTMENTS,
        key="dept_to_remove"
    )

    if st.sidebar.button("- Remove Dept", key="remove_dept_button"):
        # 세션 상태에서 제거
        st.session_state.departments = [d for d in DEPARTMENTS if d != dept_to_remove]
        # df 컬럼 삭제
        if dept_to_remove in st.session_state.df.columns:
            st.session_state.df.drop(columns=[dept_to_remove], inplace=True)

        st.sidebar.success(f"Department '{dept_to_remove}' removed.")

        # 로컬 변수 다시 반영
        DEPARTMENTS = st.session_state.departments
        df = st.session_state.df
else:
    st.sidebar.caption("No departments to remove.")

st.sidebar.caption("※ Currently changes live only in the app.\n   Later they'll sync to Google Sheet.")

# ---------------------------
# 5. Main Area - 현재 선택 정보 표시
# ---------------------------
st.title("Weekly Department Tasks & Meeting Board")

st.write("### Current selection")
st.write(f"- **Period**: {make_period_label(selected_period)}")
st.write(f"- **Department**: {selected_department}")

st.write("---")

# ---------------------------
# 6. 선택된 Period + Department에 맞는 내용 보여주기
# ---------------------------
st.write("### Tasks / Meetings for selected period")

# 6-1. 선택된 Period에 해당하는 row 찾기
week_row = df[df[WEEK_COL] == selected_period].iloc[0]

if selected_department == "All":
    # 모든 부서 내용 표시
    for dept in DEPARTMENTS:
        st.markdown(f"#### {dept}")
        content = str(week_row.get(dept, "") or "").strip()
        if content:
            # 줄바꿈을 Markdown 줄바꿈으로 변환
            st.markdown(content.replace("\n", "  \n"))
        else:
            st.caption("No data for this department.")
        st.markdown("---")
else:
    # 특정 부서만 표시
    st.markdown(f"#### {selected_department}")
    content = str(week_row.get(selected_department, "") or "").strip()
    if content:
        st.markdown(content.replace("\n", "  \n"))
    else:
        st.caption("No data for this department in this period.")

# ---------------------------
# 7. (옵션) Raw Data 보기 - 개발용/디버깅용
# ---------------------------
with st.expander("Show raw data (session df)", expanded=False):
    st.dataframe(df)
