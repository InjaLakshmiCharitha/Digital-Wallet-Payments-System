from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import User, Wallet, MoneyRequest
from app.services.transfer_service import execute_safe_transfer


def validate_request_amount(value):
    try:
        amount = Decimal(str(value))

    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="Invalid request amount"
        )

    if not amount.is_finite() or amount <= Decimal("0.00"):
        raise HTTPException(
            status_code=422,
            detail="Request amount must be greater than zero"
        )

    if amount != amount.quantize(Decimal("0.01")):
        raise HTTPException(
            status_code=422,
            detail="Request amount cannot have more than two decimal places"
        )

    return amount.quantize(Decimal("0.01"))


def create_money_request(
    db: Session,
    requester_id: int,
    payer_phone: str,
    amount: Decimal,
    note: str | None = None
):
    try:
        amount = validate_request_amount(amount)

        if not payer_phone or len(payer_phone) != 10 or not payer_phone.isdigit():
            raise HTTPException(
                status_code=422,
                detail="Payer phone number must contain exactly 10 digits"
            )

        requester = (
            db.query(User)
            .filter(User.id == requester_id)
            .first()
        )

        if not requester:
            raise HTTPException(
                status_code=404,
                detail="Requester not found"
            )

        if not requester.is_active:
            raise HTTPException(
                status_code=403,
                detail="Your account is inactive"
            )

        payer = (
            db.query(User)
            .filter(
                User.phone == payer_phone,
                User.is_active.is_(True)
            )
            .first()
        )

        if not payer:
            raise HTTPException(
                status_code=404,
                detail="Payer not found"
            )

        if payer.id == requester_id:
            raise HTTPException(
                status_code=400,
                detail="You cannot request money from yourself"
            )

        payer_wallet = (
            db.query(Wallet)
            .filter(Wallet.owner_id == payer.id)
            .first()
        )

        requester_wallet = (
            db.query(Wallet)
            .filter(Wallet.owner_id == requester_id)
            .first()
        )

        if not payer_wallet or not requester_wallet:
            raise HTTPException(
                status_code=404,
                detail="Required wallet not found"
            )

        if payer_wallet.status != "Active":
            raise HTTPException(
                status_code=403,
                detail="Payer wallet is not active"
            )

        if requester_wallet.status != "Active":
            raise HTTPException(
                status_code=403,
                detail="Requester wallet is not active"
            )

        pending_count = (
            db.query(func.count(MoneyRequest.id))
            .filter(
                MoneyRequest.requester_id == requester_id,
                MoneyRequest.payer_id == payer.id,
                MoneyRequest.status == "Pending",
                MoneyRequest.expires_at > datetime.utcnow()
            )
            .scalar()
        )

        if pending_count >= 5:
            raise HTTPException(
                status_code=400,
                detail="Maximum five pending requests to this person allowed"
            )

        if note is not None:
            note = note.strip() or None

            if note and len(note) > 250:
                raise HTTPException(
                    status_code=422,
                    detail="Note cannot exceed 250 characters"
                )

        now = datetime.utcnow()

        money_request = MoneyRequest(
            requester_id=requester_id,
            payer_id=payer.id,
            amount=amount,
            note=note,
            status="Pending",
            expires_at=now + timedelta(hours=48)
        )

        db.add(money_request)
        db.commit()
        db.refresh(money_request)

        return money_request

    except HTTPException:
        db.rollback()
        raise

    except (InvalidOperation, ValueError):
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail="Invalid request amount"
        )

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to create money request"
        )


def list_money_requests(
    db: Session,
    user_id: int,
    status: str | None = None,
    skip: int = 0,
    limit: int = 20,
    sort_by: str = "date",
    order: str = "desc"
):
    query = db.query(MoneyRequest).filter(
        (MoneyRequest.requester_id == user_id) |
        (MoneyRequest.payer_id == user_id)
    )

    if status:
        query = query.filter(
            MoneyRequest.status == status
        )

    total = query.count()

    if sort_by == "amount":
        sort_column = MoneyRequest.amount
    else:
        sort_column = MoneyRequest.created_at

    if order == "asc":
        query = query.order_by(
            sort_column.asc(),
            MoneyRequest.id.asc()
        )
    else:
        query = query.order_by(
            sort_column.desc(),
            MoneyRequest.id.desc()
        )

    money_requests = query.offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "money_requests": money_requests
    }


