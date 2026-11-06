from datetime import datetime
from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    Header,
    Response,
    HTTPException,
    BackgroundTasks,
    Query
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import get_current_user, require_roles
from app.models import (
    User,
    Merchant,
    MerchantPayment,
    Transaction
)
from app.schemas.merchant import (
    MerchantPaymentRequest,
    RefundRequest
)
from app.services.merchant_qr_service import generate_merchant_qr
from app.services.merchant_payment_service import execute_merchant_payment
from app.services.refund_service import execute_merchant_refund
from app.utils.notification_utils import queue_wallet_email
from app.services.email_service import send_email
from app.utils.websocket_manager import manager


router = APIRouter(tags=["Merchant Payments"])


@router.get("/merchants/me/qr")
def get_my_merchant_qr(
    current_user: User = Depends(require_roles("Merchant")),
    db: Session = Depends(get_db)
):
    image_buffer, merchant_code = generate_merchant_qr(
        db,
        current_user.id
    )

    return StreamingResponse(
        image_buffer,
        media_type="image/png",
        headers={
            "Content-Disposition": "inline; filename=merchant_qr.png",
            "X-Merchant-Code": merchant_code
        }
    )


@router.post("/payments/merchant")
async def pay_merchant(
    request: MerchantPaymentRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key"
    ),
    current_user: User = Depends(require_roles("User")),
    db: Session = Depends(get_db)
):
    result, replayed = execute_merchant_payment(
        db=db,
        customer_id=current_user.id,
        merchant_code=request.merchant_code,
        amount=request.amount,
        pin=request.pin,
        idempotency_key=idempotency_key
    )

    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
        return result

    merchant = db.query(Merchant).filter(
        Merchant.merchant_code == request.merchant_code
    ).first()

    queue_wallet_email(
        background_tasks,
        current_user.email,
        current_user.full_name,
        "Merchant Payment",
        result["amount"],
        result["transaction_ref"],
        result["merchant_name"]
    )

    if merchant:
        merchant_user = db.query(User).filter(
            User.id == merchant.user_id
        ).first()

        if merchant_user and merchant_user.email:
            background_tasks.add_task(
                send_email,
                merchant_user.email,
                "Digital Wallet - Merchant Payment Received",
                (
                    f"Hello {merchant_user.full_name},\n\n"
                    f"You received a merchant payment of "
                    f"₹{result['merchant_received']}.\n\n"
                    f"Transaction Reference: {result['transaction_ref']}"
                )
            )

        if merchant_user:
            await manager.send_personal_message(
                merchant_user.id,
                {
                    "type": "merchant_payment_received",
                    "message": "You received a merchant payment.",
                    "amount": str(result["merchant_received"]),
                    "transaction_ref": result["transaction_ref"]
                }
            )

    await manager.send_personal_message(
        current_user.id,
        {
            "type": "merchant_payment_sent",
            "message": "Merchant payment completed successfully.",
            "amount": str(result["amount"]),
            "merchant_name": result["merchant_name"],
            "transaction_ref": result["transaction_ref"]
        }
    )

    return result


@router.post("/payments/{transaction_ref}/refund")
async def refund_merchant_payment(
    transaction_ref: str,
    request: RefundRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key"
    ),
    current_user: User = Depends(require_roles("Merchant")),
    db: Session = Depends(get_db)
):
    result, replayed = execute_merchant_refund(
        db=db,
        merchant_user_id=current_user.id,
        transaction_ref=transaction_ref,
        amount=request.amount,
        pin=request.pin,
        idempotency_key=idempotency_key,
        reason=request.reason
    )

    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
        return result

    customer = db.query(User).filter(
        User.id == result["customer_id"]
    ).first()

    if customer and customer.email:
        queue_wallet_email(
            background_tasks,
            customer.email,
            customer.full_name,
            "Merchant Refund",
            result["refund_amount"],
            result["refund_transaction_ref"]
        )

    if current_user.email:
        background_tasks.add_task(
            send_email,
            current_user.email,
            "Digital Wallet - Refund Processed",
            (
                f"Hello {current_user.full_name},\n\n"
                f"Your refund of ₹{result['refund_amount']} "
                "has been processed successfully.\n\n"
                f"Original Transaction: {transaction_ref}\n"
                f"Refund Transaction: {result['refund_transaction_ref']}"
            )
        )

    if customer:
        await manager.send_personal_message(
            customer.id,
            {
                "type": "merchant_refund_received",
                "message": "Your merchant refund has been processed.",
                "refund_amount": str(result["refund_amount"]),
                "refund_transaction_ref": result["refund_transaction_ref"]
            }
        )

    await manager.send_personal_message(
        current_user.id,
        {
            "type": "merchant_refund_processed",
            "message": "Your merchant refund has been processed successfully.",
            "refund_amount": str(result["refund_amount"]),
            "refund_transaction_ref": result["refund_transaction_ref"]
        }
    )

    return result


@router.get("/merchants/me/payments")
def get_my_merchant_payments(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    min_amount: Decimal | None = Query(None, ge=0),
    max_amount: Decimal | None = Query(None, ge=0),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    sort_by: str = Query("date", pattern="^(date|amount)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    current_user: User = Depends(require_roles("Merchant")),
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

    merchant = db.query(Merchant).filter(
        Merchant.user_id == current_user.id
    ).first()

    if not merchant:
        raise HTTPException(
            status_code=404,
            detail="Merchant account not found"
        )

    query = (
        db.query(MerchantPayment)
        .join(
            Transaction,
            Transaction.id == MerchantPayment.transaction_id
        )
        .filter(
            MerchantPayment.merchant_id == merchant.id
        )
    )

    if status:
        query = query.filter(
            Transaction.status == status
        )

    if min_amount is not None:
        query = query.filter(
            MerchantPayment.amount >= min_amount
        )

    if max_amount is not None:
        query = query.filter(
            MerchantPayment.amount <= max_amount
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
        sort_column = MerchantPayment.amount
    else:
        sort_column = Transaction.created_at

    if order == "asc":
        query = query.order_by(
            sort_column.asc(),
            MerchantPayment.id.asc()
        )
    else:
        query = query.order_by(
            sort_column.desc(),
            MerchantPayment.id.desc()
        )

    payments = query.offset(skip).limit(limit).all()

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "payments": [
            {
                "transaction_ref": payment.transaction.transaction_ref,
                "customer_id": payment.customer_id,
                "amount": payment.amount,
                "platform_fee": payment.platform_fee,
                "net_amount": payment.net_amount,
                "status": payment.transaction.status,
                "created_at": payment.transaction.created_at
            }
            for payment in payments
        ]
    }

