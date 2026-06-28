"""
구글시트 메인 DB 백엔드 (sheets_db)

db.py(SQLite)와 '동일한 함수 인터페이스'를 제공한다. Secrets 가 설정돼 있으면
app.py 가 이 모듈을 db 로 사용 → 모든 데이터(현장/사고/귀책/정품/AS/알림)가
구글시트에 영구 저장된다. (Streamlit Cloud 재시작에도 유지)

성능: 구글 API 호출이 많으면 느리고 할당량(분당 읽기 제한)에 걸리므로,
각 탭을 '한 번 읽어 캐시'(@st.cache_data ttl)하고 메모리에서 필터한다.
쓰기 시 캐시를 비운다.

시드: 시트가 비어 있으면 db.py(SQLite) 시드를 그대로 생성해 시트로 '미러링'한다.
"""
import streamlit as st

from util import now_kst_str
# 백엔드와 무관한 상수/계산은 db.py 의 것을 재사용
from db import FAULTS, FAULTS_PRE, ISSUE_TYPES, STATUS, VENDOR_BASELINE, baseline  # noqa: F401

# 탭(워크시트)별 헤더 — 컬럼 순서가 곧 행 순서
TABS = {
    "sites": ["quote_no", "order_no", "team", "sales_rep", "sales_phone", "constructor",
              "constructor_phone", "vendor", "order_date", "address", "install_date", "qr_serial"],
    "windows": ["quote_no", "seq", "location", "model", "width", "height", "qty"],
    "incidents": ["id", "quote_no", "vendor", "issue_type", "reporter", "window_location",
                  "fault_provisional", "fault_confirmed", "status", "photo", "note",
                  "vendor_schedule", "done_photo", "created_at", "confirmed_at"],
    "registrations": ["quote_no", "customer_phone", "movein_date", "registered_at"],
    "as_requests": ["id", "quote_no", "locations", "symptoms", "note", "created_at"],
    "notif_logs": ["id", "incident_id", "target", "channel", "content", "sent_at"],
}

RAW = "RAW"  # quote_no/전화번호/날짜의 자동 변환 방지


# ───────────────────── 연결 / 워크시트 ─────────────────────
@st.cache_resource(show_spinner=False)
def _spreadsheet():
    import gspread
    gc = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    return gc.open_by_key(st.secrets["sheet_key"])


def _ws(name):
    ss = _spreadsheet()
    try:
        return ss.worksheet(name)
    except Exception:
        w = ss.add_worksheet(title=name, rows=2000, cols=len(TABS[name]))
        w.append_row(TABS[name], value_input_option=RAW)
        return w


@st.cache_data(ttl=6, show_spinner=False)
def _rows(name):
    """탭 전체를 dict 리스트로 (캐시). 없으면 생성."""
    return _ws(name).get_all_records(expected_headers=TABS[name])


def _invalidate():
    _rows.clear()


def _row_for(name, d):
    """dict → 헤더 순서 리스트 (None/누락은 빈칸)."""
    out = []
    for h in TABS[name]:
        v = d.get(h, "")
        out.append("" if v is None else v)
    return out


def _next_id(name):
    ids = [int(r["id"]) for r in _rows(name) if str(r.get("id", "")).strip().lstrip("-").isdigit()]
    return (max(ids) + 1) if ids else 1


def _find_row(name, key_col, value):
    """key_col 값이 value 인 행의 (worksheet, 행번호). 없으면 (ws, None)."""
    ws = _ws(name)
    col = TABS[name].index(key_col) + 1
    cells = ws.col_values(col)  # 1행은 헤더
    for idx, v in enumerate(cells[1:], start=2):
        if str(v) == str(value):
            return ws, idx
    return ws, None


# ───────────────────── 시드 (미러링) ─────────────────────
def seed_if_empty():
    if _rows("sites"):           # 이미 데이터 있으면 스킵 (영속성 핵심)
        return
    import db as _sq             # SQLite 시드 로직 재사용 (드리프트 방지)
    _sq.seed_if_empty()

    sites = _sq.all_sites()
    _ws("sites").append_rows([_row_for("sites", s) for s in sites], value_input_option=RAW)

    win_rows = []
    for s in sites:
        for w in _sq.get_site(s["quote_no"])["windows"]:
            win_rows.append(_row_for("windows", {**w, "quote_no": s["quote_no"]}))
    if win_rows:
        _ws("windows").append_rows(win_rows, value_input_option=RAW)

    incs = _sq.all_incidents()
    if incs:
        _ws("incidents").append_rows([_row_for("incidents", i) for i in incs], value_input_option=RAW)
    _invalidate()


