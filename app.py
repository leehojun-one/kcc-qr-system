"""
KCC 홈씨씨 창호 QR·바코드 관제 시스템 (프로토타입)

실행:  streamlit run app.py

3개 화면을 좌측에서 전환:
  1) 시공팀 앱  — 바코드+QR 현장등록 / 당일사고 등록(1차 귀책)
  2) 고객 앱    — 정품등록 / A/S 접수 (내부정보 비노출)
  3) 관제센터   — 사고 동시수신 + 2차 귀책확정 + 하자율 대시보드

백엔드는 db.py(SQLite). 본사 서버 이관 시 db.py 내부만 교체.
알림은 notify.py(데모 시뮬레이션, 솔라피 훅 분리).
"""
import streamlit as st

import notify
import db as sqlite_db
import sheets_db
from barcode_qr import make_barcode_png, make_qr_png, make_qr_sheet_pdf
import parser as order_parser

try:
    from streamlit_qrcode_scanner import qrcode_scanner
    HAS_SCANNER = True
except Exception:
    HAS_SCANNER = False


def parse_scanned_serial(text):
    """스캔/입력된 QR 텍스트에서 일련번호(KCCQR-xxxx)만 뽑기.
    URL(...?qr=KCCQR-0001)이든 일련번호 자체든 모두 처리."""
    if not text:
        return ""
    text = text.strip()
    if "qr=" in text:
        text = text.split("qr=", 1)[1].split("&")[0]
    return text.strip()

SYMPTOMS = ["새바람(틈새풍)", "물방울(결로)", "빗물 샘", "핸들 불량", "구동 불량(뻑뻑함)", "잠금 불량", "소음"]

st.set_page_config(page_title="KCC 창호 QR 관제", page_icon="🪟", layout="wide")


def pin_gate(name, secret_key):
    """관리자/관제용 PIN 잠금. Secrets에 없으면 로컬 기본 '0000'."""
    if st.session_state.get(f"ok_{name}"):
        return True
    try:
        pin = str(st.secrets[secret_key])
    except Exception:
        pin = "0000"
    e = st.text_input("🔒 PIN 입력", type="password", key=f"pin_{name}")
    if e and e == pin:
        st.session_state[f"ok_{name}"] = True
        return True
    if e:
        st.error("PIN이 틀렸습니다.")
    st.caption("본사 전용 화면입니다. (로컬 기본 PIN: 0000 · 배포 시 Secrets에 설정)")
    return False


def _pick_backend():
    """Secrets 에 구글시트 설정이 있으면 시트 백엔드(영구), 없으면 로컬 SQLite(임시)."""
    try:
        if ("gcp_service_account" in st.secrets) and ("sheet_key" in st.secrets):
            return sheets_db, True
    except Exception:
        pass
    return sqlite_db, False


db, USE_SHEETS = _pick_backend()
db.seed_if_empty()

# 배포 후 Streamlit Secrets 에 base_url 을 넣으면 QR이 이 앱 주소로 연결됨
try:
    BASE_URL = st.secrets["base_url"]
except Exception:
    BASE_URL = ""


def site_label(s):
    addr = s["address"].split("(")[0].strip()
    return f'{s["quote_no"]}  |  {addr}'


# ───────── QR 스캔 진입 (쿼리 파라미터 ?qr=일련번호) ─────────
params = st.query_params
scan_serial = params.get("qr")
scan_qno = None
if scan_serial:
    for s in db.all_sites():
        if s.get("qr_serial") == scan_serial:
            scan_qno = s["quote_no"]
            break
role_q = params.get("role")   # 'partner' | 'customer'

# QR만 찍고 들어온 상태 → 누구인지 한 번 고르는 랜딩
if scan_serial and role_q not in ("partner", "customer"):
    st.title("🪟 KCC 창호")
    if scan_qno:
        site = db.get_site(scan_qno)
        st.write(f'📍 {site["address"].split("(")[0].strip()}')
        st.write("이 QR로 무엇을 하시겠어요?")
        c1, c2 = st.columns(2)
        if c1.button("🏠 입주민 — 정품등록 / A/S", type="primary"):
            st.query_params["role"] = "customer"
            st.rerun()
        if c2.button("🛠️ 현장 관리자(파트너사) — 입주전 AS"):
            st.query_params["role"] = "partner"
            st.rerun()
    else:
        st.warning("아직 연결되지 않은 QR입니다. 시공팀 앱에서 현장에 QR을 먼저 연결하세요.")
    st.stop()

