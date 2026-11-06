from datetime import datetime, timedelta
from secrets import randbelow
import logging
import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import OTP
from app.auth.security import hash_password, verify_password


logger = logging.getLogger(__name__)


def generate_otp():
    return str(randbelow(900000) + 100000)


def create_otp(db: Session, user_id: int, purpose: str):
    if user_id <= 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid user ID"
        )

    if not purpose or not purpose.strip():
        raise HTTPException(
            status_code=422,
            detail="OTP purpose is required"
        )

    purpose = purpose.strip()

    try:
        now = datetime.utcnow()

        latest_otp = db.query(OTP).filter(
            OTP.user_id == user_id,
            OTP.purpose == purpose
        ).order_by(
            OTP.created_at.desc()
        ).first()

        if latest_otp:
            elapsed = now - latest_otp.created_at

            if elapsed.total_seconds() < 60:
                raise HTTPException(
                    status_code=429,
                    detail="Please wait 60 seconds before requesting another OTP"
                )

        otp_value = generate_otp()

        db.query(OTP).filter(
            OTP.user_id == user_id,
            OTP.purpose == purpose,
            OTP.is_used.is_(False)
        ).update(
            {"is_used": True},
            synchronize_session=False
        )

        otp_record = OTP(
            user_id=user_id,
            purpose=purpose,
            otp_hash=hash_password(otp_value),
            expires_at=now + timedelta(minutes=5),
            attempts=0,
            is_used=False
        )

        db.add(otp_record)
        db.commit()
        db.refresh(otp_record)

        return otp_value

    except HTTPException:
        raise

    except Exception:
        db.rollback()
        logger.exception("OTP creation failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to generate OTP"
        )


def verify_otp(
    db: Session,
    user_id: int,
    purpose: str,
    otp_value: str
):
    if user_id <= 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid user ID"
        )

    if not purpose or not purpose.strip():
        raise HTTPException(
            status_code=422,
            detail="OTP purpose is required"
        )

    if not otp_value or not re.fullmatch(r"[0-9]{6}", otp_value):
        raise HTTPException(
            status_code=422,
            detail="OTP must contain exactly six digits"
        )

    try:
        otp_record = db.query(OTP).filter(
            OTP.user_id == user_id,
            OTP.purpose == purpose.strip(),
            OTP.is_used.is_(False)
        ).order_by(
            OTP.created_at.desc()
        ).with_for_update().first()

        if not otp_record:
            raise HTTPException(
                status_code=400,
                detail="OTP not found or already used for this purpose"
            )

        now = datetime.utcnow()

        if otp_record.expires_at <= now:
            otp_record.is_used = True
            db.commit()

            raise HTTPException(
                status_code=400,
                detail="OTP has expired"
            )

        if otp_record.attempts >= 3:
            otp_record.is_used = True
            db.commit()

            raise HTTPException(
                status_code=429,
                detail="Maximum OTP attempts exceeded"
            )

        if not verify_password(otp_value, otp_record.otp_hash):
            otp_record.attempts += 1

            if otp_record.attempts >= 3:
                otp_record.is_used = True

            db.commit()

            if otp_record.attempts >= 3:
                raise HTTPException(
                    status_code=429,
                    detail="Maximum OTP attempts exceeded"
                )

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid OTP. "
                    f"{3 - otp_record.attempts} attempts remaining"
                )
            )

        otp_record.is_used = True
        db.commit()

        return True

    except HTTPException:
        raise

    except Exception:
        db.rollback()
        logger.exception("OTP verification failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to verify OTP"
        )


