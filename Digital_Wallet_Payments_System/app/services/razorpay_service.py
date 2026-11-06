import os
import uuid
from decimal import Decimal, InvalidOperation

import razorpay
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    User,
    Wallet,
    Account,
    Transaction,
    RazorpayPayment
)
from app.routers.pin import verify_transaction_pin
from app.services.ledger_service import (
    create_transaction_reference,
    record_transaction
)


RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")


def get_razorpay_client():
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Razorpay credentials are not configured"
        )

    return razorpay.Client(
        auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
    )


def validate_amount(amount):
    try:
        amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="Invalid payment amount"
        )

    if not amount.is_finite() or amount < Decimal("10"):
        raise HTTPException(
            status_code=422,
            detail="Minimum add money amount is ₹10"
        )

    if amount > Decimal("50000"):
        raise HTTPException(
            status_code=422,
            detail="Maximum add money amount is ₹50,000"
        )

    if amount != amount.quantize(Decimal("0.01")):
        raise HTTPException(
            status_code=422,
            detail="Amount can have a maximum of two decimal places"
        )

    return amount


def create_razorpay_order(
    db: Session,
    user_id: int,
    amount: Decimal
):
    amount = validate_amount(amount)

    user = db.query(User).filter(
        User.id == user_id,
        User.is_active.is_(True)
    ).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found or inactive"
        )

    wallet = db.query(Wallet).filter(
        Wallet.owner_id == user_id
    ).first()

    if not wallet or wallet.status != "Active":
        raise HTTPException(
            status_code=400,
            detail="Active wallet not found"
        )

    amount_in_paise = int(amount * 100)

    client = get_razorpay_client()

    receipt = f"wallet-{user_id}-{uuid.uuid4().hex[:20]}"

    try:
        order = client.order.create(
            data={
                "amount": amount_in_paise,
                "currency": "INR",
                "receipt": receipt
            }
        )
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Unable to create Razorpay order"
        )

    payment_record = RazorpayPayment(
        user_id=user_id,
        razorpay_order_id=order["id"],
        amount=amount,
        status="Created"
    )

    try:
        db.add(payment_record)
        db.commit()
        db.refresh(payment_record)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to save Razorpay order"
        )

    return {
        "razorpay_order_id": order["id"],
        "amount": amount,
        "currency": "INR",
        "status": payment_record.status,
        "key_id": RAZORPAY_KEY_ID
    }


def verify_razorpay_payment(
    db: Session,
    user_id: int,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
    pin: str
):
    client = get_razorpay_client()

    payment_record = db.query(RazorpayPayment).filter(
        RazorpayPayment.razorpay_order_id == razorpay_order_id,
        RazorpayPayment.user_id == user_id
    ).with_for_update().first()

    if not payment_record:
        raise HTTPException(
            status_code=404,
            detail="Razorpay order not found"
        )

    if payment_record.status == "Success":
        raise HTTPException(
            status_code=409,
            detail="This payment has already been credited"
        )

    if payment_record.status != "Created":
        raise HTTPException(
            status_code=400,
            detail="This Razorpay order cannot be verified"
        )

    existing_payment = db.query(RazorpayPayment).filter(
        RazorpayPayment.razorpay_payment_id == razorpay_payment_id
    ).first()

    if existing_payment:
        raise HTTPException(
            status_code=409,
            detail="This Razorpay payment has already been used"
        )

    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature
        })
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid Razorpay payment signature"
        )

    try:
        order_details = client.order.fetch(razorpay_order_id)
        payment_details = client.payment.fetch(razorpay_payment_id)
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Unable to verify payment with Razorpay"
        )

    expected_amount = int(payment_record.amount * 100)

    if (
        order_details.get("amount") != expected_amount
        or order_details.get("currency") != "INR"
        or payment_details.get("order_id") != razorpay_order_id
        or payment_details.get("amount") != expected_amount
        or payment_details.get("currency") != "INR"
    ):
        raise HTTPException(
            status_code=400,
            detail="Razorpay payment details do not match the order"
        )

    if payment_details.get("status") != "captured":
        raise HTTPException(
            status_code=400,
            detail="Razorpay payment has not been captured"
        )

    user = db.query(User).filter(
        User.id == user_id,
        User.is_active.is_(True)
    ).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found or inactive"
        )

    verify_transaction_pin(db, user, pin)

    try:
        wallet = db.query(Wallet).filter(
            Wallet.owner_id == user_id
        ).with_for_update().first()

        if not wallet or wallet.status != "Active":
            raise HTTPException(
                status_code=400,
                detail="Active wallet not found"
            )

        wallet_account = db.query(Account).filter(
            Account.wallet_id == wallet.id
        ).with_for_update().first()

        settlement_account = db.query(Account).filter(
            Account.account_code == "BANK-SETTLEMENT"
        ).with_for_update().first()

        if not wallet_account or not settlement_account:
            raise HTTPException(
                status_code=500,
                detail="Wallet or settlement account not found"
            )

        transaction = Transaction(
            transaction_ref=create_transaction_reference(),
            type="Add Money",
            amount=payment_record.amount,
            status="Success",
            initiated_by=user_id,
            description="Wallet added through Razorpay",
            is_flagged=False
        )

        db.add(transaction)
        db.flush()

        record_transaction(
            db,
            transaction,
            [
                {
                    "account_id": settlement_account.id,
                    "entry_type": "Debit",
                    "amount": payment_record.amount
                },
                {
                    "account_id": wallet_account.id,
                    "entry_type": "Credit",
                    "amount": payment_record.amount
                }
            ]
        )

        payment_record.razorpay_payment_id = razorpay_payment_id
        payment_record.transaction_id = transaction.id
        payment_record.status = "Success"

        db.commit()
        db.refresh(payment_record)
        db.refresh(wallet)

        return {
            "message": "Money added successfully through Razorpay",
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "transaction_ref": transaction.transaction_ref,
            "amount": str(payment_record.amount),
            "wallet_balance": str(wallet.balance),
            "status": payment_record.status
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to credit Razorpay payment to wallet"
        )
