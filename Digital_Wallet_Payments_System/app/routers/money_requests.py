from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Response,
    BackgroundTasks
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models import User
from app.schemas.money_request import (
    MoneyRequestCreate,
    MoneyRequestPay
)
from app.services.money_request_service import (
    create_money_request,
    list_money_requests,
    pay_money_request,
    decline_money_request,
    cancel_money_request
)
from app.utils.notification_utils import queue_wallet_email
from app.utils.websocket_manager import manager


router = APIRouter(
    prefix="/money-requests",
    tags=["Money Requests"]
)


@router.post("")
def create_request(
    request: MoneyRequestCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    money_request = create_money_request(
        db=db,
        requester_id=current_user.id,
        payer_phone=request.payer_phone,
        amount=request.amount,
        note=request.note
    )

    payer = db.query(User).filter(
        User.id == money_request.payer_id
    ).first()

    if payer:
        manager.send_from_background(
            payer.id,
            {
                "type": "money_request_received",
                "message": (
                    f"{current_user.full_name} requested "
                    f"₹{money_request.amount} from you."
                ),
                "request_id": money_request.id,
                "amount": str(money_request.amount),
                "requester": current_user.full_name
            }
        )

        if payer.email:
            queue_wallet_email(
                background_tasks,
                payer.email,
                payer.full_name,
                "Money Request Received",
                str(money_request.amount),
                details=request.note or "A new money request was received."
            )

    return {
        "message": "Money request created successfully",
        "request": money_request
    }


@router.get("")
def get_requests(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(default=None),
    sort_by: str = Query("date", pattern="^(date|amount)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if status and status not in [
        "Pending", "Paid", "Declined", "Cancelled", "Expired"
    ]:
        raise HTTPException(
            status_code=422,
            detail="Invalid money request status"
        )

    return list_money_requests(
        db=db,
        user_id=current_user.id,
        status=status,
        skip=skip,
        limit=limit,
        sort_by=sort_by,
        order=order
    )


@router.put("/{request_id}/pay")
def pay_request(
    request_id: int,
    request: MoneyRequestPay,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    result, replayed = pay_money_request(
        db=db,
        request_id=request_id,
        payer_id=current_user.id,
        pin=request.pin,
        otp=request.otp,
        idempotency_key=idempotency_key
    )

    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    else:
        money_request = db.query(
            __import__("app.models", fromlist=["MoneyRequest"]).MoneyRequest
        ).filter(
            __import__("app.models", fromlist=["MoneyRequest"]).MoneyRequest.id == request_id
        ).first()

        if money_request:
            requester = db.query(User).filter(
                User.id == money_request.requester_id
            ).first()

            if requester:
                manager.send_from_background(
                    requester.id,
                    {
                        "type": "money_request_paid",
                        "message": (
                            f"{current_user.full_name} paid your "
                            f"money request of ₹{money_request.amount}."
                        ),
                        "request_id": money_request.id,
                        "amount": str(money_request.amount),
                        "payer": current_user.full_name
                    }
                )

    return result


@router.put("/{request_id}/decline")
def decline_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    result = decline_money_request(
        db=db,
        request_id=request_id,
        payer_id=current_user.id
    )

    money_request = db.query(
        __import__("app.models", fromlist=["MoneyRequest"]).MoneyRequest
    ).filter(
        __import__("app.models", fromlist=["MoneyRequest"]).MoneyRequest.id == request_id
    ).first()

    if money_request:
        requester = db.query(User).filter(
            User.id == money_request.requester_id
        ).first()

        if requester:
            manager.send_from_background(
                requester.id,
                {
                    "type": "money_request_declined",
                    "message": (
                        f"{current_user.full_name} declined your "
                        f"money request of ₹{money_request.amount}."
                    ),
                    "request_id": money_request.id,
                    "amount": str(money_request.amount)
                }
            )

    return result


@router.put("/{request_id}/cancel")
def cancel_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    result = cancel_money_request(
        db=db,
        request_id=request_id,
        requester_id=current_user.id
    )

    return result