# ───────────────────────── 사이드바 / 역할 결정 ─────────────────────────
st.sidebar.title("🪟 KCC 창호 QR 관제")
if role_q == "partner":
    role = "② 파트너사 앱"
    st.sidebar.success("📷 QR 스캔으로 열림 (파트너사)")
    if st.sidebar.button("← 전체 메뉴"):
        st.query_params.clear(); st.rerun()
elif role_q == "customer":
    role = "③ 고객 앱"
    st.sidebar.success("📷 QR 스캔으로 열림 (고객)")
    if st.sidebar.button("← 전체 메뉴"):
        st.query_params.clear(); st.rerun()
else:
    role = st.sidebar.radio("화면 선택",
                            ["① 시공팀 앱", "② 파트너사 앱", "③ 고객 앱",
                             "④ 관제센터", "⑤ 관리자(발행)", "⑥ 가공처", "⑦ 영업사원"])
st.sidebar.caption("프로토타입 · 카톡 발송은 시뮬레이션")
if USE_SHEETS:
    st.sidebar.caption("🗄️ 저장소: 구글시트 (영구 · KST)")
else:
    st.sidebar.caption("🗄️ 저장소: 로컬 SQLite (임시 · KST)")


# ═══════════════════════ ① 시공팀 앱 ═══════════════════════
if role.startswith("①"):
    st.header("① 시공팀 앱")
    tab1, tab2 = st.tabs(["📷 현장 등록 (바코드+QR)", "🚨 당일사고 등록"])

    sites = db.all_sites()
    site_map = {site_label(s): s["quote_no"] for s in sites}

    with tab1:
        st.subheader("현장 등록")
        st.caption("① 발주서 바코드 → ② 거실 메인창 QR 스캔 → 1:1 매칭")
        use_cam = st.toggle("📷 카메라 스캔 사용", value=False,
                            help="끄면 번호 선택/입력 방식. 폰에서 카메라가 안 켜지면 끄고 진행하세요.")
        if use_cam and not HAS_SCANNER:
            st.warning("이 환경에서 카메라 스캐너를 불러오지 못했어요. 번호 입력으로 진행합니다.")
            use_cam = False

        reg_qno = st.session_state.get("reg_qno")

        # ── STEP 1: 발주서 바코드 ──
        if not reg_qno:
            st.markdown("**① 발주서 바코드**")
            if use_cam:
                st.caption("카메라를 바코드에 비추세요. (잘 안 잡히면 아래에서 번호로 선택)")
                code = qrcode_scanner(key="scan_bc")
                if code:
                    hit = next((s for s in sites if str(s["quote_no"]) == code.strip()), None)
                    if hit:
                        st.session_state["reg_qno"] = hit["quote_no"]; st.rerun()
                    else:
                        st.error(f"등록되지 않은 현장입니다: {code}  (관리자에서 발주서 등록 먼저)")
            # 번호 선택은 카메라 여부와 무관하게 항상 노출 (막히지 않게)
            if not site_map:
                st.info("등록된 현장이 없어요. ⑤ 관리자에서 발주서를 먼저 올리세요.")
            else:
                pick = st.selectbox("현장(견적번호) 선택", list(site_map.keys()))
                if st.button("이 현장으로 진행 →", type="primary"):
                    st.session_state["reg_qno"] = site_map[pick]; st.rerun()

        # ── STEP 2: 거실창 QR ──
        else:
            site = db.get_site(reg_qno)
            st.success(f'① 바코드 확인 — {reg_qno} · {site["address"].split("(")[0].strip()}')

            if site.get("qr_serial"):
                st.success(f'✅ ② QR 매칭 완료 — {site["qr_serial"]}')
                st.caption("이 현장은 이제 '당일사고 등록' 대상이 됩니다.")
            else:
                st.markdown("**② 거실 메인창 QR (매칭)**")
                if use_cam:
                    st.caption("QR 스티커를 카메라에 비추세요. (잘 안 잡히면 아래에 번호 입력)")
                    qr = qrcode_scanner(key="scan_qr")
                    if qr:
                        serial = parse_scanned_serial(qr)
                        db.link_qr(reg_qno, serial)
                        st.success(f"매칭 완료 — {serial}"); st.rerun()
                # 번호 입력은 항상 노출
                default_serial = f"KCCQR-{reg_qno.split('-')[1]}"
                serial = st.text_input("QR 일련번호 입력", value=default_serial)
                if st.button("✅ QR 연결 (매칭)", type="primary"):
                    db.link_qr(reg_qno, parse_scanned_serial(serial))
                    st.success("매칭 완료"); st.rerun()

            if st.button("↩️ 다른 현장 등록"):
                del st.session_state["reg_qno"]; st.rerun()

            st.divider()
            # 참고용: 인쇄/확인용 바코드·QR
            col1, col2 = st.columns([1, 1])
            with col1:
                st.markdown("**발주서 바코드**")
                st.image(make_barcode_png(reg_qno), caption=f"Code128 · {reg_qno}", width=300)
            with col2:
                serial = site.get("qr_serial") or f"KCCQR-{reg_qno.split('-')[1]}"
                payload = f"{BASE_URL}?qr={serial}" if BASE_URL else serial
                st.markdown("**거실창 QR**")
                st.image(make_qr_png(payload), caption=f"{serial}", width=150)

            st.divider()
            st.markdown("**현장 정보** (단가 제외)")
            c1, c2, c3 = st.columns(3)
            c1.metric("소속팀 / 영업", f'{site["team"]} · {site["sales_rep"]}')
            c2.metric("시공업체", site["constructor"])
            c3.metric("가공처", site["vendor"])
            st.write(f'📍 {site["address"]}')
            st.dataframe(
                [{"순번": w["seq"], "설치위치": w["location"], "모델": w["model"],
                  "W": w["width"], "H": w["height"], "수량": w["qty"]} for w in site["windows"]],
                width='stretch', hide_index=True)

    with tab2:
        st.subheader("당일사고 등록")
        st.caption("설치 당일 사고 = 99% 가공처 액션 → 가공처+관제센터 동시 발송")
        # QR 매칭(현장등록 완료)된 현장만 사고 등록 가능
        matched = [s for s in sites if s.get("qr_serial")]
        if not matched:
            st.warning("아직 QR 매칭된 현장이 없습니다. '현장 등록' 탭에서 바코드+QR 매칭을 먼저 하세요.")
            st.stop()
        m_map = {site_label(s): s["quote_no"] for s in matched}
        pick2 = st.selectbox("현장 (QR 매칭 완료된 현장만)", list(m_map.keys()), key="inc_site")
        qno2 = m_map[pick2]
        site2 = db.get_site(qno2)
        locs = [w["location"] for w in site2["windows"]]

        win = st.selectbox("문제 창 (설치위치)", locs)
        fault = st.radio("1차 귀책 판별 (현장 잠정)", db.FAULTS, horizontal=True)
        note = st.text_area("특이사항", placeholder="예: W치수 3435 → 실측 3415, 5mm 작음")
        st.file_uploader("📸 현장 사진 첨부", type=["jpg", "jpeg", "png"])

        if st.button("🚨 사고 접수 (가공처+관제 발송)", type="primary"):
            iid = db.add_incident(qno2, win, fault, issue_type="당일사고", reporter="시공팀", note=note)
            inc = {"id": iid, "window_location": win, "fault_provisional": fault, "reporter": "시공팀"}
            logs = notify.dispatch(site2, inc, issue_type="당일사고", simulate=True)
            db.log_notifs(logs)
            st.success(f"접수 완료 (티켓 #{iid}) — 알림 발송됨")
            st.markdown("**발송 시뮬레이션**")
            for lg in logs:
                st.info(f'➡️ {lg["target"]} ({lg["channel"]})\n\n{lg["content"]}')
            st.caption("실제 배포: 솔라피 알림톡+SMS · '접수확인' 전까지 10/30분 에스컬레이션")


