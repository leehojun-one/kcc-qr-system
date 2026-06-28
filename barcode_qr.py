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


def make_qr_sheet_pdf(serials, base_url="", cols=4, rows=6):
    """빈 고유번호 QR을 A4 격자로 깔아 인쇄용 PDF(bytes) 생성.
    base_url 이 있으면 QR이 base_url?qr=일련번호 를 담아 스캔 시 앱이 열림."""
    from PIL import Image, ImageDraw, ImageFont
    A4 = (1240, 1754)  # 150dpi 정도
    margin, per = 60, cols * rows
    cw = (A4[0] - margin * 2) // cols
    ch = (A4[1] - margin * 2) // rows
    qr_size = min(cw, ch) - 50
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 18)
    except Exception:
        font = ImageFont.load_default()

    pages = []
    for i in range(0, len(serials), per):
        page = Image.new("RGB", A4, "white")
        draw = ImageDraw.Draw(page)
        for j, serial in enumerate(serials[i:i + per]):
            r, c = divmod(j, cols)
            x = margin + c * cw + (cw - qr_size) // 2
            y = margin + r * ch + 10
            payload = f"{base_url}?qr={serial}" if base_url else serial
            qr_img = Image.open(io.BytesIO(make_qr_png(payload))).resize((qr_size, qr_size))
            page.paste(qr_img, (x, y))
            draw.text((margin + c * cw + cw // 2, y + qr_size + 8), serial,
                      fill="black", anchor="ma", font=font)
        pages.append(page)

    buf = io.BytesIO()
    if pages:
        pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
    return buf.getvalue()
