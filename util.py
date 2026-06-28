"""한국시간(KST, Asia/Seoul) 헬퍼.
서버(Streamlit Cloud 등)가 UTC로 돌아도 시각은 항상 한국시간으로 저장/표시한다.
"""
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    _KST = ZoneInfo("Asia/Seoul")
except Exception:  # 아주 구버전 파이썬 대비
    from datetime import timezone, timedelta
    _KST = timezone(timedelta(hours=9))


def now_kst():
    """타임존 정보를 뗀 한국시간 datetime (naive, 문자열 비교/파싱과 호환)."""
    return datetime.now(_KST).replace(tzinfo=None)


def now_kst_str():
    """'YYYY-MM-DD HH:MM:SS' 한국시간 문자열."""
    return now_kst().strftime("%Y-%m-%d %H:%M:%S")