# ═══════════════════════ ② 파트너사 앱 ═══════════════════════
elif role.startswith("②"):
    st.header("② 파트너사 앱")
    st.caption("인테리어 공사중·고객 인계 전, 현장 관리자(파트너사)가 접수 → 관제+영업 발송")

    sites = db.all_sites()
    site_map = {site_label(s): s["quote_no"] for s in sites}
    keys = list(site_map.keys())
    pre_idx = next((i for i, k in enumerate(keys) if site_map[k] == scan_qno), 0)
    if scan_qno:
        st.info("📷 QR 스캔으로 열린 현장입니다.")

    pickp = st.selectbox("현장 (발주서 바코드 / QR)", keys, index=pre_idx)
    qnop = site_map[pickp]
    sitep = db.get_site(qnop)
    st.write(f'📍 {sitep["address"]}  ·  영업 {sitep["sales_rep"]}')

    reporter = st.selectbox("신고자 (파트너사 현장 관리자)", ["대표", "실장", "현장소장"])
    locs = [w["location"] for w in sitep["windows"]]
    win = st.selectbox("문제 창 (설치위치)", locs)
    fault = st.radio("1차 귀책 판별 (현장 잠정)", db.FAULTS_PRE, horizontal=True)
    note = st.text_area("특이사항", placeholder="예: 타공정 작업 중 거실창 프레임 스크래치")
    st.file_uploader("📸 현장 사진 첨부", type=["jpg", "jpeg", "png"])

    if st.button("📩 입주전 AS 접수 (관제+영업 발송)", type="primary"):
        iid = db.add_incident(qnop, win, fault, issue_type="입주전AS", reporter=reporter, note=note)
        inc = {"id": iid, "window_location": win, "fault_provisional": fault, "reporter": reporter}
        logs = notify.dispatch(sitep, inc, issue_type="입주전AS", simulate=True)
        db.log_notifs(logs)
        st.success(f"접수 완료 (티켓 #{iid}) — 관제+영업에 발송됨")
        st.markdown("**발송 시뮬레이션**")
        for lg in logs:
            st.info(f'➡️ {lg["target"]} ({lg["channel"]})\n\n{lg["content"]}')
        st.caption("가공처는 받지 않음 — 관제센터가 검토 후 필요 시 '가공처에 지시 발송' · 30/120분 에스컬레이션")
