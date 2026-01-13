아래 코드 전체를 `app.py`에 그대로 덮어쓰기 해서 사용하면 돼요.

변경 포함 사항:

* `initial_sidebar_state="expanded"` → PC에서 기본으로 사이드바 펼쳐짐
* 사이드바 접기/펼치기 아이콘 항상 보이도록 CSS 추가
* 상단 링크 버튼 4개:
  병원 일정 보기 / 의료진 진료시간표 / 네이버 블로그 / 의료기사 스크랩
* 본문 안의 URL 자동 추출 → 카드 아래
  `링크 바로가기:`
  `- [PDF 1)](…)`, `- [링크 2)](…)` 처럼 짧은 레이블로 클릭 가능하게 표시
  (구글 드라이브·PDF 링크는 `PDF n)` / 나머지는 `링크 n)`)

```python
import re
from datetime import datetime, timedelta

import gspread
from gspread.cell import Cell
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
import streamlit.components.v1 as components

WEEK_COL = "WEEK"

# ---------- URL 추출 & 라벨링 ----------

URL_PATTERN = re.compile(r"(https?://[^\s]+)")


def extract_urls(text: str):
    """텍스트에서 URL만 뽑아서 중복 제거하고 리스트로 반환."""
    if not text:
        return []
    urls = URL_PATTERN.findall(text)
    # 순서 유지하면서 중복 제거
    return list(dict.fromkeys(urls))


def link_label(u: str, idx: int) -> str:
    """URL 종류에 따라 'PDF 1)', '링크 1)' 이런 식으로 라벨 생성."""
    u_low = u.lower()
    # 주소에 .pdf 가 있거나, 구글 드라이브면 PDF 취급
    is_pdf = u_low.endswith(".pdf") or "drive.google.com" in u_low
    if is_pdf:
        return f"PDF {idx})"
    else:
        return f"링크 {idx})"


# ---------- 구글 시트 관련 ----------


@st.cache_resource(show_spinner=False)
def get_worksheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scopes,
    )
    client = gspread.authorize(creds)
    sh = client.open_by_key(st.secrets["gsheet"]["spreadsheet_id"])
    ws = sh.worksheet(st.secrets["gsheet"]["worksheet_name"])
    return ws


@st.cache_data(show_spinner=False)
def load_data():
    ws = get_worksheet()
    values = ws.get_all_values()

    if not values or len(values) < 2:
        return pd.DataFrame()

    raw_header = values[0]
    rows = values[1:]

    header = []
    for i, h in enumerate(raw_header):
        h = str(h).strip()
        if not h:
            h = f"Unnamed_{i + 1}"
        header.append(h)

    n_cols = len(header)

    normalized_rows = []
    for r in rows:
        if len(r) < n_cols:
            r = r + [""] * (n_cols - len(r))
        elif len(r) > n_cols:
            r = r[:n_cols]
        normalized_rows.append(r)

    df = pd.DataFrame(normalized_rows, columns=header)

    # 완전히 빈 Unnamed_ 컬럼 제거
    for c in [c for c in df.columns if c.startswith("Unnamed_")]:
        if df[c].replace("", pd.NA).isna().all():
            df.drop(columns=[c], inplace=True)

    # 시트 실제 row 번호 (헤더가 1행이므로 +2)
    df["_sheet_row"] = df.index + 2

    # WEEK 컬럼 자동 탐지
    pattern = re.compile(r"\d{4}\.\d{2}\.\d{2}\s*~\s*\d{4}\.\d{2}\.\d{2}")
    week_col_name = None
    for col in df.columns:
        s = df[col].astype(str)
        if s.apply(lambda x: bool(pattern.fullmatch(x.strip()))).any():
            week_col_name = col
            break

    if week_col_name is None:
        return df

    if WEEK_COL not in df.columns:
        df[WEEK_COL] = df[week_col_name]

    def parse_start_date(week_str: str) -> datetime:
        try:
            start = str(week_str).split("~")[0].strip()
            return datetime.strptime(start, "%Y.%m.%d")
        except Exception:
            return datetime.min

    df["_start_date"] = df[WEEK_COL].astype(str).apply(parse_start_date)
    df = df.sort_values("_start_date", ascending=False).reset_index(drop=True)

    return df


def get_dept_columns(df: pd.DataFrame):
    return [c for c in df.columns if c not in [WEEK_COL] and not c.startswith("_")]


def parse_week_range(week_str: str):
    try:
        s, e = week_str.split("~")
        start = datetime.strptime(s.strip(), "%Y.%m.%d")
        end = datetime.strptime(e.strip(), "%Y.%m.%d")
        return start, end
    except Exception:
        return None, None


def get_col_index(ws, col_name: str):
    headers = ws.row_values(1)
    try:
        return headers.index(col_name) + 1
    except ValueError:
        return None


def save_cell(sheet_row: int, col_name: str, key: str):
    """텍스트 입력이 끝난 시점에 해당 셀을 바로 구글 시트에 반영하는 자동 저장 콜백."""
    ws = get_worksheet()
    col_idx = get_col_index(ws, col_name)
    if col_idx is None:
        st.warning(f"'{col_name}' 열을 찾을 수 없어 자동 저장에 실패했습니다.")
        return

    value = st.session_state.get(key, "")
    ws.update_cell(sheet_row, col_idx, value)

    # 캐시 지우기
    load_data.clear()

    # 토스트 지원 안 될 수 있으니 예외 처리
    try:
        st.toast("자동 저장 완료", icon="💾")
    except Exception:
        st.success("자동 저장 완료")


def escape_html(text: str) -> str:
    if text is None:
        return ""
    text = str(text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("\n", "<br>")
    return text


def main():
    app_title = "HISMEDI † Weekly report"
    try:
        app_title = st.secrets["app"].get("TITLE", app_title)
    except Exception:
        pass

    # 기본: 사이드바 펼쳐진 상태
    st.set_page_config(
        page_title=app_title,
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ---------- 전역 스타일 ----------
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] {
            min-width: 440px;
            max-width: 460px;
            padding-top: 0;
        }
        [data-testid="stSidebar"] * {
            line-height: 1.03;
        }
        [data-testid="stSidebar"] .stButton {
            margin-bottom: 0.2rem;
        }
        [data-testid="stSidebar"] button {
            font-size: 0.8rem;
            padding-top: 0.18rem;
            padding-bottom: 0.18rem;
        }
        /* 부서 선택 영역 버튼 */
        [data-testid="stSidebar"] [data-testid="column"] button {
            font-size: 0.7rem;
            padding-top: 0.30rem;
            padding-bottom: 0.30rem;
        }
        [data-testid="stSidebar"] [data-testid="column"] .stButton {
            margin-bottom: 0.07rem;
        }
        [data-testid="block-container"] {
            padding-top: 0;
            padding-left: 1.3rem;
            padding-right: 1.3rem;
        }
        h4 {
            margin-top: 0.15rem;
            margin-bottom: 0.35rem;
        }
        textarea {
            line-height: 1.3;
        }
        /* 기간 선택 드롭다운 튜닝 */
        [data-testid="stSidebar"] div[data-baseweb="select"] > div {
            background-color: #bfdbfe;
            border-radius: 4px;
            border: 1px solid #1d4ed8;
        }
        [data-testid="stSidebar"] div[data-baseweb="select"] span {
            font-size: 0.9rem;
            font-weight: 800;
        }
        /* 상단 링크 버튼(병원일정/진료시간표/블로그/스크랩) 스타일 */
        .stLinkButton > button {
            border-radius: 999px;
            background-color: #f9fafb;
            border: 1px solid #e5e7eb;
            color: #111827;
            font-size: 0.9rem;
            font-weight: 500;
            padding: 0.45rem 1.6rem;
            box-shadow: 0 1px 2px rgba(15,23,42,0.04);
        }
        .stLinkButton > button:hover {
            background-color: #e5e7eb;
            border-color: #d1d5db;
        }

        /* 사이드바 접기/펼치기 아이콘 항상 보이게 */
        [data-testid="collapsedControl"] {
            opacity: 1 !important;
            visibility: visible !important;
        }
        [data-testid="collapsedControl"] svg {
            color: #4b5563;
        }

        /* 📱 모바일 화면 대응 (폭이 900px 이하인 경우) */
        @media (max-width: 900px) {
            /* 사이드바 폭 줄이기 */
            [data-testid="stSidebar"] {
                min-width: 260px;
                max-width: 260px;
            }
            /* 본문 좌우 여백 조금 줄이기 */
            [data-testid="block-container"] {
                padding-left: 0.6rem;
                padding-right: 0.6rem;
            }
            /* 상단 링크 버튼은 가로 전체를 쓰도록 */
            .stLinkButton > button {
                width: 100%;
                margin-bottom: 0.25rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    df = load_data()
    if df.empty:
        st.warning("구글시트에 데이터가 없습니다.")
        return

    if WEEK_COL not in df.columns:
        st.error("기간(WEEK) 컬럼을 찾지 못했습니다. 시트의 기간 형식을 확인해 주세요.")
        st.write("현재 열 목록:", list(df.columns))
        return

    ws = get_worksheet()
    dept_cols = get_dept_columns(df)

    if "selected_dept" not in st.session_state:
        st.session_state["selected_dept"] = "전체 부서"

    # ---------- 사이드바 ----------
    with st.sidebar:
        st.markdown(
            f"""
            <div style="
                width:100%;
                margin-top:-0.8rem;
                margin-bottom:0.3rem;
                font-size:2.0rem;
                font-weight:900;
                letter-spacing:0.05em;
                color:#111827;
            ">
                {app_title}
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            "<hr style='margin:0.25rem 0; border:0; border-top:1px solid #e0e0e0;' />",
            unsafe_allow_html=True,
        )

        # 인쇄 / 동기화
        btn_cols = st.columns(2)
        with btn_cols[0]:
            if st.button("🖨 인쇄 미리보기", use_container_width=True):
                st.session_state["print_requested"] = True
        with btn_cols[1]:
            if st.button("🔄 데이터 동기화", use_container_width=True):
                load_data.clear()
                st.rerun()

        st.markdown(
            "<hr style='margin:0.35rem 0; border:0; border-top:1px solid #e0e0e0;' />",
            unsafe_allow_html=True,
        )

        # 기간 관리
        week_options = df[WEEK_COL].astype(str).tolist()
        selected_week = st.selectbox(
            "기간 선택",
            options=week_options,
            index=0,
            key="week_select",
        )

        last_week_str = df[WEEK_COL].astype(str).iloc[0]
        last_start, last_end = parse_week_range(last_week_str)
        if last_start and last_end:
            span_days = (last_end - last_start).days + 1
            default_weeks = 1 if span_days <= 7 else 2
        else:
            default_weeks = 2

        st.markdown(
            "<div style='font-size:0.8rem; margin-top:0.1rem; margin-bottom:0.1rem;'>새 기간 길이</div>",
            unsafe_allow_html=True,
        )
        unit_choice = st.radio(
            "새 기간 길이 선택",
            ["직전 기간과 동일", "1주", "2주"],
            index=0,
            horizontal=True,
            label_visibility="collapsed",
        )

        if unit_choice == "1주":
            weeks_to_add = 1
        elif unit_choice == "2주":
            weeks_to_add = 2
        else:
            weeks_to_add = default_weeks

        if last_start and last_end:
            new_start = last_end + timedelta(days=1)
        else:
            new_start = datetime.today()

        new_end = new_start + timedelta(days=7 * weeks_to_add - 1)
        new_week_str = f"{new_start:%Y.%m.%d}~{new_end:%Y.%m.%d}"
        st.caption(f"새 기간 미리보기: **{new_week_str}**")

        if st.button("새 기간 추가('기간선택'에서 없는 경우)", use_container_width=True):
            headers = ws.row_values(1)
            new_row = ["" for _ in headers]
            if WEEK_COL in headers:
                idx = headers.index(WEEK_COL)
                new_row[idx] = new_week_str
            else:
                ws.insert_cols([WEEK_COL], 1)
                headers = ws.row_values(1)
                new_row = ["" for _ in headers]
                new_row[0] = new_week_str

            ws.insert_row(new_row, index=2, value_input_option="USER_ENTERED")

            load_data.clear()
            st.success(f"새 기간 {new_week_str} 이(가) 추가되었습니다.")
            st.rerun()

        st.markdown(
            "<hr style='margin:0.35rem 0; border:0; border-top:1px solid #e0e0e0;' />",
            unsafe_allow_html=True,
        )

        # 부서 선택
        all_depts = ["전체 부서"] + dept_cols
        current_dept = st.session_state.get("selected_dept", "전체 부서")

        n_cols = 3 if len(all_depts) >= 3 else len(all_depts)
        dept_cols_ui = st.columns(n_cols)

        for i, dept in enumerate(all_depts):
            col = dept_cols_ui[i % n_cols]
            button_type = "primary" if dept == current_dept else "secondary"
            with col:
                if st.button(
                    dept,
                    key=f"dept_btn_{dept}",
                    use_container_width=True,
                    type=button_type,
                ):
                    st.session_state["selected_dept"] = dept
                    st.rerun()

        # 현재 선택된 부서 필터
        dept_filter = st.session_state.get("selected_dept", "전체 부서")

        st.markdown(
            "<hr style='margin:0.35rem 0; border:0; border-top:1px solid #e0e0e0;' />",
            unsafe_allow_html=True,
        )

        # 부서 관리
        st.markdown(
            "<div style='font-weight:600; margin:0.05rem 0 0.2rem;'>부서 관리</div>",
            unsafe_allow_html=True,
        )
        st.caption("표에서 부서명을 직접 수정·추가·삭제 후, 아래 저장 버튼을 눌러주세요.")

        dept_df = pd.DataFrame({"부서": dept_cols})
        edited_dept_df = st.data_editor(
            dept_df,
            num_rows="dynamic",
            use_container_width=True,
            key="dept_editor",
        )

        if st.button("부서 변경 사항 저장", use_container_width=True):
            original = dept_cols
            new_list = [
                str(x).strip()
                for x in edited_dept_df["부서"].tolist()
                if str(x).strip()
            ]

            max_len = max(len(original), len(new_list))
            renames = []
            to_delete = []
            to_add = []

            for i in range(max_len):
                old = original[i] if i < len(original) else None
                new_name = new_list[i] if i < len(new_list) else None

                if old and new_name:
                    if old != new_name:
                        renames.append((old, new_name))
                elif old and not new_name:
                    to_delete.append(old)
                elif new_name and not old:
                    to_add.append(new_name)

            for old, new_name in renames:
                col_idx = get_col_index(ws, old)
                if col_idx is not None:
                    ws.update_cell(1, col_idx, new_name)

            if to_delete:
                col_indices = []
                for name in to_delete:
                    idx = get_col_index(ws, name)
                    if idx is not None:
                        col_indices.append(idx)
                for idx in sorted(col_indices, reverse=True):
                    ws.delete_columns(idx)

            for name in to_add:
                headers_now = ws.row_values(1)
                ws.add_cols(1)
                new_idx = len(headers_now) + 1
                ws.update_cell(1, new_idx, name)

            load_data.clear()
            st.success("부서 설정이 저장되었습니다.")
            st.rerun()

    # ---------- 상단 네비게이션 버튼 ----------
    nav_cols = st.columns(4)
    with nav_cols[0]:
        st.link_button(
            "병원 일정 보기",
            "https://calendar.google.com/calendar/u/0/r?pli=1",
            type="secondary",
        )
    with nav_cols[1]:
        st.link_button(
            "의료진 진료시간표",
            "https://docs.google.com/spreadsheets/d/1NwQadQSzlmWVmPN8U-AHw7ZmWbnKO0nzmc0M25XDwfo/edit?usp=sharing",
            type="secondary",
        )
    with nav_cols[2]:
        st.link_button(
            "네이버 블로그",
            "https://blog.naver.com/hisped2017",
            type="secondary",
        )
    with nav_cols[3]:
        st.link_button(
            "의료기사 스크랩",
            "https://hisnews-p6tawcdhd7g2xrfgutathk.streamlit.app/",
            type="secondary",
        )

    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)

    # ---------- 메인 콘텐츠 ----------
    row_df = df[df[WEEK_COL] == selected_week]
    if row_df.empty:
        st.error("선택한 기간의 데이터를 찾을 수 없습니다.")
        return

    row = row_df.iloc[0]

    selected_indices = df.index[df[WEEK_COL] == selected_week].tolist()
    selected_idx = selected_indices[0] if selected_indices else 0
    prev_row = df.iloc[selected_idx + 1] if selected_idx + 1 < len(df) else None

    edited_values = {}   # 전체 부서 모드
    edited_single = {}   # 단일 부서 모드

    if dept_filter == "전체 부서":
        st.markdown(f"#### {selected_week}")

        cols_main = st.columns(2)
        for i, dept in enumerate(dept_cols):
            current_text = ""
            if dept in row.index and pd.notna(row[dept]):
                current_text = str(row[dept])

            col = cols_main[i % 2]
            with col:
                with st.container(border=True):
                    st.markdown(f"**{dept}**")
                    ta_key = f"ta_{dept}_{selected_week}"
                    edited = st.text_area(
                        label=f"{dept} 업무 내용",
                        value=current_text,
                        height=320,
                        key=ta_key,
                        label_visibility="collapsed",
                        on_change=save_cell,
                        args=(int(row["_sheet_row"]), dept, ta_key),
                    )
                    edited_values[dept] = edited

                    # 링크 바로가기 출력
                    urls = extract_urls(edited)
                    if urls:
                        st.markdown(
                            "<div style='margin-top:0.25rem; font-size:0.8rem; color:#374151;'>링크 바로가기:</div>",
                            unsafe_allow_html=True,
                        )
                        link_lines = []
                        for idx, u in enumerate(urls, start=1):
                            label = link_label(u, idx)
                            link_lines.append(f"- [{label}]({u})")
                        st.markdown("\n".join(link_lines))
    else:
        dept = dept_filter
        cols = st.columns(2) if prev_row is not None else [st]

        # 현재(선택) 기간
        cur_text = ""
        if dept in row.index and pd.notna(row[dept]):
            cur_text = str(row[dept])

        with cols[0]:
            with st.container(border=True):
                st.markdown(f"**{selected_week} · {dept}**")
                ta_key_cur = f"ta_{dept}_{selected_week}"
                edited_cur = st.text_area(
                    label=f"{selected_week} · {dept} 업무 내용",
                    value=cur_text,
                    height=450,
                    key=ta_key_cur,
                    label_visibility="collapsed",
                    on_change=save_cell,
                    args=(int(row["_sheet_row"]), dept, ta_key_cur),
                )
                edited_single[selected_week] = edited_cur

                urls_cur = extract_urls(edited_cur)
                if urls_cur:
                    st.markdown(
                        "<div style='margin-top:0.25rem; font-size:0.8rem; color:#374151;'>링크 바로가기:</div>",
                        unsafe_allow_html=True,
                    )
                    link_lines = []
                    for idx, u in enumerate(urls_cur, start=1):
                        label = link_label(u, idx)
                        link_lines.append(f"- [{label}]({u})")
                    st.markdown("\n".join(link_lines))

        # 직전 기간
        if prev_row is not None:
            prev_week = str(prev_row[WEEK_COL])
            prev_text = ""
            if dept in prev_row.index and pd.notna(prev_row[dept]):
                prev_text = str(prev_row[dept])

            with cols[1]:
                with st.container(border=True):
                    st.markdown(f"**{prev_week} · {dept}**")
                    ta_key_prev = f"ta_{dept}_{prev_week}"
                    edited_prev = st.text_area(
                        label=f"{prev_week} · {dept} 업무 내용",
                        value=prev_text,
                        height=450,
                        key=ta_key_prev,
                        label_visibility="collapsed",
                        on_change=save_cell,
                        args=(int(prev_row["_sheet_row"]), dept, ta_key_prev),
                    )
                    edited_single[prev_week] = edited_prev

                    urls_prev = extract_urls(edited_prev)
                    if urls_prev:
                        st.markdown(
                            "<div style='margin-top:0.25rem; font-size:0.8rem; color:#374151;'>링크 바로가기:</div>",
                            unsafe_allow_html=True,
                        )
                        link_lines = []
                        for idx, u in enumerate(urls_prev, start=1):
                            label = link_label(u, idx)
                            link_lines.append(f"- [{label}]({u})")
                        st.markdown("\n".join(link_lines))

    # ---------- 저장 버튼 ----------
    if st.button("변경 내용 저장", type="primary"):
        cells = []

        if dept_filter == "전체 부서":
            sheet_row = int(row["_sheet_row"])
            for dept, val in edited_values.items():
                col_idx = get_col_index(ws, dept)
                if col_idx is not None:
                    cells.append(Cell(row=sheet_row, col=col_idx, value=val))
        else:
            dept = dept_filter
            col_idx = get_col_index(ws, dept)
            if col_idx is not None:
                for week_str, text in edited_single.items():
                    row_match = df[df[WEEK_COL] == week_str]
                    if not row_match.empty:
                        sheet_row = int(row_match.iloc[0]["_sheet_row"])
                        cells.append(Cell(row=sheet_row, col=col_idx, value=text))

        if not cells:
            st.error("저장할 대상 부서를 찾지 못했습니다. 헤더 이름을 확인해 주세요.")
        else:
            ws.update_cells(cells)
            load_data.clear()
            st.success("구글 시트에 저장되었습니다.")
            st.rerun()

    # ---------- 인쇄 미리보기 ----------
    if st.session_state.get("print_requested"):
        title_html = escape_html(app_title)
        week_html = escape_html(selected_week)

        sections_html = ""

        if dept_filter == "전체 부서":
            for dept in dept_cols:
                content = ""
                if dept in row.index and pd.notna(row[dept]):
                    content = str(row[dept])
                content_html = escape_html(content)
                sections_html += f"""
                <div class="dept-card">
                    <div class="dept-title">{escape_html(dept)}</div>
                    <div class="dept-body">{content_html}</div>
                </div>
                """
        else:
            dept = dept_filter
            content = ""
            if dept in row.index and pd.notna(row[dept]):
                content = str(row[dept])
            content_html = escape_html(content)
            sections_html += f"""
            <div class="dept-card">
                <div class="dept-title">{escape_html(dept)}</div>
                <div class="dept-body">{content_html}</div>
            </div>
            """

        html = f"""
        <html>
          <head>
            <meta charset="utf-8" />
            <title>{title_html}</title>
            <style>
              @page {{
                size: A4;
                margin: 10mm;
              }}
              body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                font-size: 11px;
                color: #111;
              }}
              h1 {{
                font-size: 16px;
                margin-bottom: 0.3rem;
              }}
              h2 {{
                font-size: 13px;
                margin: 0 0 0.6rem 0;
              }}

              .dept-grid {{
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
              }}
              .dept-card {{
                box-sizing: border-box;
                flex: 1 1 calc(50% - 8px);
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 6px 8px;
                page-break-inside: avoid;
              }}
              .dept-title {{
                font-size: 11px;
                font-weight: 700;
                margin-bottom: 3px;
              }}
              .dept-body {{
                font-size: 10px;
                white-space: normal;
              }}

              @media print {{
                .dept-card {{
                  break-inside: avoid;
                }}
              }}
            </style>
          </head>
          <body>
            <h1>{title_html}</h1>
            <h2>{week_html}</h2>
            <div class="dept-grid">
              {sections_html}
            </div>
            <script>
              window.print();
            </script>
          </body>
        </html>
        """
        components.html(html, height=0, width=0)
        st.session_state["print_requested"] = False


if __name__ == "__main__":
    main()
```
