from datetime import datetime
from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    BackgroundTasks,
    Query
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import require_roles
from app.models import Transaction, User
from app.schemas.fraud import FraudDecisionRequest
from app.services.fraud_service import decide_flagged_transaction
from app.services.email_service import send_fraud_notification
from app.services.notification_service import create_notification
from app.utils.websocket_manager import manager


router = APIRouter(
    prefix="/admin",
    tags=["Fraud Detection"]
)


@router.get("/flagged-transactions")
def get_flagged_transactions(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    transaction_type: str | None = Query(None, alias="type"),
    status: str | None = Query(None),
    min_amount: Decimal | None = Query(None, ge=0),
    max_amount: Decimal | None = Query(None, ge=0),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    sort_by: str = Query("date", pattern="^(date|amount)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("Admin"))
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

    query = db.query(Transaction).filter(
        Transaction.is_flagged.is_(True)
    )

    if status:
        query = query.filter(
            Transaction.status == status
        )
    else:
        query = query.filter(
            Transaction.status == "On Hold"
        )

    if transaction_type:
        query = query.filter(
            Transaction.type == transaction_type
        )

    if min_amount is not None:
        query = query.filter(
            Transaction.amount >= min_amount
        )

    if max_amount is not None:
        query = query.filter(
            Transaction.amount <= max_amount
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
        sort_column = Transaction.amount
    else:
        sort_column = Transaction.created_at

    if order == "asc":
        query = query.order_by(
            sort_column.asc(),
            Transaction.id.asc()
        )
    else:
        query = query.order_by(
            sort_column.desc(),
            Transaction.id.desc()
        )

    transactions = query.offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "transactions": transactions
    }


def process_admin_decision(
    transaction_ref: str,
    request: FraudDecisionRequest,
    decision: str,
    current_user,
    db: Session,
    background_tasks: BackgroundTasks
):
    transaction = (
        db.query(Transaction)
        .filter(
            Transaction.transaction_ref == transaction_ref,
            Transaction.type == "Transfer",
            Transaction.status == "On Hold"
        )
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Flagged transaction not found or already reviewed"
        )

    sender = (
        db.query(User)
        .filter(User.id == transaction.initiated_by)
        .first()
    )

    if not sender:
        raise HTTPException(
            status_code=404,
            detail="Transaction sender not found"
        )

    result = decide_flagged_transaction(
        db=db,
        transaction_ref=transaction_ref,
        admin_id=current_user.id,
        decision=decision,
        reason=request.reason
    )

    message = (
        f"Your transfer of ₹{transaction.amount} "
        f"has been {decision.lower()}. "
        f"Transaction Reference: {transaction_ref}. "
        f"Reason: {request.reason or 'Not provided'}"
    )

    create_notification(
        db=db,
        user_id=sender.id,
        notification_type=f"Transfer {decision}",
        message=message
    )

    db.commit()

    manager.send_from_background(
        sender.id,
        {
            "type": f"transfer_{decision.lower()}",
            "message": message,
            "amount": str(transaction.amount),
            "transaction_ref": transaction_ref,
            "decision": decision
        }
    )

    if sender.email:
        background_tasks.add_task(
            send_fraud_notification,
            sender.email,
            sender.full_name,
            transaction_ref,
            str(transaction.amount),
            decision,
            request.reason
        )

    return result


@router.put("/transactions/{transaction_ref}/approve")
def approve_flagged_transaction(
    transaction_ref: str,
    request: FraudDecisionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("Admin"))
):
    return process_admin_decision(
        transaction_ref=transaction_ref,
        request=request,
        decision="Approved",
        current_user=current_user,
        db=db,
        background_tasks=background_tasks
    )


@router.put("/transactions/{transaction_ref}/reject")
def reject_flagged_transaction(
    transaction_ref: str,
    request: FraudDecisionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("Admin"))
):
    return process_admin_decision(
        transaction_ref=transaction_ref,
        request=request,
        decision="Rejected",
        current_user=current_user,
        db=db,
        background_tasks=background_tasks
    )