elif role.startswith("③"):
    st.header("③ 고객 앱")
    st.caption("입주 후 거실 메인창 QR 스캔 → 첫 스캔=정품등록, 이후=A/S 접수")

    sites = db.all_sites()
    qr_map = {s.get("qr_serial"): s["quote_no"] for s in sites if s.get("qr_serial")}

    if not qr_map:
        st.warning("아직 QR이 연결된 현장이 없어요. ① 시공팀 앱 > 현장등록에서 'QR 연결'을 먼저 누르세요.")
        st.stop()

    if scan_serial and scan_serial in qr_map:
        serial = scan_serial
        st.info(f"📷 QR 스캔으로 열림 — {serial}")
    else:
        st.markdown("**QR 스캔** (데모: 일련번호 선택)")
        serial = st.selectbox("스캔된 QR 일련번호", list(qr_map.keys()))
    qno = qr_map[serial]
    site = db.get_site(qno)

    reg = db.get_registration(qno)
    if not reg:
        st.subheader("🎁 정품 등록")
        st.caption("KCC 본사 13년 품질보증 — 연락처를 등록하면 보증/AS 추적이 시작됩니다")
        phone = st.text_input("휴대폰 번호", placeholder="010-0000-0000")
        movein = st.date_input("입주일")
        if st.button("정품 등록", type="primary"):
            if phone.strip():
                db.add_registration(qno, phone.strip(), str(movein))
                st.success("등록 완료! 이제 같은 QR을 다시 스캔하면 A/S 접수 화면이 떠요.")
                st.rerun()
            else:
                st.error("휴대폰 번호를 입력하세요.")
    else:
        st.success(f"정품 등록된 세대입니다 (등록일 {reg['registered_at'][:10]})")
        st.subheader("🛠️ A/S 접수")
        st.caption("내부 시공팀/가공처/영업자 정보는 노출되지 않습니다 (본사 DB가 보유)")
        locs = [w["location"] for w in site["windows"]]
        sel_locs = st.multiselect("어느 창에 문제가 있나요?", locs)
        sel_sym = st.multiselect("증상 (해당 항목 체크)", SYMPTOMS)
        free = st.text_area("직접 입력 (목록에 없으면)", placeholder="증상을 직접 적어주세요")
        if st.button("A/S 접수하기", type="primary"):
            if sel_locs and (sel_sym or free.strip()):
                db.add_as_request(qno, sel_locs, sel_sym, free.strip())
                st.success("접수 완료 — 본사 관제탑에 실시간 전달되었습니다. 담당자가 곧 연락드립니다.")
            else:
                st.error("창과 증상을 하나 이상 선택해주세요.")


