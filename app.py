import streamlit as st
import pandas as pd
from datetime import datetime, date
import os
import json
import html
import base64

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound

# ---------------------------
# 0. 페이지 기본 설정 + 전체 레이아웃 폭 조정
# ---------------------------
st.set_page_config(
    page_title="부서별 주간 업무 & 회의 보드",
    layout="wide"
)

# 레이아웃 / 폰트 스타일
st.markdown(
    """
    <style>
    .block-container {
        max-width: 1400px;
        padding-top: 1.5rem;
        padding-bottom: 1rem;
    }
    .small-muted {
        font-size: 0.9rem;
        color: #6c757d;
    }
    .dept-content {
        font-size: 0.95rem;
        line-height: 1.5;
        white-space: normal;
    }
    .dept-content-large {
        font-size: 1.05rem;
        line-height: 1.6;
        white-space: normal;
    }
    .info-card {
        border: 1px solid #d0d7de;
        border-radius: 8px;
        padding: 0.7rem 1rem;
        background-color: #f4f6fb;
    }
    .info-card-title {
        font-size: 0.85rem;
        font-weight: 600;
        color: #57606a;
        margin-bottom: 0.25rem;
    }
    .info-card-value {
        font-size: 0.98rem;
        font-weight: 500;
    }
    /* 큰 내용 박스 (파스텔 하늘색) */
    .content-card {
        border-radius: 10px;
        padding: 1.2rem 1.4rem;
        background-color: #e9f2ff;       /* 파스텔 하늘색 */
        border: 1px solid #c5d8ff;
        margin-top: 1.0rem;
    }
    /* 안쪽 각 부서별 카드 (흰색) */
    .dept-inner-card {
        background-color: #ffffff;
        border-radius: 8px;
        padding: 0.8rem 1rem;
        margin-bottom: 1rem;
        border: 1px solid #d0d7de;
    }
    /* 전체 부서일 때 3열~2열 자동 레이아웃 */
    .dept-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
        gap: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------
# 1. 공통 설정
# ---------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1khJ4XMVEb9N3oQbwVqnz6loVM-yvMkRik-6NMQH6IKA/edit?gid=1896609182#gid=1896609182"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

WEEK_COL = "WEEK"
RAW_SHEET_NAME = "raw_log"


def get_credentials():
    if "gcp_service_account" in st.secrets:
        info = st.secrets["gcp_service_account"]
        if isinstance(info, str):
            service_account_info = json.loads(info)
        else:
            service_account_info = dict(info)
        return Credentials.from_service_account_info(
            service_account_info, scopes=SCOPES
        )

    service_account_file = os.path.join(BASE_DIR, "google_service_account.json")
    if os.path.exists(service_account_file):
        return Credentials.from_service_account_file(
            service_account_file, scopes=SCOPES
        )

    raise FileNotFoundError(
        "No credentials found. Set 'gcp_service_account' in Streamlit secrets "
        "or put google_service_account.json next to app.py."
    )


# ---------------------------
# 2. Google Sheets 연결
# ---------------------------

try:
    credentials = get_credentials()
    gc = gspread.authorize(credentials)
    sh = gc.open_by_url(SPREADSHEET_URL)
except Exception as e:
    st.error("❌ Google Sheet 연결 중 오류가 발생했습니다.")
    st.write("1) 시트 URL, 2) 서비스 계정 권한을 확인하세요.")
    st.exception(e)
    st.stop()

# '주간업무' 시트
try:
    worksheet = sh.worksheet("주간업무")
except Exception as e:
    st.error("❌ '주간업무' 시트를 찾지 못했습니다.")
    st.write("스프레드시트 안 탭 이름이 정확히 '주간업무'인지 확인하세요.")
    st.exception(e)
    st.stop()

# 'raw_log' 시트 (없으면 생성)
try:
    raw_ws = sh.worksheet(RAW_SHEET_NAME)
except WorksheetNotFound:
    try:
        raw_ws = sh.add_worksheet(title=RAW_SHEET_NAME, rows=1000, cols=10)
        header = ["timestamp", "meeting_date", "week_range", "department", "content"]
        raw_ws.append_row(header)
    except Exception as e:
        st.error("❌ 'raw_log' 시트를 생성하는 중 오류가 발생했습니다.")
        st.exception(e)
        st.stop()
except Exception as e:
    st.error("❌ 'raw_log' 시트 접근 중 오류가 발생했습니다.")
    st.exception(e)
    st.stop()

# ---------------------------
# 3. '주간업무' 시트 → DataFrame
# ---------------------------

raw_values = worksheet.get_all_values()
raw_df = pd.DataFrame(raw_values)

dept_row = raw_df.iloc[0]
data_df = raw_df.iloc[1:].copy()

new_columns = []
for idx, cell in enumerate(dept_row):
    header_value = str(cell).strip()
    if header_value.upper() == "WEEK":
        new_columns.append(WEEK_COL)
    elif header_value != "":
        new_columns.append(header_value)
    else:
        new_columns.append(f"col_{idx}")

data_df.columns = new_columns
data_df = data_df[data_df[WEEK_COL].astype(str).str.strip() != ""].copy()
base_df = data_df.reset_index(drop=True)

# ---------------------------
# 4. 세션 상태
# ---------------------------
if "df" not in st.session_state:
    st.session_state.df = base_df.copy()
if "departments" not in st.session_state:
    st.session_state.departments = [c for c in base_df.columns if c != WEEK_COL]
if "recent_entries" not in st.session_state:
    st.session_state.recent_entries = []

df = st.session_state.df
DEPARTMENTS = st.session_state.departments


# ---------------------------
# 5. 날짜/라벨 유틸
# ---------------------------
def parse_week_range(week_label: str):
    week_label = str(week_label).replace(" ", "")
    start_str, end_str = week_label.split("~")
    start = datetime.strptime(start_str, "%Y.%m.%d").date()
    end = datetime.strptime(end_str, "%Y.%m.%d").date()
    return start, end


def make_period_label(week_label: str) -> str:
    start, end = parse_week_range(week_label)
    date_part = f"{start.year}-{start.month:02d}-{start.day:02d} ~ {end.month:02d}-{end.day:02d}"
    days = (end - start).days + 1
    weeks = max(1, round(days / 7))
    cycle = "weekly" if weeks == 1 else f"{weeks}-weekly"
    return f"{date_part} ({cycle})"


def make_period_compact_label(week_label: str) -> str:
    """요약 박스용: 2025.11.10 - 2025.11.23"""
    start, end = parse_week_range(week_label)
    return f"{start.year}.{start.month:02d}.{start.day:02d} - {end.year}.{end.month:02d}.{end.day:02d}"


def find_week_for_date(target_date: date, week_series) -> str | None:
    for week_label in week_series:
        start, end = parse_week_range(week_label)
        if start <= target_date <= end:
            return week_label
    return None


# ---------------------------
# 6. 렌더링 유틸 (폰트 통일)
# ---------------------------
def content_to_html(text: str, large: bool = False) -> str:
    """마크다운/HTML 무시하고 줄바꿈만 유지한 HTML 문자열 반환."""
    if text is None:
        text = ""
    escaped = html.escape(str(text))
    escaped = escaped.replace("\n", "<br>")
    css_class = "dept-content-large" if large else "dept-content"
    return f"<div class='{css_class}'>{escaped}</div>"


def dept_title_html(dept: str) -> str:
    """부서 이름만 굵게, '공지 · 결정사항' 은 파란색 굵게."""
    name = dept.strip()
    esc_name = html.escape(name)
    if ("공지" in name) and ("결정사항" in name):
        return f"<div style='color:#1f6feb;font-weight:700;margin-bottom:0.4rem;'>{esc_name}</div>"
    else:
        return f"<div style='font-weight:700;margin-bottom:0.4rem;'>{esc_name}</div>"


# ---------------------------
# 7. Sidebar - 모드 선택
# ---------------------------
st.sidebar.title("메뉴")

mode = st.sidebar.radio(
    "모드 선택",
    ["회의 내용 입력", "회의 내용 조회"],
)

# ---------------------------
# 8. 회의 내용 입력 모드
# ---------------------------
if mode == "회의 내용 입력":
    st.title("회의 내용 입력")

    st.markdown("#### 1) 기본 정보 선택")

    meeting_date = st.date_input(
        "회의 날짜",
        value=date.today()
    )

    if DEPARTMENTS:
        dept_for_input = st.selectbox(
            "부서 선택",
            options=DEPARTMENTS,
            index=0
        )
    else:
        dept_for_input = None
        st.warning("등록된 부서가 없습니다. 먼저 왼쪽 하단 '부서 관리'에서 부서를 추가하세요.")

    st.markdown("#### 2) 회의 내용 입력")

    content = st.text_area(
        "회의 내용",
        placeholder="회의 안건, 주요 논의사항, 결정사항 등을 자유롭게 입력하세요.",
        height=200
    )

    week_label_for_date = find_week_for_date(meeting_date, base_df[WEEK_COL].tolist())

    if week_label_for_date:
        st.info(
            f"이 날짜는 다음 주차에 포함됩니다:\n\n**{make_period_label(week_label_for_date)}**"
        )
    else:
        st.warning(
            "⚠ 이 날짜에 해당하는 WEEK 구간을 '주간업무' 시트에서 찾지 못했습니다.\n"
            "→ 나중에 WEEK 정의를 추가로 설정해야 할 수 있습니다."
        )

    st.markdown("#### 3) 동기화 (Google Sheet에 저장)")

    if st.button("💾 Google Sheet로 동기화 (저장)", type="primary"):
        if not content.strip():
            st.warning("회의 내용을 입력하세요.")
        elif not dept_for_input:
            st.warning("부서를 선택하거나 추가하세요.")
        elif week_label_for_date is None:
            st.warning("이 날짜에 해당하는 WEEK를 찾지 못했습니다. '주간업무' 시트를 먼저 정리해야 합니다.")
        else:
            try:
                timestamp = datetime.now().isoformat(timespec="seconds")
                record_row = [
                    timestamp,
                    meeting_date.isoformat(),
                    week_label_for_date,
                    dept_for_input,
                    content.strip(),
                ]
                raw_ws.append_row(record_row)

                st.session_state.recent_entries.append(
                    {
                        "timestamp": timestamp,
                        "meeting_date": meeting_date.isoformat(),
                        "week_range": week_label_for_date,
                        "department": dept_for_input,
                        "content": content.strip(),
                    }
                )

                st.success("✅ Google Sheet에 저장되었습니다.")
            except Exception as e:
                st.error("❌ Google Sheet에 저장하는 중 오류가 발생했습니다.")
                st.exception(e)

    if st.session_state.recent_entries:
        st.markdown("---")
        st.markdown("### 이 세션에서 저장한 회의 기록들")
        for i, rec in enumerate(reversed(st.session_state.recent_entries), start=1):
            st.markdown(f"**#{i} | {rec['meeting_date']} | {rec['department']}**")
            st.markdown(content_to_html(rec["content"], large=False), unsafe_allow_html=True)
            st.caption(
                f"주차: {rec['week_range']} / 저장 시각: {rec['timestamp']}"
            )
            st.markdown("---")


# ---------------------------
# 9. 회의 내용 조회 모드
# ---------------------------
elif mode == "회의 내용 조회":
    st.title("주간 회의 내용 조회")

    # 사이드바 상단 필터
    st.sidebar.markdown("---")
    st.sidebar.subheader("조회 필터")

    period_options = df[WEEK_COL].tolist()
    selected_period = st.sidebar.selectbox(
        "회의 기간(주차) 선택",
        options=period_options,
        format_func=make_period_label,
    )

    selected_department = st.sidebar.selectbox(
        "부서 선택",
        options=["전체"] + DEPARTMENTS
    )

    # 요약 박스 두 개 (선택된 기간 / 선택된 부서)
    period_label_compact = make_period_compact_label(selected_period)
    dept_label = "전체 부서" if selected_department == "전체" else selected_department

    col_info1, col_info2 = st.columns(2)

    with col_info1:
        st.markdown(
            f"""
            <div class="info-card">
              <div class="info-card-title">선택된 기간</div>
              <div class="info-card-value">{html.escape(period_label_compact)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_info2:
        st.markdown(
            f"""
            <div class="info-card">
              <div class="info-card-title">선택된 부서</div>
              <div class="info-card-value">{html.escape(dept_label)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # 실제 내용
    week_row = df[df[WEEK_COL] == selected_period].iloc[0]

    if selected_department == "전체":
        inner_cards = []
        for dept in DEPARTMENTS:
            content = str(week_row.get(dept, "") or "").strip()
            if not content:
                continue
            title_html = dept_title_html(dept)
            body_html = content_to_html(content, large=False)
            inner_html = f"<div class='dept-inner-card'>{title_html}{body_html}</div>"
            inner_cards.append(inner_html)

        if not inner_cards:
            inner_cards.append(
                "<div class='dept-inner-card'><div class='dept-content'>이 기간에는 등록된 내용이 없습니다.</div></div>"
            )

        card_html = "<div class='content-card'><div class='dept-grid'>" + "".join(inner_cards) + "</div></div>"
        st.markdown(card_html, unsafe_allow_html=True)

    else:
        content = str(week_row.get(selected_department, "") or "").strip()
        title_html = dept_title_html(selected_department)
        if content:
            body_html = content_to_html(content, large=True)
        else:
            body_html = "<div class='dept-content'>이 기간에는 등록된 내용이 없습니다.</div>"

        card_html = "<div class='content-card'><div class='dept-inner-card'>" + title_html + body_html + "</div></div>"
        st.markdown(card_html, unsafe_allow_html=True)

    with st.expander("디버그용: 현재 DataFrame 보기", expanded=False):
        st.dataframe(df)


# ---------------------------
# 10. Sidebar 하단 - 부서 관리
# ---------------------------
st.sidebar.markdown("<br><br>", unsafe_allow_html=True)
st.sidebar.markdown("---")

with st.sidebar.expander("부서 관리", expanded=False):
    st.caption("앱에서 사용할 부서 목록을 관리합니다. (현재 세션 기준)")

    new_dept_name = st.text_input(
        "새 부서 이름",
        placeholder="예) 영상의학팀",
        key="sidebar_new_dept_name"
    )

    if st.button("＋ 부서 추가", key="sidebar_add_dept_button"):
        name = new_dept_name.strip()
        if not name:
            st.warning("부서 이름을 입력하세요.")
        elif name in DEPARTMENTS:
            st.warning("이미 존재하는 부서입니다.")
        elif name == WEEK_COL:
            st.warning("이 이름은 사용할 수 없습니다.")
        else:
            st.session_state.departments.append(name)
            DEPARTMENTS = st.session_state.departments
            st.success(f"'{name}' 부서를 추가했습니다.")

    if DEPARTMENTS:
        dept_to_remove = st.selectbox(
            "삭제할 부서 선택",
            options=DEPARTMENTS,
            key="sidebar_dept_to_remove"
        )
        if st.button("－ 부서 삭제", key="sidebar_remove_dept_button"):
            st.session_state.departments = [d for d in DEPARTMENTS if d != dept_to_remove]
            DEPARTMENTS = st.session_state.departments
            st.success(f"'{dept_to_remove}' 부서를 삭제했습니다.")
    else:
        st.caption("현재 등록된 부서가 없습니다.")


# ---------------------------
# 11. 우측 하단 병원 로고 표시 (viewport 고정)
# ---------------------------
logo_path = None
for fname in [
    "히즈메디병원 로고-네모.png",   # 한글 파일명
    "hospital_logo.png",            # 영어 파일명 옵션
    "logo.png",
]:
    candidate = os.path.join(BASE_DIR, fname)
    if os.path.exists(candidate):
        logo_path = candidate
        break

if logo_path:
    try:
        with open(logo_path, "rb") as f:
            img_bytes = f.read()
        b64 = base64.b64encode(img_bytes).decode()
        st.markdown(
            f"""
            <div style="
                position: fixed;
                bottom: 16px;
                right: 18px;
                z-index: 999;
            ">
                <img src="data:image/png;base64,{b64}" style="width:72px; opacity:0.96;">
            </div>
            """,
            unsafe_allow_html=True,
        )
    except Exception:
        pass
else:
    st.sidebar.caption(
        "로고를 보이게 하려면 app.py와 같은 폴더에\n"
        "'hospital_logo.png' 또는 '히즈메디병원 로고-네모.png' 파일을 두세요."
    )
