from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    Header,
    Response,
    HTTPException,
    BackgroundTasks
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models import (
    User,
    Transaction,
    LedgerEntry,
    Account,
    Wallet
)
from app.schemas.transfer import TransferRequest
from app.services.transfer_service import execute_safe_transfer
from app.services.email_service import send_fraud_notification
from app.services.notification_service import create_notification
from app.utils.notification_utils import queue_wallet_email
from app.utils.websocket_manager import manager


router = APIRouter(tags=["Transfers"])


@router.post("/transfers")
async def transfer_money(
    request: TransferRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    result, replayed = execute_safe_transfer(
        db=db,
        sender_id=current_user.id,
        receiver_phone=request.receiver_phone,
        amount=request.amount,
        idempotency_key=idempotency_key,
        description=request.note or "Wallet transfer",
        pin=request.pin,
        otp=request.otp
    )

    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
        return result

    if result.get("status") == "On Hold":
        create_notification(
            db=db,
            user_id=current_user.id,
            notification_type="Transfer On Hold",
            message=(
                f"Your transfer of ₹{result['amount']} "
                f"is currently on hold for review. "
                f"Transaction Reference: {result['transaction_ref']}"
            )
        )

        db.commit()

        if current_user.email:
            background_tasks.add_task(
                send_fraud_notification,
                current_user.email,
                current_user.full_name,
                result["transaction_ref"],
                result["amount"],
                "On Hold"
            )

        await manager.send_personal_message(
            current_user.id,
            {
                "type": "transfer_on_hold",
                "message": "Your transfer is on hold for review.",
                "transaction_ref": result["transaction_ref"],
                "amount": str(result["amount"])
            }
        )

        return result

    receiver = db.query(User).filter(
        User.id == result["receiver_id"]
    ).first()

    if current_user.email:
        queue_wallet_email(
            background_tasks,
            current_user.email,
            current_user.full_name,
            "Money Sent",
            result["amount"],
            result["transaction_ref"]
        )

    if receiver and receiver.email:
        queue_wallet_email(
            background_tasks,
            receiver.email,
            receiver.full_name,
            "Money Received",
            result["amount"],
            result["transaction_ref"]
        )

    sender_balance = Decimal(str(result["sender_balance"]))

    if sender_balance < Decimal("100.00"):
        create_notification(
            db=db,
            user_id=current_user.id,
            notification_type="Low Balance Alert",
            message=(
                f"Your wallet balance is ₹{sender_balance}, "
                "which is below ₹100. Please add money to your wallet."
            )
        )

    db.commit()

    await manager.send_personal_message(
        current_user.id,
        {
            "type": "money_sent",
            "message": "Money transferred successfully.",
            "amount": str(result["amount"]),
            "transaction_ref": result["transaction_ref"],
            "wallet_balance": str(sender_balance)
        }
    )

    if receiver:
        await manager.send_personal_message(
            receiver.id,
            {
                "type": "money_received",
                "message": "Money received successfully.",
                "amount": str(result["amount"]),
                "transaction_ref": result["transaction_ref"]
            }
        )

    if sender_balance < Decimal("100.00"):
        await manager.send_personal_message(
            current_user.id,
            {
                "type": "low_balance",
                "message": "Your wallet balance is below ₹100.",
                "wallet_balance": str(sender_balance)
            }
        )

        if current_user.email:
            queue_wallet_email(
                background_tasks,
                current_user.email,
                current_user.full_name,
                "Low Balance Alert",
                str(sender_balance)
            )

    return result


@router.get("/transfers/{transaction_ref}")
def get_transfer(
    transaction_ref: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    transaction = (
        db.query(Transaction)
        .filter(
            Transaction.transaction_ref == transaction_ref,
            Transaction.type == "Transfer"
        )
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Transfer transaction not found"
        )

    if current_user.role != "Admin":
        user_entry = (
            db.query(LedgerEntry.id)
            .join(
                Account,
                Account.id == LedgerEntry.account_id
            )
            .join(
                Wallet,
                Wallet.id == Account.wallet_id
            )
            .filter(
                LedgerEntry.transaction_id == transaction.id,
                Wallet.owner_id == current_user.id
            )
            .first()
        )

        if not user_entry:
            raise HTTPException(
                status_code=403,
                detail="You are not authorized to view this transfer"
            )

    return {
        "transaction_ref": transaction.transaction_ref,
        "type": transaction.type,
        "amount": transaction.amount,
        "status": transaction.status,
        "description": transaction.description,
        "initiated_by": transaction.initiated_by,
        "is_flagged": transaction.is_flagged,
        "created_at": transaction.created_at
    }