# ═══════════════════════ ④ 관제센터 ═══════════════════════
elif role.startswith("④"):
    from datetime import datetime

    st.header("④ 본사 관제센터")
    if not pin_gate("control", "control_pin"):
        st.stop()
    sites = db.all_sites()
    incidents = db.all_incidents()
    vendor_base, total_base = db.baseline()

    confirmed = [i for i in incidents if i["fault_confirmed"]]
    pending_confirm = [i for i in incidents if not i["fault_confirmed"]]
    unconfirmed_status = [i for i in incidents if i["status"] == "접수"]

    defect_rate = (len(confirmed) / total_base * 100) if total_base else 0

    # ── KPI ──
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("누적 사고 건수", f"{len(incidents)}건")
    k2.metric("하자율 (확정 기준)", f"{defect_rate:.1f}%")
    k3.metric("누적 시공 창호", f"{total_base:,}")
    k4.metric("미확인(접수상태)", f"{len(unconfirmed_status)}건",
              delta=None if not unconfirmed_status else "확인 필요", delta_color="inverse")
    da = len([i for i in incidents if i["issue_type"] == "당일사고"])
    pre = len([i for i in incidents if i["issue_type"] == "입주전AS"])
    st.caption(f"당일사고 {da}건 · 입주전AS {pre}건  |  사용중 AS(고객·보증)는 하단 별도 집계")

    st.divider()
    colL, colR = st.columns(2)

    # ── 귀책별 분포 (확정 기준) ──
    with colL:
        st.subheader("귀책별 분포")
        st.caption("관제 최종확정 건만 집계")
        dist = {f: 0 for f in db.FAULTS}
        for i in confirmed:
            dist[i["fault_confirmed"]] = dist.get(i["fault_confirmed"], 0) + 1
        tot = sum(dist.values()) or 1
        for f, n in dist.items():
            st.write(f"{f} — {n}건 ({n/tot*100:.0f}%)")
            st.progress(n / tot)

    # ── 가공처별 하자율 ──
    with colR:
        st.subheader("가공처별 하자율")
        st.caption("확정 사고 ÷ 해당 가공처 누적 시공 창호")
        vendor_inc = {}
        for i in confirmed:
            v = i["vendor"] or "?"
            vendor_inc[v] = vendor_inc.get(v, 0) + 1
        rows = []
        for v, wn in vendor_base.items():
            rate = (vendor_inc.get(v, 0) / wn * 100) if wn else 0
            rows.append((v, rate))
        for v, rate in sorted(rows, key=lambda x: -x[1]):
            st.write(f"{v} — {rate:.1f}%")
            st.progress(min(rate / 5, 1.0))

    st.divider()

    # ── 관제 2차 귀책 확정 큐 ──
    st.subheader(f"⚖️ 2차 귀책 확정 대기 ({len(pending_confirm)}건)")
    st.caption("시공팀 1차 잠정귀책 → 관제 검토 후 확정. 확정 전까지는 하자율 통계에서 제외.")
    if not pending_confirm:
        st.info("대기 중인 건이 없습니다.")
    for i in pending_confirm:
        is_pre = i["issue_type"] == "입주전AS"
        flist = db.FAULTS_PRE if is_pre else db.FAULTS
        prov = i["fault_provisional"]
        idx = flist.index(prov) if prov in flist else 0
        with st.container(border=True):
            cc1, cc2, cc3 = st.columns([3, 2, 1])
            site = db.get_site(i["quote_no"])
            tag = "🟡 입주전AS" if is_pre else "🔴 당일사고"
            cc1.write(f'{tag}  **{site["address"].split("(")[0].strip()}** · {i["window_location"]}')
            cc1.caption(f'1차({i["reporter"]}): {prov} · 가공처 {site["vendor"]} · 영업 {site["sales_rep"]}')
            final = cc2.selectbox("최종 귀책", flist, index=idx, key=f"f{i['id']}")
            if cc3.button("확정", key=f"b{i['id']}", type="primary"):
                db.confirm_fault(i["id"], final)
                st.rerun()
            if is_pre:
                if st.button("📤 가공처에 지시 발송", key=f"v{i['id']}"):
                    inc = dict(i)
                    log = notify.instruct_vendor(site, inc, simulate=True)
                    db.log_notifs([log])
                    db.set_incident_status(i["id"], "가공처확인")
                    st.success(f'가공처({site["vendor"]})에 지시 발송 — {log["content"]}')

    st.divider()

    # ── 최근 사고 티켓 + 에스컬레이션 ──
    st.subheader("최근 사고 티켓")
    table = []
    for i in incidents[:12]:
        site = db.get_site(i["quote_no"])
        confirmed_flag = "확정" if i["fault_confirmed"] else "검토중"
        try:
            created = datetime.strptime(i["created_at"], "%Y-%m-%d %H:%M:%S")
            esc = notify.escalation_stage(created, i["status"] != "접수", i["issue_type"])
            esc_txt = "확인됨" if esc["level"] < 0 else f'{esc["minutes"]}분 · {esc["channel"]}'
        except Exception:
            esc_txt = "-"
        table.append({
            "유형": i["issue_type"],
            "현장": site["address"].split("(")[0].strip(),
            "창": i["window_location"],
            "신고자": i["reporter"],
            "1차귀책": i["fault_provisional"],
            "확정": (i["fault_confirmed"] or "—") + f" ({confirmed_flag})",
            "상태": i["status"],
            "에스컬레이션": esc_txt,
        })
    st.dataframe(table, width='stretch', hide_index=True)

    # ── 고객 A/S 접수 현황 ──
    asr = db.all_as_requests()
    if asr:
        st.subheader("고객 A/S 접수")
        st.dataframe(
            [{"접수시각": a["created_at"], "창": a["locations"], "증상": a["symptoms"],
              "직접입력": a["note"]} for a in asr],
            width='stretch', hide_index=True)


