from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import User, Wallet, ScheduledPayment
from app.routers.pin import verify_transaction_pin


def create_scheduled_payment(
    db: Session,
    user_id: int,
    recipient_phone: str,
    amount: Decimal,
    note: str | None,
    frequency: str,
    next_run_at: datetime,
    pin: str
):
    auth_db = SessionLocal()

    try:
        user = (
            auth_db.query(User)
            .filter(
                User.id == user_id,
                User.is_active.is_(True)
            )
            .first()
        )

        if not user:
            raise HTTPException(
                status_code=403,
                detail="User account not found or inactive"
            )

        verify_transaction_pin(
            auth_db,
            user,
            pin
        )

        sender_wallet = (
            db.query(Wallet)
            .filter(Wallet.owner_id == user_id)
            .first()
        )

        if not sender_wallet or sender_wallet.status != "Active":
            raise HTTPException(
                status_code=403,
                detail="Active wallet not found"
            )

        receiver = (
            db.query(User)
            .filter(
                User.phone == recipient_phone,
                User.is_active.is_(True)
            )
            .first()
        )

        if not receiver:
            raise HTTPException(
                status_code=404,
                detail="Recipient not found or inactive"
            )

        if receiver.id == user_id:
            raise HTTPException(
                status_code=400,
                detail="You cannot schedule a payment to yourself"
            )

        receiver_wallet = (
            db.query(Wallet)
            .filter(
                Wallet.owner_id == receiver.id,
                Wallet.status == "Active"
            )
            .first()
        )

        if not receiver_wallet:
            raise HTTPException(
                status_code=404,
                detail="Recipient does not have an active wallet"
            )

        if next_run_at <= datetime.utcnow():
            raise HTTPException(
                status_code=400,
                detail="Next payment date must be in the future"
            )

        scheduled_payment = ScheduledPayment(
            user_id=user_id,
            recipient_phone=recipient_phone,
            amount=amount,
            note=note,
            frequency=frequency,
            next_run_at=next_run_at,
            is_active=True
        )

        db.add(scheduled_payment)
        db.commit()
        db.refresh(scheduled_payment)

        return scheduled_payment

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to create scheduled payment"
        )

    finally:
        auth_db.close()


def list_scheduled_payments(
    db: Session,
    user_id: int,
    skip: int = 0,
    limit: int = 20,
    active_only: bool = False
):
    query = db.query(ScheduledPayment).filter(
        ScheduledPayment.user_id == user_id
    )

    if active_only:
        query = query.filter(
            ScheduledPayment.is_active.is_(True)
        )

    total = query.count()

    payments = (
        query.order_by(ScheduledPayment.next_run_at.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "scheduled_payments": payments
    }


def cancel_scheduled_payment(
    db: Session,
    user_id: int,
    payment_id: int
):
    payment = (
        db.query(ScheduledPayment)
        .filter(
            ScheduledPayment.id == payment_id,
            ScheduledPayment.user_id == user_id
        )
        .with_for_update()
        .first()
    )

    if not payment:
        raise HTTPException(
            status_code=404,
            detail="Scheduled payment not found"
        )

    if not payment.is_active:
        raise HTTPException(
            status_code=400,
            detail="Scheduled payment is already inactive"
        )

    payment.is_active = False

    db.commit()
    db.refresh(payment)

    return {
        "message": "Scheduled payment cancelled successfully",
        "payment_id": payment.id
    }