# ───────────────────── 조회 ─────────────────────
def all_sites():
    return sorted(_rows("sites"), key=lambda r: str(r.get("order_date", "")), reverse=True)


def get_site(quote_no):
    rows = [r for r in _rows("sites") if str(r["quote_no"]) == str(quote_no)]
    if not rows:
        return None
    site = dict(rows[0])
    site["windows"] = sorted(
        [dict(w) for w in _rows("windows") if str(w["quote_no"]) == str(quote_no)],
        key=lambda w: int(w["seq"]) if str(w["seq"]).isdigit() else 0)
    return site


def all_incidents():
    return sorted(_rows("incidents"), key=lambda r: str(r.get("created_at", "")), reverse=True)


def all_as_requests():
    return sorted(_rows("as_requests"), key=lambda r: str(r.get("created_at", "")), reverse=True)


def get_registration(quote_no):
    rows = [r for r in _rows("registrations") if str(r["quote_no"]) == str(quote_no)]
    return dict(rows[0]) if rows else None


# ───────────────────── 쓰기 ─────────────────────
def link_qr(quote_no, serial):
    ws, row = _find_row("sites", "quote_no", quote_no)
    if row:
        ws.update_cell(row, TABS["sites"].index("qr_serial") + 1, serial)
    _invalidate()


def add_incident(quote_no, window_location, fault_provisional,
                 issue_type="당일사고", reporter="시공팀", note="", photo="(사진)"):
    site = get_site(quote_no)
    vendor = site["vendor"] if site else ""
    iid = _next_id("incidents")
    _ws("incidents").append_row(_row_for("incidents", {
        "id": iid, "quote_no": quote_no, "vendor": vendor, "issue_type": issue_type,
        "reporter": reporter, "window_location": window_location,
        "fault_provisional": fault_provisional, "fault_confirmed": "", "status": "접수",
        "photo": photo, "note": note, "created_at": now_kst_str(), "confirmed_at": "",
    }), value_input_option=RAW)
    _invalidate()
    return iid


def set_incident_status(iid, status):
    ws, row = _find_row("incidents", "id", iid)
    if row:
        ws.update_cell(row, TABS["incidents"].index("status") + 1, status)
        if status == "가공처확인":
            ws.update_cell(row, TABS["incidents"].index("confirmed_at") + 1, now_kst_str())
    _invalidate()


def confirm_fault(iid, fault_confirmed):
    ws, row = _find_row("incidents", "id", iid)
    if row:
        ws.update_cell(row, TABS["incidents"].index("fault_confirmed") + 1, fault_confirmed)
    _invalidate()


def log_notifs(logs):
    if not logs:
        return
    base = _next_id("notif_logs")
    ws = _ws("notif_logs")
    rows = []
    for k, lg in enumerate(logs):
        rows.append(_row_for("notif_logs", {
            "id": base + k, "incident_id": lg.get("incident_id", ""), "target": lg["target"],
            "channel": lg["channel"], "content": lg["content"], "sent_at": lg["sent_at"],
        }))
    ws.append_rows(rows, value_input_option=RAW)
    _invalidate()


def add_registration(quote_no, phone, movein_date):
    ws, row = _find_row("registrations", "quote_no", quote_no)
    vals = {"quote_no": quote_no, "customer_phone": phone,
            "movein_date": movein_date, "registered_at": now_kst_str()}
    if row:
        for col, h in enumerate(TABS["registrations"], start=1):
            ws.update_cell(row, col, vals[h])
    else:
        _ws("registrations").append_row(_row_for("registrations", vals), value_input_option=RAW)
    _invalidate()


def add_as_request(quote_no, locations, symptoms, note):
    iid = _next_id("as_requests")
    _ws("as_requests").append_row(_row_for("as_requests", {
        "id": iid, "quote_no": quote_no, "locations": "·".join(locations),
        "symptoms": "·".join(symptoms), "note": note, "created_at": now_kst_str(),
    }), value_input_option=RAW)
    _invalidate()