# ═══════════════════════ ⑤ 관리자 (발행) ═══════════════════════
elif role.startswith("⑤"):
    st.header("⑤ 관리자 — 바코드·QR 발행")
    if not pin_gate("admin", "admin_pin"):
        st.stop()
    st.caption("견적프로그램 연동 전 임시 발행 도구. 발주서를 올리면 현장 등록 + 바코드 발행.")
    tabA, tabB = st.tabs(["📤 발주서 업로드 → 바코드", "🏷️ QR 100장 일괄 발행"])

    with tabA:
        up = st.file_uploader("시공발주서 (.xlsx)", type=["xlsx"])
        if up is not None:
            import tempfile, os
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tf:
                tf.write(up.getbuffer())
                tmp_path = tf.name
            try:
                site = order_parser.parse_order_sheet(tmp_path)
            finally:
                os.unlink(tmp_path)
            st.success(f'파싱 완료 — {site["quote_no"]} · 창호 {len(site["windows"])}개')
            st.write(f'📍 {site["address"]}  ·  {site["team"]}/{site["sales_rep"]} · 가공처 {site["vendor"]}')
            if st.button("이 현장 등록 + 바코드 발행", type="primary"):
                db.add_site(site)
                st.success("현장 등록 완료")
            bc = make_barcode_png(site["quote_no"])
            st.image(bc, caption=f'바코드 · {site["quote_no"]}', width=320)
            st.download_button("⬇️ 바코드 PNG 다운로드", bc,
                               file_name=f'barcode_{site["quote_no"]}.png', mime="image/png")
        st.divider()
        st.markdown("**기존 등록 현장 바코드 다시 받기**")
        sites = db.all_sites()
        if sites:
            smap = {site_label(s): s["quote_no"] for s in sites}
            pk = st.selectbox("현장", list(smap.keys()))
            bc2 = make_barcode_png(smap[pk])
            st.image(bc2, width=300)
            st.download_button("⬇️ 바코드 PNG", bc2,
                               file_name=f"barcode_{smap[pk]}.png", mime="image/png", key="dl2")

    with tabB:
        st.caption("빈 고유번호 QR을 미리 대량 발행 → 인쇄해두고 현장에서 바코드와 매칭")
        c1, c2 = st.columns(2)
        start = c1.number_input("시작 번호", min_value=1, value=1, step=1)
        count = c2.number_input("발행 장수", min_value=1, max_value=500, value=100, step=10)
        if not BASE_URL:
            st.warning("아직 base_url 미설정 — QR엔 일련번호만 담깁니다. Secrets에 base_url 넣으면 스캔 시 앱이 열려요.")
        if st.button("QR 일괄 생성 (PDF)", type="primary"):
            serials = [f"KCCQR-{i:04d}" for i in range(int(start), int(start) + int(count))]
            pdf = make_qr_sheet_pdf(serials, base_url=BASE_URL)
            st.success(f"{len(serials)}장 생성 완료")
            st.download_button("⬇️ QR 시트 PDF 다운로드", pdf,
                               file_name=f"QR_{serials[0]}_{serials[-1]}.pdf", mime="application/pdf")


