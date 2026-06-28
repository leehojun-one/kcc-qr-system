"""
알림 모듈 (당일사고 / 입주전AS)

데모 단계에서는 실제 발송 대신 DB에 '발송 로그'를 남기는 시뮬레이션으로 동작한다.
본사 IT가 솔라피/알리고 등 카카오 알림톡 딜러사 API 키를 넣으면
_send_via_provider() 한 곳만 채워서 실제 발송으로 전환할 수 있게 분리해 둔다.

유형별 라우팅
- 당일사고 : 설치 당일, 시공팀 신고. 99% 가공처 액션 필요 → [가공처담당, 관제센터] 동시(긴급).
- 입주전AS : 공사중·입주전, 대리점/현장 신고. 귀책 불명확/덜 긴급
             → [관제센터, 영업자] 만 수신. 가공처는 관제가 검토 후 '지시'로 발송.

멈춤 조건: 가공처(또는 관제)가 웹뷰 '접수확인' 클릭 (status -> '가공처확인').
미확인 시 1분 도배 금지 — 유형별 에스컬레이션 사다리로 대상 확대.
"""
from datetime import datetime

from util import now_kst, now_kst_str

# 유형별 1차 수신자
T0_TARGETS = {
    "당일사고": ["가공처담당", "관제센터"],
    "입주전AS": ["관제센터", "영업자"],
}

# 유형별 에스컬레이션 사다리 (분, 대상, 채널). 당일사고는 공격적, 입주전AS는 완만.
ESCALATION = {
    "당일사고": [
        (0,  ["가공처담당", "관제센터"],              "알림톡+SMS"),
        (10, ["가공처담당", "가공처관리자", "관제센터"], "알림톡+SMS 재발송"),
        (30, ["가공처관리자", "관제센터(직접전화)"],     "관제센터 직접 전화/ARS"),
    ],
    "입주전AS": [
        (0,   ["관제센터", "영업자"],            "알림톡+SMS"),
        (30,  ["관제센터", "영업자"],            "알림톡 재발송"),
        (120, ["관제센터(직접전화)", "영업자"],   "관제센터 직접 전화"),
    ],
}


def build_message(site, incident, issue_type):
    addr = site["address"].split("(")[0].strip()
    head = "[당일현장사고]" if issue_type == "당일사고" else "[입주전 AS]"
    reporter = incident.get("reporter", "")
    rep_line = f"신고: {reporter}\n" if reporter else ""
    return (
        f"{head} {addr}\n"
        f"창: {incident['window_location']} / 사유(1차): {incident['fault_provisional']}\n"
        f"{rep_line}"
        f"시공팀: {site['constructor']} · 영업: {site['sales_rep']}\n"
        f"▶ 접수확인/처리: 웹뷰 링크"
    )


def escalation_stage(created_at, confirmed, issue_type="당일사고", now=None):
    if confirmed:
        return {"level": -1, "targets": [], "channel": "확인됨(중단)", "minutes": 0}
    now = now or now_kst()
    elapsed = (now - created_at).total_seconds() / 60.0
    ladder = ESCALATION.get(issue_type, ESCALATION["당일사고"])
    stage = ladder[0]
    for mins, targets, channel in ladder:
        if elapsed >= mins:
            stage = (mins, targets, channel)
    return {"level": stage[0], "targets": stage[1], "channel": stage[2], "minutes": round(elapsed)}


def _send_via_provider(to_phone, text, channel):
    """실제 발송 자리(본사 IT 연동). 예) 솔라피 알림톡 + 실패 시 SMS 대체발송."""
    raise NotImplementedError("배포 시 딜러사 API 연결")


def dispatch(site, incident, issue_type="당일사고", simulate=True):
    """사고/AS 1차 알림. 유형별 수신자에게 발송. simulate=True면 로그만 반환."""
    text = build_message(site, incident, issue_type)
    targets = T0_TARGETS.get(issue_type, T0_TARGETS["당일사고"])
    logs = []
    for t in targets:
        if not simulate:
            _send_via_provider("", text, "알림톡")
        logs.append({
            "incident_id": incident.get("id"),
            "target": t,
            "channel": "알림톡+SMS",
            "content": text,
            "sent_at": now_kst_str(),
        })
    return logs


def instruct_vendor(site, incident, simulate=True):
    """관제센터 → 가공처 '지시' 발송 (입주전AS에서 관제 검토 후 가공처 액션 필요 시)."""
    fault = incident.get("fault_confirmed") or incident["fault_provisional"]
    text = (f"[관제 지시] {site['address'].split('(')[0].strip()}\n"
            f"창: {incident['window_location']} / 확정사유: {fault}\n"
            f"▶ 처리예정일 입력/완료사진 등록: 웹뷰 링크")
    if not simulate:
        _send_via_provider("", text, "알림톡")
    return {
        "incident_id": incident.get("id"),
        "target": f"가공처({site['vendor']})",
        "channel": "알림톡+SMS(관제지시)",
        "content": text,
        "sent_at": now_kst_str(),
    }
