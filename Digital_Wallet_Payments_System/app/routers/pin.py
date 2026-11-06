from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.auth.dependencies import require_roles
from app.auth.security import hash_password, verify_password
from app.schemas.pin import (
    PINRequest,
    PINChangeRequest,
    PINResetRequest,
    OTPRequest,
    OTPVerifyRequest
)
from app.services.otp_service import create_otp, verify_otp
from app.services.email_service import send_otp_email


router = APIRouter(tags=["PIN and OTP"])


def validate_pin(pin: str):
    weak_pins = {
        "0000", "1111", "2222", "3333", "4444",
        "5555", "6666", "7777", "8888", "9999",
        "1234", "4321", "0123", "3210"
    }

    if pin in weak_pins:
        raise HTTPException(
            status_code=422,
            detail="Choose a stronger transaction PIN"
        )


def check_pin_lock(user: User):
    now = datetime.utcnow()

    if user.pin_locked_until and user.pin_locked_until > now:
        raise HTTPException(
            status_code=423,
            detail="Payments are locked for 30 minutes"
        )

    if user.pin_locked_until and user.pin_locked_until <= now:
        user.pin_locked_until = None
        user.pin_failed_attempts = 0


def verify_transaction_pin(db: Session, user: User, pin: str):
    try:
        check_pin_lock(user)

        if not user.transaction_pin_hash:
            raise HTTPException(
                status_code=400,
                detail="Please set your transaction PIN first"
            )

        if not verify_password(pin, user.transaction_pin_hash):
            user.pin_failed_attempts += 1

            if user.pin_failed_attempts >= 3:
                user.pin_locked_until = (
                    datetime.utcnow() + timedelta(minutes=30)
                )

                db.commit()

                raise HTTPException(
                    status_code=423,
                    detail="Payments locked for 30 minutes"
                )

            remaining_attempts = 3 - user.pin_failed_attempts

            db.commit()

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Incorrect PIN. "
                    f"{remaining_attempts} attempts remaining"
                )
            )

        user.pin_failed_attempts = 0
        user.pin_locked_until = None

        db.commit()

        return True

    except HTTPException:
        raise

    except Exception:
        db.rollback()
        raise


@router.post("/wallet/pin")
def set_pin(
    data: PINRequest,
    current_user: User = Depends(require_roles("User", "Merchant")),
    db: Session = Depends(get_db)
):
    if current_user.transaction_pin_hash:
        raise HTTPException(
            status_code=409,
            detail="PIN already exists. Use the change or reset PIN API."
        )

    validate_pin(data.pin)

    current_user.transaction_pin_hash = hash_password(data.pin)
    current_user.pin_failed_attempts = 0
    current_user.pin_locked_until = None

    db.commit()

    return {
        "message": "Transaction PIN set successfully"
    }


@router.put("/wallet/pin/change")
def change_pin(
    data: PINChangeRequest,
    current_user: User = Depends(require_roles("User", "Merchant")),
    db: Session = Depends(get_db)
):
    check_pin_lock(current_user)

    verify_transaction_pin(
        db,
        current_user,
        data.current_pin
    )

    validate_pin(data.new_pin)

    if verify_password(
        data.new_pin,
        current_user.transaction_pin_hash
    ):
        raise HTTPException(
            status_code=422,
            detail="New PIN must be different from the current PIN"
        )

    current_user.transaction_pin_hash = hash_password(data.new_pin)
    current_user.pin_failed_attempts = 0
    current_user.pin_locked_until = None

    db.commit()

    return {
        "message": "Transaction PIN changed successfully"
    }


@router.post("/wallet/pin/reset")
def reset_pin(
    data: PINResetRequest,
    current_user: User = Depends(require_roles("User", "Merchant")),
    db: Session = Depends(get_db)
):
    validate_pin(data.new_pin)

    verify_otp(
        db,
        current_user.id,
        "PIN Reset",
        data.otp
    )

    current_user.transaction_pin_hash = hash_password(data.new_pin)
    current_user.pin_failed_attempts = 0
    current_user.pin_locked_until = None

    db.commit()

    return {
        "message": "Transaction PIN reset successfully"
    }


@router.post("/otp/send")
def send_otp(
    data: OTPRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_roles("User", "Merchant")),
    db: Session = Depends(get_db)
):
    otp_value = create_otp(
        db,
        current_user.id,
        data.purpose
    )

    background_tasks.add_task(
        send_otp_email,
        current_user.email,
        otp_value,
        data.purpose
    )

    return {
        "message": "OTP sent to your registered email address"
    }


@router.post("/otp/verify")
def check_otp(
    data: OTPVerifyRequest,
    current_user: User = Depends(require_roles("User", "Merchant")),
    db: Session = Depends(get_db)
):
    verify_otp(
        db,
        current_user.id,
        data.purpose,
        data.otp
    )

    return {
        "message": "OTP verified successfully"
    }