# ═══════════════════════ ⑥ 가공처 ═══════════════════════
elif role.startswith("⑥"):
    st.header("⑥ 가공처")
    sites = db.all_sites()
    vendors = db.VENDORS
    vendor = st.selectbox("가공처 선택", vendors) if vendors else None
    st.caption("내게 접수된 사고를 확인하고 처리예정/완료를 입력 (파일럿: 앱 내 알람·피드백)")

    incidents = [i for i in db.all_incidents() if i.get("vendor") == vendor]
    new_cnt = len([i for i in incidents if i["status"] == "접수"])
    if new_cnt:
        st.error(f"🔔 새 사고 {new_cnt}건 — 접수확인이 필요합니다")
    if not incidents:
        st.info("접수된 사고가 없습니다.")

    for i in incidents:
        site = db.get_site(i["quote_no"])
        with st.container(border=True):
            head = "🚨 당일사고" if i["issue_type"] == "당일사고" else "🟡 입주전AS"
            st.write(f'{head} · **{site["address"].split("(")[0].strip()}** · {i["window_location"]}')
            st.caption(f'사유: {i["fault_provisional"]} · 신고: {i["reporter"]} · 상태: {i["status"]} · {i["created_at"]}')
            cc1, cc2, cc3 = st.columns(3)
            if i["status"] == "접수":
                if cc1.button("✅ 접수확인", key=f"v_ack{i['id']}", type="primary"):
                    db.set_incident_status(i["id"], "가공처확인"); st.rerun()
            sched = cc2.text_input("처리예정일", value=i.get("vendor_schedule", ""), key=f"sch{i['id']}",
                                   placeholder="예: 7/15 재제작")
            if cc2.button("일정 저장", key=f"vs{i['id']}"):
                db.update_incident_field(i["id"], "vendor_schedule", sched)
                db.set_incident_status(i["id"], "처리예정"); st.rerun()
            if cc3.button("처리완료", key=f"done{i['id']}"):
                db.update_incident_field(i["id"], "done_photo", "(완료사진)")
                db.set_incident_status(i["id"], "처리완료"); st.rerun()


# ═══════════════════════ ⑦ 영업사원 ═══════════════════════
else:
    st.header("⑦ 영업사원")
    sites = db.all_sites()
    reps = sorted({s["sales_rep"] for s in sites if s.get("sales_rep")})
    rep = st.selectbox("영업사원 선택", reps) if reps else None
    st.caption("내 담당 현장의 사고/AS를 열람 (처리는 가공처·관제, 영업은 상황 파악 전용)")

    my_qnos = {s["quote_no"] for s in sites if s["sales_rep"] == rep}
    my_inc = [i for i in db.all_incidents() if i["quote_no"] in my_qnos]
    open_cnt = len([i for i in my_inc if i["status"] != "처리완료"])
    c1, c2 = st.columns(2)
    c1.metric("내 담당 사고", f"{len(my_inc)}건")
    c2.metric("처리중", f"{open_cnt}건")

    if my_inc:
        st.subheader("사고/AS 현황")
        st.dataframe([{
            "유형": i["issue_type"],
            "현장": db.get_site(i["quote_no"])["address"].split("(")[0].strip(),
            "창": i["window_location"],
            "사유": i["fault_provisional"],
            "확정": i["fault_confirmed"] or "검토중",
            "상태": i["status"],
            "예정": i.get("vendor_schedule", ""),
            "접수": i["created_at"],
        } for i in my_inc], width='stretch', hide_index=True)
    else:
        st.info("담당 현장에 사고가 없습니다.")
