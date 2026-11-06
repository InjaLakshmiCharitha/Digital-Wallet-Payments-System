from datetime import datetime

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import get_current_user, require_roles
from app.models import User
from app.services.report_service import (
    get_admin_dashboard,
    get_ledger_summary,
    get_merchant_sales,
    get_my_spending
)


router = APIRouter(
    prefix="/reports",
    tags=["Reports & Analytics"]
)


@router.get("/admin-dashboard")
def admin_dashboard(
    current_user: User = Depends(require_roles("Admin")),
    db: Session = Depends(get_db)
):
    return get_admin_dashboard(db)


@router.get("/ledger-summary")
def ledger_summary(
    current_user: User = Depends(require_roles("Admin")),
    db: Session = Depends(get_db)
):
    return get_ledger_summary(db)


@router.get("/merchant-sales")
def merchant_sales(
    current_user: User = Depends(require_roles("Admin")),
    db: Session = Depends(get_db)
):
    return get_merchant_sales(db)


@router.get("/my-spending")
def my_spending(
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=422,
            detail="From date cannot be later than to date"
        )

    if current_user.role not in ["User", "Merchant"]:
        raise HTTPException(
            status_code=403,
            detail="This report is available only to wallet users and merchants"
        )

    return get_my_spending(
        db=db,
        user_id=current_user.id,
        from_date=from_date,
        to_date=to_date
    )
