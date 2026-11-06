from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Wallet, Account, Transaction
from app.services.ledger_service import (
    create_transaction_reference,
    record_transaction
)
from app.services.idempotency_service import (
    get_or_create_idempotency_key,
    complete_idempotency_key,
    release_idempotency_lock
)


KYC_BALANCE_LIMITS = {
    "Minimum": Decimal("10000.00"),
    "Full": Decimal("200000.00")
}


def execute_add_money(
    db: Session,
    user_id: int,
    amount: Decimal,
    source: str,
    simulate_status: str,
    idempotency_key: str
):
    lock_name = None

    try:
        try:
            amount = Decimal(str(amount))

        except (InvalidOperation, TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="Invalid add money amount"
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

        if amount < Decimal("10.00") or amount > Decimal("50000.00"):
            raise HTTPException(
                status_code=422,
                detail="Amount must be between ₹10 and ₹50,000"
            )

        if source not in ["UPI", "Card", "Net Banking"]:
            raise HTTPException(
                status_code=422,
                detail="Invalid payment source"
            )

        if simulate_status not in ["Success", "Failed"]:
            raise HTTPException(
                status_code=422,
                detail="Invalid simulated payment status"
            )

        request_data = {
            "amount": str(amount),
            "source": source,
            "simulate_status": simulate_status
        }

        idempotency_record, saved_response, lock_name = (
            get_or_create_idempotency_key(
                db=db,
                user_id=user_id,
                endpoint="/wallet/add-money",
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

        if simulate_status == "Failed":
            transaction = Transaction(
                transaction_ref=create_transaction_reference(),
                type="Add Money",
                amount=amount,
                status="Failed",
                initiated_by=user_id,
                description=f"Add money through {source}",
                is_flagged=False
            )

            db.add(transaction)
            db.flush()

            response_data = {
                "message": "Add money failed",
                "transaction_ref": transaction.transaction_ref,
                "amount": str(amount),
                "source": source,
                "status": "Failed",
                "wallet_balance": str(wallet.balance)
            }

            complete_idempotency_key(
                db,
                idempotency_record,
                response_data
            )

            db.commit()

            return response_data, False

        balance_limit = KYC_BALANCE_LIMITS.get(wallet.kyc_level)

        if balance_limit is None:
            raise HTTPException(
                status_code=403,
                detail="Invalid wallet KYC level"
            )

        if wallet.balance + amount > balance_limit:
            raise HTTPException(
                status_code=403,
                detail=f"Wallet balance cannot exceed ₹{balance_limit:,.2f}"
            )

        wallet_account = (
            db.query(Account)
            .filter(Account.wallet_id == wallet.id)
            .with_for_update()
            .first()
        )

        bank_account = (
            db.query(Account)
            .filter(
                Account.account_code == "BANK-SETTLEMENT"
            )
            .with_for_update()
            .first()
        )

        if not wallet_account or not bank_account:
            raise HTTPException(
                status_code=404,
                detail="Required ledger accounts not found"
            )

        transaction = Transaction(
            transaction_ref=create_transaction_reference(),
            type="Add Money",
            amount=amount,
            status="Success",
            initiated_by=user_id,
            description=f"Add money through {source}",
            is_flagged=False
        )

        db.add(transaction)
        db.flush()

        record_transaction(
            db,
            transaction,
            [
                {
                    "account_id": bank_account.id,
                    "entry_type": "Debit",
                    "amount": amount
                },
                {
                    "account_id": wallet_account.id,
                    "entry_type": "Credit",
                    "amount": amount
                }
            ]
        )

        response_data = {
            "message": "Money added successfully",
            "transaction_ref": transaction.transaction_ref,
            "amount": str(amount),
            "source": source,
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

    except (InvalidOperation, ValueError):
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail="Invalid add money amount"
        )

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Add money failed. No money was added."
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

