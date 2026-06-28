"""
구글시트 백엔드 연결 테스트.

실행:  streamlit run test_gsheet.py

본 앱(app.py)을 켜기 전에 이걸로 먼저 '연결·공유·읽기/쓰기'가 되는지 확인하세요.
버튼을 누르면 시트에 시드(현장/창호/사고)를 만들고 건수를 보여줍니다.
시트에 sites·windows·incidents 탭이 생기면 성공입니다.
"""
import streamlit as st

import sheets_db

st.title("📗 구글시트 백엔드 연결 테스트")

try:
    ok = ("gcp_service_account" in st.secrets) and ("sheet_key" in st.secrets)
except Exception:
    ok = False

st.write("**Secrets 설정:**", "✅ 됨" if ok else "❌ 안 됨 (구글시트_연동가이드.md 참고)")

if not ok:
    st.stop()

if st.button("연결 확인 + 시드 생성", type="primary"):
    try:
        sheets_db.seed_if_empty()
        ns = len(sheets_db.all_sites())
        ni = len(sheets_db.all_incidents())
        st.success(f"성공! 구글시트에 현장 {ns}건, 사고 {ni}건이 들어갔습니다. "
                   "시트의 sites·windows·incidents 탭을 확인하세요.")
    except Exception as e:
        st.error(f"실패: {e}")
        st.caption("→ 서비스 계정 '편집자' 공유, sheet_key, Sheets/Drive API 사용 설정을 확인하세요.")
