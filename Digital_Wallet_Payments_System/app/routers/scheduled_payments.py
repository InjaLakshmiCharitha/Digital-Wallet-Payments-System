from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models import User
from app.schemas.scheduled_payment import (
    ScheduledPaymentCreate,
    ScheduledPaymentResponse
)
from app.services.scheduled_payment_service import (
    create_scheduled_payment,
    list_scheduled_payments,
    cancel_scheduled_payment
)


router = APIRouter(
    prefix="/scheduled-payments",
    tags=["Scheduled Payments"]
)


@router.post("/", response_model=ScheduledPaymentResponse, status_code=201)
def create_schedule(
    data: ScheduledPaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return create_scheduled_payment(
        db=db,
        user_id=current_user.id,
        recipient_phone=data.recipient_phone,
        amount=data.amount,
        note=data.note,
        frequency=data.frequency,
        next_run_at=data.next_run_at,
        pin=data.pin
    )


@router.get("/")
def get_scheduled_payments(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    active_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return list_scheduled_payments(
        db=db,
        user_id=current_user.id,
        skip=skip,
        limit=limit,
        active_only=active_only
    )


@router.delete("/{payment_id}")
def cancel_schedule(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return cancel_scheduled_payment(
        db=db,
        user_id=current_user.id,
        payment_id=payment_id
    )