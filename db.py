"""
백엔드 (SQLite)

데모/프로토타입용 로컬 DB. 본사 IT가 본사 서버로 옮길 때는
이 파일의 함수 시그니처를 유지한 채 내부를 사내 DB(MySQL 등)나
구글시트 API 호출로 교체하면 앱 코드는 그대로 동작한다.

시트 5종
  sites          현장DB (단가 제외)
  windows        창호목록 (설치위치 = A/S 체크박스 소스)
  incidents      당일현장사고 티켓 (1차 잠정귀책 / 2차 확정귀책 / 상태)
  registrations  고객 정품등록
  as_requests    고객 A/S 접수
  notif_logs     알림 발송 로그
"""
import json
import os
import sqlite3

from util import now_kst, now_kst_str
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "kcc_qr.db")

FAULTS = ["공장 오제작", "오출고·미출고", "실측 오류", "영업 주문실수"]
STATUS = ["접수", "가공처확인", "처리예정", "처리완료"]
ISSUE_TYPES = ["당일사고", "입주전AS"]   # 시공팀(현장) 앱에서 신고하는 유형
# 입주전AS는 운반/타공정 훼손 귀책이 추가로 발생
FAULTS_PRE = FAULTS + ["운반·시공 파손", "타공정 훼손"]

# 데모용 '누적 시공 창호' 기준선(하자율 분모). 실서버에선 sites/windows 실집계로 대체.
VENDOR_BASELINE = {"미성산업": 720, "A유리산업": 540, "B창호": 380, "C산업": 210}


