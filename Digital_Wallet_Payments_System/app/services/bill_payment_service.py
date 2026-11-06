from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Wallet, Account, Transaction, BillPayment
from app.services.ledger_service import (
    create_transaction_reference,
    record_transaction
)
from app.services.idempotency_service import (
    get_or_create_idempotency_key,
    complete_idempotency_key,
    release_idempotency_lock
)
from app.routers.pin import verify_transaction_pin


def execute_bill_payment(
    db: Session,
    user_id: int,
    bill_type: str,
    provider_name: str,
    consumer_number: str,
    amount: Decimal,
    pin: str,
    idempotency_key: str
):
    lock_name = None

    try:
        try:
            amount = Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="Invalid bill payment amount"
            )

        if not amount.is_finite() or amount <= Decimal("0.00"):
            raise HTTPException(
                status_code=422,
                detail="Amount must be greater than zero"
            )

        if amount != amount.quantize(Decimal("0.01")):
            raise HTTPException(
                status_code=422,
                detail="Amount cannot have more than two decimal places"
            )

        amount = amount.quantize(Decimal("0.01"))

        if amount > Decimal("50000.00"):
            raise HTTPException(
                status_code=422,
                detail="Bill payment cannot exceed ₹50,000"
            )

        if bill_type not in ["Mobile Recharge", "Electricity"]:
            raise HTTPException(
                status_code=422,
                detail="Unsupported bill type"
            )

        provider_name = provider_name.strip()
        consumer_number = consumer_number.strip()

        if not provider_name or not consumer_number:
            raise HTTPException(
                status_code=422,
                detail="Provider name and consumer number are required"
            )

        request_data = {
            "bill_type": bill_type,
            "provider_name": provider_name,
            "consumer_number": consumer_number,
            "amount": str(amount)
        }

        idempotency_record, saved_response, lock_name = (
            get_or_create_idempotency_key(
                db=db,
                user_id=user_id,
                endpoint="/bills/pay",
                idempotency_key=idempotency_key,
                request_data=request_data
            )
        )

        if saved_response is not None:
            db.rollback()
            return saved_response, True

        wallet = (
            db.query(Wallet)
            .filter(Wallet.owner_id == user_id)
            .with_for_update()
            .first()
        )

        if not wallet:
            raise HTTPException(
                status_code=404,
                detail="Wallet not found"
            )

        if wallet.status != "Active":
            raise HTTPException(
                status_code=403,
                detail="Wallet is not active"
            )

        auth_db = None

        try:
            from app.database import SessionLocal

            auth_db = SessionLocal()

            verify_transaction_pin(
                auth_db,
                user_id,
                pin
            )

        finally:
            if auth_db:
                auth_db.close()

        wallet_account = (
            db.query(Account)
            .filter(Account.wallet_id == wallet.id)
            .with_for_update()
            .first()
        )

        settlement_account = (
            db.query(Account)
            .filter(
                Account.account_code == "BANK-SETTLEMENT"
            )
            .with_for_update()
            .first()
        )

        if not wallet_account or not settlement_account:
            raise HTTPException(
                status_code=404,
                detail="Required ledger accounts not found"
            )

        if Decimal(str(wallet.balance)) < amount:
            raise HTTPException(
                status_code=400,
                detail="Insufficient wallet balance"
            )

        transaction = Transaction(
            transaction_ref=create_transaction_reference(),
            type="Bill Payment",
            amount=amount,
            status="Success",
            initiated_by=user_id,
            description=f"{bill_type} payment to {provider_name}",
            is_flagged=False
        )

        db.add(transaction)
        db.flush()

        record_transaction(
            db,
            transaction,
            [
                {
                    "account_id": wallet_account.id,
                    "entry_type": "Debit",
                    "amount": amount
                },
                {
                    "account_id": settlement_account.id,
                    "entry_type": "Credit",
                    "amount": amount
                }
            ]
        )

        bill_payment = BillPayment(
            user_id=user_id,
            transaction_id=transaction.id,
            bill_type=bill_type,
            provider_name=provider_name,
            consumer_number=consumer_number,
            amount=amount,
            status="Success"
        )

        db.add(bill_payment)
        db.flush()

        response_data = {
            "message": "Bill payment successful",
            "bill_payment_id": bill_payment.id,
            "transaction_ref": transaction.transaction_ref,
            "bill_type": bill_type,
            "provider_name": provider_name,
            "consumer_number": consumer_number,
            "amount": str(amount),
            "status": "Success",
            "wallet_balance": str(wallet.balance)
        }

        complete_idempotency_key(
            db,
            idempotency_record,
            response_data
        )

        db.commit()

        return response_data, False

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Bill payment failed. No money was deducted."
        )

    finally:
        if lock_name:
            try:
                release_idempotency_lock(
                    db,
                    lock_name
                )
            except Exception:
                db.rollback()