def pay_money_request(
    db: Session,
    request_id: int,
    payer_id: int,
    pin: str,
    otp: str | None,
    idempotency_key: str
):
    if request_id <= 0:
        raise HTTPException(
            status_code=422,
            detail="Invalid money request ID"
        )

    try:
        money_request = (
            db.query(MoneyRequest)
            .filter(MoneyRequest.id == request_id)
            .with_for_update()
            .first()
        )

        if not money_request:
            raise HTTPException(
                status_code=404,
                detail="Money request not found"
            )

        if money_request.payer_id != payer_id:
            raise HTTPException(
                status_code=403,
                detail="Only the requested payer can pay this request"
            )

        if money_request.status != "Pending":
            raise HTTPException(
                status_code=400,
                detail=f"Request is already {money_request.status}"
            )

        if money_request.expires_at <= datetime.utcnow():
            money_request.status = "Expired"
            db.commit()

            raise HTTPException(
                status_code=400,
                detail="Money request has expired"
            )

        requester = (
            db.query(User)
            .filter(User.id == money_request.requester_id)
            .first()
        )

        if not requester:
            raise HTTPException(
                status_code=404,
                detail="Requester not found"
            )

        if not requester.is_active:
            raise HTTPException(
                status_code=403,
                detail="Requester account is inactive"
            )

        amount = validate_request_amount(money_request.amount)

        result, replayed = execute_safe_transfer(
            db=db,
            sender_id=payer_id,
            receiver_phone=requester.phone,
            amount=amount,
            idempotency_key=idempotency_key,
            description=f"Payment for money request #{request_id}",
            pin=pin,
            otp=otp
        )

        money_request.status = "Paid"
        db.commit()

        result["money_request_id"] = request_id

        return result, replayed

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to process money request payment"
        )


def decline_money_request(
    db: Session,
    request_id: int,
    payer_id: int
):
    if request_id <= 0:
        raise HTTPException(
            status_code=422,
            detail="Invalid money request ID"
        )

    try:
        money_request = (
            db.query(MoneyRequest)
            .filter(MoneyRequest.id == request_id)
            .with_for_update()
            .first()
        )

        if not money_request:
            raise HTTPException(
                status_code=404,
                detail="Money request not found"
            )

        if money_request.payer_id != payer_id:
            raise HTTPException(
                status_code=403,
                detail="Only the payer can decline this request"
            )

        if money_request.status != "Pending":
            raise HTTPException(
                status_code=400,
                detail=f"Request is already {money_request.status}"
            )

        if money_request.expires_at <= datetime.utcnow():
            money_request.status = "Expired"
            db.commit()

            raise HTTPException(
                status_code=400,
                detail="Money request has expired"
            )

        money_request.status = "Declined"
        db.commit()

        return {
            "message": "Money request declined",
            "request_id": request_id
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to decline money request"
        )


def cancel_money_request(
    db: Session,
    request_id: int,
    requester_id: int
):
    if request_id <= 0:
        raise HTTPException(
            status_code=422,
            detail="Invalid money request ID"
        )

    try:
        money_request = (
            db.query(MoneyRequest)
            .filter(MoneyRequest.id == request_id)
            .with_for_update()
            .first()
        )

        if not money_request:
            raise HTTPException(
                status_code=404,
                detail="Money request not found"
            )

        if money_request.requester_id != requester_id:
            raise HTTPException(
                status_code=403,
                detail="Only the requester can cancel this request"
            )

        if money_request.status != "Pending":
            raise HTTPException(
                status_code=400,
                detail=f"Request is already {money_request.status}"
            )

        if money_request.expires_at <= datetime.utcnow():
            money_request.status = "Expired"
            db.commit()

            raise HTTPException(
                status_code=400,
                detail="Money request has expired"
            )

        money_request.status = "Cancelled"
        db.commit()

        return {
            "message": "Money request cancelled",
            "request_id": request_id
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to cancel money request"
        )
