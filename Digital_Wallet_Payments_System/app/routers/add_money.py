from fastapi import (
    APIRouter,
    Depends,
    Header,
    Response,
    HTTPException
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models import User
from app.schemas.add_money import AddMoneyRequest
from app.schemas.razorpay import (
    RazorpayOrderCreate,
    RazorpayPaymentVerify
)
from app.services.add_money_service import execute_add_money
from app.services.razorpay_service import (
    create_razorpay_order,
    verify_razorpay_payment
)
from app.utils.websocket_manager import manager


router = APIRouter(
    prefix="/wallet",
    tags=["Add Money"]
)


@router.post("/add-money")
async def add_money(
    request: AddMoneyRequest,
    response: Response,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    result, replayed = execute_add_money(
        db,
        current_user.id,
        request.amount,
        request.source,
        request.simulate_status,
        idempotency_key
    )

    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
        return result

    if result.get("status") == "Success":
        await manager.send_personal_message(
            current_user.id,
            {
                "type": "money_added",
                "message": "Money added successfully",
                "amount": str(request.amount),
                "source": request.source,
                "wallet_balance": result.get("wallet_balance")
            }
        )

    return result


@router.post("/razorpay/create-order")
def create_razorpay_payment_order(
    request: RazorpayOrderCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return create_razorpay_order(
        db,
        current_user.id,
        request.amount
    )


@router.post("/razorpay/verify-payment")
async def verify_razorpay_payment_order(
    request: RazorpayPaymentVerify,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    result = verify_razorpay_payment(
        db=db,
        user_id=current_user.id,
        razorpay_order_id=request.razorpay_order_id,
        razorpay_payment_id=request.razorpay_payment_id,
        razorpay_signature=request.razorpay_signature,
        pin=request.pin
    )

    await manager.send_personal_message(
        current_user.id,
        {
            "type": "money_added",
            "message": result["message"],
            "amount": result["amount"],
            "wallet_balance": result["wallet_balance"],
            "transaction_ref": result["transaction_ref"]
        }
    )

    return result


