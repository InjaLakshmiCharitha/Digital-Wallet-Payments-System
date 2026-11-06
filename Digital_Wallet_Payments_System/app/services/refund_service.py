from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    User,
    Wallet,
    Account,
    Transaction,
    MerchantPayment,
    Refund,
    Cashback
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


def execute_merchant_refund(
    db: Session,
    merchant_user_id: int,
    transaction_ref: str,
    amount: Decimal,
    pin: str,
    idempotency_key: str,
    reason: str | None = None
):
    lock_name = None
    auth_db = None

    try:
        try:
            amount = Decimal(str(amount))

        except (InvalidOperation, TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="Invalid refund amount"
            )

        if not amount.is_finite() or amount <= Decimal("0.00"):
            raise HTTPException(
                status_code=422,
                detail="Refund amount must be greater than zero"
            )

        if amount != amount.quantize(Decimal("0.01")):
            raise HTTPException(
                status_code=422,
                detail="Refund amount cannot have more than two decimal places"
            )

        amount = amount.quantize(Decimal("0.01"))

        if not pin or len(pin) != 4 or not pin.isdigit():
            raise HTTPException(
                status_code=422,
                detail="A valid four-digit PIN is required"
            )

        if not transaction_ref or not transaction_ref.strip():
            raise HTTPException(
                status_code=422,
                detail="Transaction reference is required"
            )

        transaction_ref = transaction_ref.strip()

        if reason is not None:
            reason = reason.strip() or None

        request_data = {
            "transaction_ref": transaction_ref,
            "amount": str(amount),
            "reason": reason,
            "pin": pin
        }

        endpoint = f"/payments/{transaction_ref}/refund"

        idempotency_record, saved_response, lock_name = (
            get_or_create_idempotency_key(
                db=db,
                user_id=merchant_user_id,
                endpoint=endpoint,
                idempotency_key=idempotency_key,
                request_data=request_data
            )
        )

        if saved_response is not None:
            db.rollback()
            return saved_response, True

        auth_db = SessionLocal()

        auth_user = (
            auth_db.query(User)
            .filter(User.id == merchant_user_id)
            .first()
        )

        if not auth_user:
            raise HTTPException(
                status_code=404,
                detail="Merchant account not found"
            )

        if not auth_user.is_active:
            raise HTTPException(
                status_code=403,
                detail="Merchant account is inactive"
            )

        verify_transaction_pin(
            auth_db,
            auth_user,
            pin
        )

        auth_db.close()
        auth_db = None

        merchant_payment = (
            db.query(MerchantPayment)
            .join(
                Transaction,
                Transaction.id == MerchantPayment.transaction_id
            )
            .filter(
                Transaction.transaction_ref == transaction_ref,
                Transaction.type == "Merchant Payment",
                Transaction.status == "Success"
            )
            .with_for_update()
            .first()
        )

        if not merchant_payment:
            raise HTTPException(
                status_code=404,
                detail="Successful merchant payment not found"
            )

        merchant = merchant_payment.merchant

        if not merchant or merchant.user_id != merchant_user_id:
            raise HTTPException(
                status_code=403,
                detail="Only the receiving merchant can refund this payment"
            )

        original_transaction = merchant_payment.transaction

        now = datetime.utcnow()

        if now > original_transaction.created_at + timedelta(days=7):
            raise HTTPException(
                status_code=400,
                detail="Refund period of seven days has expired"
            )

        refunded_amount = (
            db.query(func.coalesce(func.sum(Refund.amount), 0))
            .filter(
                Refund.merchant_payment_id == merchant_payment.id,
                Refund.status == "Success"
            )
            .scalar()
        )

        refunded_amount = Decimal(str(refunded_amount or "0.00"))

        remaining_refundable = (
            Decimal(str(merchant_payment.amount)) - refunded_amount
        )

        if amount > remaining_refundable:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Maximum refundable amount is "
                    f"₹{remaining_refundable:,.2f}"
                )
            )

        customer_id = merchant_payment.customer_id

        merchant_wallet_id = (
            db.query(Wallet.id)
            .filter(Wallet.merchant_id == merchant.id)
            .scalar()
        )

        customer_wallet_id = (
            db.query(Wallet.id)
            .filter(Wallet.owner_id == customer_id)
            .scalar()
        )

        if not merchant_wallet_id or not customer_wallet_id:
            raise HTTPException(
                status_code=404,
                detail="Merchant or customer wallet not found"
            )

        wallet_ids = sorted({
            merchant_wallet_id,
            customer_wallet_id
        })

        account_rows = (
            db.query(Account)
            .filter(Account.wallet_id.in_(wallet_ids))
            .order_by(Account.id.asc())
            .all()
        )

        account_by_wallet = {
            account.wallet_id: account
            for account in account_rows
        }

        merchant_account = account_by_wallet.get(merchant_wallet_id)
        customer_account = account_by_wallet.get(customer_wallet_id)

        if not merchant_account or not customer_account:
            raise HTTPException(
                status_code=404,
                detail="Required ledger accounts not found"
            )

        account_ids = sorted({
            merchant_account.id,
            customer_account.id
        })

        locked_accounts = (
            db.query(Account)
            .filter(Account.id.in_(account_ids))
            .order_by(Account.id.asc())
            .with_for_update()
            .all()
        )

        account_map = {
            account.id: account
            for account in locked_accounts
        }

        if len(account_map) != len(account_ids):
            raise HTTPException(
                status_code=404,
                detail="Required ledger accounts not found"
            )

        merchant_account = account_map[merchant_account.id]
        customer_account = account_map[customer_account.id]

        wallets = (
            db.query(Wallet)
            .filter(Wallet.id.in_(wallet_ids))
            .order_by(Wallet.id.asc())
            .with_for_update()
            .all()
        )

        if len(wallets) != 2:
            raise HTTPException(
                status_code=404,
                detail="Required wallets not found"
            )

        wallet_map = {
            wallet.id: wallet
            for wallet in wallets
        }

        merchant_wallet = wallet_map[merchant_wallet_id]
        customer_wallet = wallet_map[customer_wallet_id]

        if merchant_wallet.status != "Active":
            raise HTTPException(
                status_code=403,
                detail="Merchant wallet is not active"
            )

        if customer_wallet.status != "Active":
            raise HTTPException(
                status_code=403,
                detail="Customer wallet is not active"
            )

        if merchant_wallet.balance < amount:
            raise HTTPException(
                status_code=400,
                detail="Insufficient merchant wallet balance for refund"
            )

        if merchant_account.balance < amount:
            raise HTTPException(
                status_code=400,
                detail="Insufficient merchant ledger balance"
            )

        refund_transaction = Transaction(
            transaction_ref=create_transaction_reference(),
            type="Merchant Refund",
            amount=amount,
            status="Success",
            initiated_by=merchant_user_id,
            description=reason or f"Refund for {transaction_ref}",
            is_flagged=False
        )

        db.add(refund_transaction)
        db.flush()

        refund = Refund(
            merchant_payment_id=merchant_payment.id,
            transaction_id=refund_transaction.id,
            initiated_by=merchant_user_id,
            amount=amount,
            reason=reason,
            status="Success"
        )

        db.add(refund)

        record_transaction(
            db,
            refund_transaction,
            [
                {
                    "account_id": merchant_account.id,
                    "entry_type": "Debit",
                    "amount": amount
                },
                {
                    "account_id": customer_account.id,
                    "entry_type": "Credit",
                    "amount": amount
                }
            ]
        )

        pending_cashbacks = (
            db.query(Cashback)
            .filter(
                Cashback.merchant_payment_id == merchant_payment.id,
                Cashback.status == "Pending"
            )
            .with_for_update()
            .all()
        )

        for cashback in pending_cashbacks:
            cashback.status = "Cancelled"

        total_refunded = refunded_amount + amount

        response_data = {
            "message": "Merchant refund processed successfully",
            "refund_transaction_ref": refund_transaction.transaction_ref,
            "original_transaction_ref": transaction_ref,
            "refund_amount": str(amount),
            "total_refunded": str(total_refunded),
            "remaining_refundable": str(
                Decimal(str(merchant_payment.amount)) - total_refunded
            ),
            "customer_id": customer_id,
            "status": "Success",
            "cashback_cancelled": bool(pending_cashbacks),
            "customer_wallet_balance": str(customer_wallet.balance)
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
            detail="Invalid refund amount"
        )

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Refund failed. No money was deducted."
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

