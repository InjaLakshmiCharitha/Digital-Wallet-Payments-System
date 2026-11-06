from datetime import datetime
from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Header,
    Response
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models import User, Withdrawal, Transaction
from app.schemas.bank import (
    BankAccountCreate,
    WithdrawalRequest
)
from app.services.bank_service import (
    add_bank_account,
    get_bank_accounts,
    delete_bank_account
)
from app.services.withdrawal_service import execute_withdrawal


router = APIRouter(tags=["Bank Accounts & Withdrawals"])


@router.post("/bank-accounts")
def create_bank_account(
    request: BankAccountCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return add_bank_account(
        db=db,
        user_id=current_user.id,
        account_holder_name=request.account_holder_name,
        account_number=request.account_number,
        ifsc_code=request.ifsc_code,
        bank_name=request.bank_name,
        otp=request.otp
    )


@router.get("/bank-accounts")
def list_bank_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return get_bank_accounts(
        db=db,
        user_id=current_user.id
    )


@router.delete("/bank-accounts/{bank_account_id}")
def remove_bank_account(
    bank_account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return delete_bank_account(
        db=db,
        user_id=current_user.id,
        bank_account_id=bank_account_id
    )


@router.post("/withdrawals")
def withdraw_money(
    request: WithdrawalRequest,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    result, replayed = execute_withdrawal(
        db=db,
        user_id=current_user.id,
        bank_account_id=request.bank_account_id,
        amount=request.amount,
        pin=request.pin,
        idempotency_key=idempotency_key
    )

    if replayed:
        response.headers["Idempotent-Replayed"] = "true"

    return result


@router.get("/withdrawals")
def list_withdrawals(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    transaction_type: str | None = Query(None, alias="type"),
    min_amount: Decimal | None = Query(None, ge=0),
    max_amount: Decimal | None = Query(None, ge=0),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    sort_by: str = Query("date", pattern="^(date|amount)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if min_amount is not None and max_amount is not None:
        if min_amount > max_amount:
            raise HTTPException(
                status_code=422,
                detail="Minimum amount cannot exceed maximum amount"
            )

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=422,
            detail="From date cannot be later than to date"
        )

    query = (
        db.query(Withdrawal)
        .join(Transaction)
        .filter(
            Transaction.initiated_by == current_user.id
        )
    )

    if status:
        query = query.filter(
            Withdrawal.status == status
        )

    if transaction_type:
        query = query.filter(
            Transaction.type == transaction_type
        )

    if min_amount is not None:
        query = query.filter(
            Withdrawal.amount >= min_amount
        )

    if max_amount is not None:
        query = query.filter(
            Withdrawal.amount <= max_amount
        )

    if from_date:
        query = query.filter(
            Transaction.created_at >= from_date
        )

    if to_date:
        query = query.filter(
            Transaction.created_at <= to_date
        )

    total = query.count()

    if sort_by == "amount":
        sort_column = Withdrawal.amount
    else:
        sort_column = Transaction.created_at

    if order == "asc":
        query = query.order_by(
            sort_column.asc(),
            Withdrawal.id.asc()
        )
    else:
        query = query.order_by(
            sort_column.desc(),
            Withdrawal.id.desc()
        )

    withdrawals = query.offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "withdrawals": withdrawals
    }
