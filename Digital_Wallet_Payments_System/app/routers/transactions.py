from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models import User
from app.services.transaction_service import (
    get_transaction_history,
    get_transaction_detail
)


router = APIRouter(
    prefix="/transactions",
    tags=["Transaction History"]
)


@router.get("")
def transaction_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    transaction_type: str | None = Query(None),
    status: str | None = Query(None),
    min_amount: Decimal | None = Query(None, ge=0),
    max_amount: Decimal | None = Query(None, ge=0),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    sort_by: str = Query("date", pattern="^(date|amount)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role == "Admin":
        return {
            "message": "Use the admin transaction report endpoint to view all transactions"
        }

    return get_transaction_history(
        db=db,
        current_user=current_user,
        skip=skip,
        limit=limit,
        transaction_type=transaction_type,
        status=status,
        min_amount=min_amount,
        max_amount=max_amount,
        from_date=from_date,
        to_date=to_date,
        sort_by=sort_by,
        order=order
    )


@router.get("/{transaction_ref}")
def transaction_details(
    transaction_ref: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return get_transaction_detail(
        db,
        current_user,
        transaction_ref
    )

