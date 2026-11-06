from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models import User, BillPayment
from app.schemas.bill_payment import BillPaymentCreate
from app.services.bill_payment_service import execute_bill_payment


router = APIRouter(
    prefix="/bills",
    tags=["Mock Bill Payments"]
)


@router.post("/pay", status_code=status.HTTP_200_OK)
def pay_bill(
    data: BillPaymentCreate,
    response: Response,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=8,
        max_length=128
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result, replayed = execute_bill_payment(
        db=db,
        user_id=current_user.id,
        bill_type=data.bill_type,
        provider_name=data.provider_name,
        consumer_number=data.consumer_number,
        amount=data.amount,
        pin=data.pin,
        idempotency_key=idempotency_key
    )

    if replayed:
        response.headers["Idempotent-Replayed"] = "true"

    return result


@router.get("/history")
def get_bill_payment_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    bill_type: str | None = Query(None),
    payment_status: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(BillPayment).filter(
        BillPayment.user_id == current_user.id
    )

    if bill_type:
        query = query.filter(
            BillPayment.bill_type == bill_type
        )

    if payment_status:
        query = query.filter(
            BillPayment.status == payment_status
        )

    total = query.count()

    payments = (
        query.order_by(
            BillPayment.created_at.desc(),
            BillPayment.id.desc()
        )
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "bill_payments": payments
    }