def baseline():
    return dict(VENDOR_BASELINE), sum(VENDOR_BASELINE.values())


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS sites(
        quote_no TEXT PRIMARY KEY, order_no TEXT, team TEXT,
        sales_rep TEXT, sales_phone TEXT, constructor TEXT,
        constructor_phone TEXT, vendor TEXT, order_date TEXT,
        address TEXT, install_date TEXT, qr_serial TEXT);
    CREATE TABLE IF NOT EXISTS windows(
        id INTEGER PRIMARY KEY AUTOINCREMENT, quote_no TEXT, seq INTEGER,
        location TEXT, model TEXT, width TEXT, height TEXT, qty TEXT);
    CREATE TABLE IF NOT EXISTS incidents(
        id INTEGER PRIMARY KEY AUTOINCREMENT, quote_no TEXT, vendor TEXT,
        issue_type TEXT, reporter TEXT,
        window_location TEXT, fault_provisional TEXT, fault_confirmed TEXT,
        status TEXT, photo TEXT, note TEXT, vendor_schedule TEXT,
        done_photo TEXT, created_at TEXT, confirmed_at TEXT);
    CREATE TABLE IF NOT EXISTS registrations(
        quote_no TEXT PRIMARY KEY, customer_phone TEXT,
        movein_date TEXT, registered_at TEXT);
    CREATE TABLE IF NOT EXISTS as_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT, quote_no TEXT,
        locations TEXT, symptoms TEXT, note TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS notif_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER,
        target TEXT, channel TEXT, content TEXT, sent_at TEXT);
    """)
    c.commit()
    c.close()


def _add_site(c, site, qr_serial=None):
    c.execute("""INSERT OR REPLACE INTO sites VALUES
        (?,?,?,?,?,?,?,?,?,?,?,?)""", (
        site["quote_no"], site.get("order_no", ""), site["team"],
        site["sales_rep"], site["sales_phone"], site["constructor"],
        site["constructor_phone"], site["vendor"], site["order_date"],
        site["address"], site["install_date"], qr_serial))
    c.execute("DELETE FROM windows WHERE quote_no=?", (site["quote_no"],))
    for w in site["windows"]:
        c.execute("""INSERT INTO windows(quote_no,seq,location,model,width,height,qty)
            VALUES(?,?,?,?,?,?,?)""", (
            site["quote_no"], w["seq"], w["location"], w["model"],
            w["width"], w["height"], w["qty"]))


def seed_if_empty():
    """최초 1회: 실데이터 1현장 + 데모용 합성 현장/사고 적재."""
    init_db()
    c = conn()
    if c.execute("SELECT COUNT(*) FROM sites").fetchone()[0] > 0:
        c.close()
        return

    # 1) 실데이터: 방배 임광 현장
    real = json.load(open(os.path.join(os.path.dirname(__file__), "seed_site.json"), encoding="utf-8"))
    _add_site(c, real)

    # 2) 데모용 합성 현장 (대시보드를 살리기 위함)
    synth = [
        dict(quote_no="900000-002301-280-001", order_no="", team="서울", sales_rep="박종한",
             sales_phone="01040096860", constructor="다솔창호", constructor_phone="010-3543-4281",
             vendor="미성산업", order_date="2026-06-10", install_date="2026-06-25",
             address="서울특별시 강남구 역삼로 102 (역삼동, e편한세상)102동 1503호",
             windows=[dict(seq=1, location="1번 거실발코니", model="HW ONE(V)_HBF251D", width="3300", height="2300", qty="1"),
                      dict(seq=2, location="2번 안방", model="HW ONE(V)_HBF141S", width="2400", height="1300", qty="1")]),
        dict(quote_no="900000-002288-280-001", order_no="", team="서울", sales_rep="김서연",
             sales_phone="01055551234", constructor="으뜸창호", constructor_phone="010-7777-1212",
             vendor="A유리산업", order_date="2026-06-05", install_date="2026-06-20",
             address="서울특별시 강남구 도곡로 425 (도곡동, 타워팰리스)B동 2201호",
             windows=[dict(seq=1, location="1번 거실발코니", model="HW ONE(V)_HBF251D", width="3500", height="2350", qty="1"),
                      dict(seq=2, location="6번 침실2", model="HW ONE(V)_BF230R", width="1800", height="1200", qty="1")]),
        dict(quote_no="900000-002270-280-001", order_no="", team="서울", sales_rep="이준호",
             sales_phone="01066667777", constructor="한빛창호", constructor_phone="010-3030-4040",
             vendor="B창호", order_date="2026-06-01", install_date="2026-06-15",
             address="서울특별시 서초구 방배로 88 (방배동, 신동아)5동 808호",
             windows=[dict(seq=1, location="1번 거실발코니", model="HW ONE(V)_HBF251D", width="3200", height="2300", qty="1"),
                      dict(seq=2, location="7번 주방싱크창", model="HW ONE(V)_HBF251D", width="1100", height="600", qty="1")]),
    ]
    for s in synth:
        _add_site(c, s)

    # 3) 데모용 사고 티켓
    #    (a) 누적 확정 사고: 가공처별 하자율 ~2~3% 가 나오도록 분포 생성
    #    (b) 실시간 데모용 활성 사고: 상세 4현장 참조 (확정 큐/에스컬레이션용)
    import random
    now = now_kst()
    locs_pool = ["1번 거실발코니", "2번 안방", "6번 침실2", "7번 주방싱크창", "5번 안방내창"]
    quote_pool = ["900000-002336-280-001", "900000-002301-280-001",
                  "900000-002288-280-001", "900000-002270-280-001"]

    vendor_confirmed = {"미성산업": 22, "A유리산업": 13, "B창호": 7, "C산업": 3}
    fault_weights = {"공장 오제작": 0.41, "오출고·미출고": 0.21, "실측 오류": 0.28, "영업 주문실수": 0.10}
    faults_seq = []
    for f, w in fault_weights.items():
        faults_seq += [f] * round(w * 45)
    random.seed(7)
    random.shuffle(faults_seq)
    fi = 0
    for vendor, cnt in vendor_confirmed.items():
        for _ in range(cnt):
            f = faults_seq[fi % len(faults_seq)]; fi += 1
            created = (now - timedelta(days=random.randint(1, 25),
                                       hours=random.randint(0, 12))).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("""INSERT INTO incidents
                (quote_no,vendor,issue_type,reporter,window_location,fault_provisional,fault_confirmed,status,
                 photo,note,vendor_schedule,done_photo,created_at,confirmed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (random.choice(quote_pool), vendor, "당일사고", "시공팀", random.choice(locs_pool),
                 f, f, "처리완료", "(사진)", "", "", "(완료사진)", created, created))

    active = [
        ("900000-002336-280-001", "미성산업",  "1번 거실발코니", "공장 오제작",   None,          "접수",     38),
        ("900000-002270-280-001", "B창호",     "7번 주방싱크창", "실측 오류",     None,          "접수",     12),
        ("900000-002288-280-001", "A유리산업", "6번 침실2",      "공장 오제작",   "공장 오제작", "가공처확인", 60),
        ("900000-002301-280-001", "미성산업",  "2번 안방",        "오출고·미출고", None,          "처리예정", 180),
    ]
    for qno, vendor, loc, prov, conf, status, mins_ago in active:
        created = (now - timedelta(minutes=mins_ago)).strftime("%Y-%m-%d %H:%M:%S")
        confirmed_at = created if conf else None
        c.execute("""INSERT INTO incidents
            (quote_no,vendor,issue_type,reporter,window_location,fault_provisional,fault_confirmed,status,
             photo,note,vendor_schedule,done_photo,created_at,confirmed_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (qno, vendor, "당일사고", "시공팀", loc, prov, conf, status,
             "(사진)", "", "", "", created, confirmed_at))

    # (c) 입주전 AS: 공사중 신고. 라우팅 = 관제+영업 (가공처는 관제 지시).
    pre_as = [
        # 누적 확정 (하자율 집계 포함)
        ("900000-002288-280-001", "A유리산업", "실장",     "1번 거실발코니", "운반·시공 파손", "운반·시공 파손", "처리완료", 1800),
        ("900000-002301-280-001", "미성산업",  "현장소장", "2번 안방",       "타공정 훼손",   "타공정 훼손",   "처리완료", 2600),
        # 활성 (관제 검토 대기 → 관제가 가공처 지시)
        ("900000-002336-280-001", "미성산업",  "대표",     "7번 주방싱크창", "공장 오제작",   None,            "접수",     90),
    ]
    for qno, vendor, reporter, loc, prov, conf, status, mins_ago in pre_as:
        created = (now - timedelta(minutes=mins_ago)).strftime("%Y-%m-%d %H:%M:%S")
        confirmed_at = created if conf else None
        c.execute("""INSERT INTO incidents
            (quote_no,vendor,issue_type,reporter,window_location,fault_provisional,fault_confirmed,status,
             photo,note,vendor_schedule,done_photo,created_at,confirmed_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (qno, vendor, "입주전AS", reporter, loc, prov, conf, status,
             "(사진)", "", "", "", created, confirmed_at))

    c.commit()
    c.close()


# ---- 조회/쓰기 헬퍼 ----
def get_site(quote_no):
    c = conn()
    s = c.execute("SELECT * FROM sites WHERE quote_no=?", (quote_no,)).fetchone()
    if not s:
        c.close()
        return None
    site = dict(s)
    site["windows"] = [dict(w) for w in c.execute(
        "SELECT * FROM windows WHERE quote_no=? ORDER BY seq", (quote_no,)).fetchall()]
    c.close()
    return site


def all_sites():
    c = conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM sites ORDER BY order_date DESC").fetchall()]
    c.close()
    return rows


def add_site(site):
    """발주서 파싱 결과(site dict, windows 포함)를 등록/갱신."""
    c = conn()
    _add_site(c, site)
    c.commit()
    c.close()


ALLOWED_INC_FIELDS = {"status", "vendor_schedule", "done_photo", "confirmed_at", "fault_confirmed"}


def update_incident_field(iid, field, value):
    if field not in ALLOWED_INC_FIELDS:
        return
    c = conn()
    c.execute(f"UPDATE incidents SET {field}=? WHERE id=?", (value, iid))
    c.commit()
    c.close()


def link_qr(quote_no, serial):
    c = conn()
    c.execute("UPDATE sites SET qr_serial=? WHERE quote_no=?", (serial, quote_no))
    c.commit()
    c.close()


def add_incident(quote_no, window_location, fault_provisional,
                 issue_type="당일사고", reporter="시공팀", note="", photo="(사진)"):
    site = get_site(quote_no)
    vendor = site["vendor"] if site else ""
    c = conn()
    cur = c.execute("""INSERT INTO incidents
        (quote_no,vendor,issue_type,reporter,window_location,fault_provisional,fault_confirmed,status,
         photo,note,vendor_schedule,done_photo,created_at,confirmed_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (quote_no, vendor, issue_type, reporter, window_location, fault_provisional, None, "접수",
         photo, note, "", "", now_kst_str(), None))
    iid = cur.lastrowid
    c.commit()
    c.close()
    return iid


def set_incident_status(iid, status):
    c = conn()
    if status == "가공처확인":
        c.execute("UPDATE incidents SET status=?, confirmed_at=? WHERE id=?",
                  (status, now_kst_str(), iid))
    else:
        c.execute("UPDATE incidents SET status=? WHERE id=?", (status, iid))
    c.commit()
    c.close()


def confirm_fault(iid, fault_confirmed):
    """관제 2차 확정."""
    c = conn()
    c.execute("UPDATE incidents SET fault_confirmed=? WHERE id=?", (fault_confirmed, iid))
    c.commit()
    c.close()


def all_incidents():
    c = conn()
    rows = [dict(r) for r in c.execute(
        "SELECT * FROM incidents ORDER BY created_at DESC").fetchall()]
    c.close()
    return rows


def log_notifs(logs):
    c = conn()
    for lg in logs:
        c.execute("""INSERT INTO notif_logs(incident_id,target,channel,content,sent_at)
            VALUES(?,?,?,?,?)""", (lg["incident_id"], lg["target"], lg["channel"],
                                   lg["content"], lg["sent_at"]))
    c.commit()
    c.close()


def get_registration(quote_no):
    c = conn()
    r = c.execute("SELECT * FROM registrations WHERE quote_no=?", (quote_no,)).fetchone()
    c.close()
    return dict(r) if r else None


def add_registration(quote_no, phone, movein_date):
    c = conn()
    c.execute("""INSERT OR REPLACE INTO registrations VALUES(?,?,?,?)""",
              (quote_no, phone, movein_date, now_kst_str()))
    c.commit()
    c.close()


def add_as_request(quote_no, locations, symptoms, note):
    c = conn()
    c.execute("""INSERT INTO as_requests(quote_no,locations,symptoms,note,created_at)
        VALUES(?,?,?,?,?)""", (quote_no, "·".join(locations), "·".join(symptoms),
                               note, now_kst_str()))
    c.commit()
    c.close()


def all_as_requests():
    c = conn()
    rows = [dict(r) for r in c.execute(
        "SELECT * FROM as_requests ORDER BY created_at DESC").fetchall()]
    c.close()
    return rows
