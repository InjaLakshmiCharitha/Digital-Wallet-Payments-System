from io import BytesIO
import qrcode

from fastapi import HTTPException
from app.models import Merchant


def generate_merchant_qr(db, user_id):
    merchant = (
        db.query(Merchant)
        .filter(
            Merchant.user_id == user_id,
            Merchant.is_approved.is_(True)
        )
        .first()
    )

    if not merchant:
        raise HTTPException(
            status_code=404,
            detail="Approved merchant account not found"
        )

    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=4
    )

    qr.add_data(merchant.merchant_code)
    qr.make(fit=True)

    image = qr.make_image(
        fill_color="black",
        back_color="white"
    )

    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")
    image_buffer.seek(0)

    return image_buffer, merchant.merchant_code
