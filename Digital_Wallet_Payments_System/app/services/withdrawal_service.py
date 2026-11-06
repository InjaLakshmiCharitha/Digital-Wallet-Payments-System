from decimal import Decimal, InvalidOperation
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    User,
    Wallet,
    BankAccount,
    Account,
    Transaction,
    Withdrawal
)
from app.routers.pin import verify_transaction_pin
from app.services.ledger_service import (
    create_transaction_reference,
    record_transaction
)
from app.services.idempotency_service import (
    get_or_create_idempotency_key,
    complete_idempotency_key,
    release_idempotency_lock
)
from app.services.transfer_service import (
    get_outgoing_total,
    DAILY_TRANSFER_LIMITS,
    MONTHLY_TRANSFER_LIMITS
)


def execute_withdrawal(
    db: Session,
    user_id: int,
    bank_account_id: int,
    amount: Decimal,
    pin: str,
    idempotency_key: str
):
    lock_name = None
    auth_db = None

    try:
        try:
            amount = Decimal(str(amount))

        except (InvalidOperation, TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="Invalid withdrawal amount"
            )

        if not amount.is_finite() or amount <= Decimal("0.00"):
            raise HTTPException(
                status_code=422,
                detail="Withdrawal amount must be greater than zero"
            )

        if amount != amount.quantize(Decimal("0.01")):
            raise HTTPException(
                status_code=422,
                detail="Withdrawal amount cannot have more than two decimal places"
            )

        amount = amount.quantize(Decimal("0.01"))

        if amount < Decimal("100.00"):
            raise HTTPException(
                status_code=422,
                detail="Minimum withdrawal amount is ₹100"
            )

        if not isinstance(bank_account_id, int) or bank_account_id <= 0:
            raise HTTPException(
                status_code=422,
                detail="Invalid bank account ID"
            )

        if not pin or len(pin) != 4 or not pin.isdigit():
            raise HTTPException(
                status_code=422,
                detail="A valid four-digit PIN is required"
            )

        request_data = {
            "bank_account_id": bank_account_id,
            "amount": str(amount),
            "pin": pin
        }

        idempotency_record, saved_response, lock_name = (
            get_or_create_idempotency_key(
                db=db,
                user_id=user_id,
                endpoint="/withdrawals",
                idempotency_key=idempotency_key,
                request_data=request_data
            )
        )

        if saved_response is not None:
            db.rollback()
            return saved_response, True

        auth_db = SessionLocal()

        user = auth_db.query(User).filter(
            User.id == user_id
        ).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if not user.is_active:
            raise HTTPException(
                status_code=403,
                detail="Your account is inactive"
            )

        verify_transaction_pin(
            auth_db,
            user,
            pin
        )

        auth_db.close()
        auth_db = None

        user = (
            db.query(User)
            .filter(User.id == user_id)
            .first()
        )

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if not user.is_active:
            raise HTTPException(
                status_code=403,
                detail="Your account is inactive"
            )

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
                status_code=423,
                detail="Wallet is frozen or inactive"
            )

        if user.role != "Merchant" and wallet.kyc_level != "Full":
            raise HTTPException(
                status_code=403,
                detail="Full KYC is required to withdraw money"
            )

        bank_account = (
            db.query(BankAccount)
            .filter(
                BankAccount.id == bank_account_id,
                BankAccount.user_id == user_id
            )
            .with_for_update()
            .first()
        )

        if not bank_account:
            raise HTTPException(
                status_code=404,
                detail="Linked bank account not found"
            )

        if not bank_account.is_active:
            raise HTTPException(
                status_code=400,
                detail="Selected bank account is inactive"
            )

        if wallet.balance < amount:
            raise HTTPException(
                status_code=400,
                detail="Insufficient wallet balance"
            )

        now = datetime.utcnow()

        day_start = now.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        month_start = now.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        daily_limit = DAILY_TRANSFER_LIMITS.get(
            wallet.kyc_level,
            Decimal("0")
        )

        monthly_limit = MONTHLY_TRANSFER_LIMITS.get(
            wallet.kyc_level,
            Decimal("0")
        )

        daily_used = get_outgoing_total(
            db,
            wallet.id,
            day_start
        )

        monthly_used = get_outgoing_total(
            db,
            wallet.id,
            month_start
        )

        if daily_used + amount > daily_limit:
            remaining = max(
                daily_limit - daily_used,
                Decimal("0")
            )

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Daily limit of ₹{daily_limit:,.2f} reached. "
                    f"You can withdraw ₹{remaining:,.2f} more today"
                )
            )

        if monthly_used + amount > monthly_limit:
            remaining = max(
                monthly_limit - monthly_used,
                Decimal("0")
            )

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Monthly limit of ₹{monthly_limit:,.2f} reached. "
                    f"You can withdraw ₹{remaining:,.2f} more this month"
                )
            )

        wallet_account = (
            db.query(Account)
            .filter(Account.wallet_id == wallet.id)
            .with_for_update()
            .first()
        )

        clearing_account = (
            db.query(Account)
            .filter(
                Account.account_code == "WITHDRAWAL-CLEARING"
            )
            .with_for_update()
            .first()
        )

        if not wallet_account or not clearing_account:
            raise HTTPException(
                status_code=404,
                detail="Required ledger accounts not found"
            )

        transaction = Transaction(
            transaction_ref=create_transaction_reference(),
            type="Withdrawal",
            amount=amount,
            status="Pending",
            initiated_by=user_id,
            description=f"Withdrawal to {bank_account.bank_name}",
            is_flagged=False
        )

        db.add(transaction)
        db.flush()

        withdrawal = Withdrawal(
            transaction_id=transaction.id,
            user_id=user_id,
            bank_account_id=bank_account.id,
            amount=amount,
            status="Pending",
            processed_at=None,
            failure_reason=None
        )

        db.add(withdrawal)
        db.flush()

        transaction.status = "Success"

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
                    "account_id": clearing_account.id,
                    "entry_type": "Credit",
                    "amount": amount
                }
            ]
        )

        response_data = {
            "message": "Withdrawal request submitted successfully",
            "transaction_ref": transaction.transaction_ref,
            "withdrawal_id": withdrawal.id,
            "bank_account_id": bank_account.id,
            "amount": str(amount),
            "status": "Pending",
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

    except (InvalidOperation, ValueError):
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail="Invalid withdrawal amount"
        )

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Withdrawal failed. No money was deducted."
        )

    finally:
        if auth_db is not None:
            auth_db.close()

        if lock_name:
            try:
                release_idempotency_lock(
                    db,
                    lock_name
                )
            except Exception:
                db.rollback()
