"""
바코드 / QR 생성기
- 시공발주서 '오더번호' 칸에 들어갈 바코드: 창호견적번호를 Code128로 인코딩
- 거실 메인창 보증스티커 QR: 고유 일련번호(serial)를 인코딩
둘 다 PNG bytes(또는 base64)로 반환 → Streamlit st.image 로 표시 가능.
"""
import base64
import io

import qrcode
import barcode
from barcode.writer import ImageWriter


def make_barcode_png(value: str) -> bytes:
    """창호견적번호 → Code128 바코드 PNG bytes."""
    code128 = barcode.get("code128", value, writer=ImageWriter())
    buf = io.BytesIO()
    code128.write(buf, options={"module_height": 8.0, "font_size": 8, "text_distance": 3.0})
    return buf.getvalue()


def make_qr_png(value: str) -> bytes:
    """QR 일련번호(또는 접속 URL) → QR PNG bytes."""
    qr = qrcode.QRCode(version=1, box_size=8, border=2,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(value)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def to_b64(png_bytes: bytes) -> str:
    return base64.b64encode(png_bytes).decode("ascii")
