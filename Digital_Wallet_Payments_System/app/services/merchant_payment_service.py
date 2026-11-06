from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    User,
    Merchant,
    Wallet,
    Account,
    Transaction,
    MerchantPayment,
    Cashback,
    IdempotencyKey
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


def execute_merchant_payment(
    db: Session,
    customer_id: int,
    merchant_code: str,
    amount: Decimal,
    pin: str,
    idempotency_key: str
):
    lock_name = None
    auth_db = None

    try:
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))

        if not amount.is_finite() or amount <= Decimal("0.00"):
            raise HTTPException(
                status_code=422,
                detail="Payment amount must be greater than zero"
            )

        if not merchant_code:
            raise HTTPException(
                status_code=422,
                detail="Merchant code is required"
            )

        if not pin or len(pin) != 4 or not pin.isdigit():
            raise HTTPException(
                status_code=422,
                detail="A valid four-digit PIN is required"
            )

        request_data = {
            "merchant_code": merchant_code,
            "amount": str(amount),
            "pin": pin
        }

        idempotency_record, saved_response, lock_name = (
            get_or_create_idempotency_key(
                db=db,
                user_id=customer_id,
                endpoint="/payments/merchant",
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
            .filter(User.id == customer_id)
            .first()
        )

        if not auth_user or not auth_user.is_active:
            raise HTTPException(
                status_code=404,
                detail="Customer account not found or inactive"
            )

        verify_transaction_pin(
            auth_db,
            auth_user,
            pin
        )

        auth_db.close()
        auth_db = None

        customer = (
            db.query(User)
            .filter(
                User.id == customer_id,
                User.is_active.is_(True)
            )
            .first()
        )

        if not customer:
            raise HTTPException(
                status_code=404,
                detail="Customer account not found or inactive"
            )

        merchant = (
            db.query(Merchant)
            .filter(
                Merchant.merchant_code == merchant_code,
                Merchant.is_approved.is_(True)
            )
            .first()
        )

        if not merchant:
            raise HTTPException(
                status_code=404,
                detail="Approved merchant not found"
            )

        if merchant.user_id == customer_id:
            raise HTTPException(
                status_code=400,
                detail="You cannot pay your own merchant account"
            )

        customer_wallet_id = (
            db.query(Wallet.id)
            .filter(Wallet.owner_id == customer_id)
            .scalar()
        )

        merchant_wallet_id = (
            db.query(Wallet.id)
            .filter(Wallet.merchant_id == merchant.id)
            .scalar()
        )

        if not customer_wallet_id or not merchant_wallet_id:
            raise HTTPException(
                status_code=404,
                detail="Customer or merchant wallet not found"
            )

        wallet_ids = sorted([
            customer_wallet_id,
            merchant_wallet_id
        ])

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

        customer_wallet = wallet_map[customer_wallet_id]
        merchant_wallet = wallet_map[merchant_wallet_id]

        if customer_wallet.status != "Active":
            raise HTTPException(
                status_code=403,
                detail="Your wallet is not active"
            )

        if merchant_wallet.status != "Active":
            raise HTTPException(
                status_code=403,
                detail="Merchant wallet is not active"
            )

        if customer_wallet.balance < amount:
            raise HTTPException(
                status_code=400,
                detail="Insufficient wallet balance"
            )

        customer_account = (
            db.query(Account)
            .filter(Account.wallet_id == customer_wallet_id)
            .first()
        )

        merchant_account = (
            db.query(Account)
            .filter(Account.wallet_id == merchant_wallet_id)
            .first()
        )

        fee_account = (
            db.query(Account)
            .filter(Account.account_code == "PLATFORM-FEES")
            .first()
        )

        if not customer_account or not merchant_account or not fee_account:
            raise HTTPException(
                status_code=404,
                detail="Required ledger accounts not found"
            )

        account_ids = sorted([
            customer_account.id,
            merchant_account.id,
            fee_account.id
        ])

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

        customer_account = account_map[customer_account.id]
        merchant_account = account_map[merchant_account.id]
        fee_account = account_map[fee_account.id]

        if customer_account.balance < amount:
            raise HTTPException(
                status_code=400,
                detail="Insufficient ledger account balance"
            )

        daily_limit = DAILY_TRANSFER_LIMITS.get(
            customer_wallet.kyc_level
        )

        monthly_limit = MONTHLY_TRANSFER_LIMITS.get(
            customer_wallet.kyc_level
        )

        if daily_limit is None or monthly_limit is None:
            raise HTTPException(
                status_code=400,
                detail="Invalid customer KYC level"
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

        daily_used = get_outgoing_total(
            db,
            customer_account.id,
            day_start
        )

        monthly_used = get_outgoing_total(
            db,
            customer_account.id,
            month_start
        )

        daily_remaining = max(
            daily_limit - daily_used,
            Decimal("0.00")
        )

        monthly_remaining = max(
            monthly_limit - monthly_used,
            Decimal("0.00")
        )

        if amount > daily_remaining:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Daily limit of ₹{daily_limit:,.2f} reached. "
                    f"You can pay ₹{daily_remaining:,.2f} more today."
                )
            )

        if amount > monthly_remaining:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Monthly limit of ₹{monthly_limit:,.2f} reached. "
                    f"You can pay ₹{monthly_remaining:,.2f} more this month."
                )
            )

        platform_fee = (
            amount * Decimal("0.01")
        ).quantize(Decimal("0.01"))

        net_amount = amount - platform_fee

        cashback_amount = min(
            (amount * Decimal("0.02")).quantize(Decimal("0.01")),
            Decimal("50.00")
        )

        transaction = Transaction(
            transaction_ref=create_transaction_reference(),
            type="Merchant Payment",
            amount=amount,
            status="Success",
            initiated_by=customer_id,
            description=f"Payment to {merchant.business_name}",
            is_flagged=False
        )

        db.add(transaction)
        db.flush()

        merchant_payment = MerchantPayment(
            transaction_id=transaction.id,
            merchant_id=merchant.id,
            customer_id=customer_id,
            amount=amount,
            platform_fee=platform_fee,
            net_amount=net_amount
        )

        cashback = Cashback(
            merchant_payment_id=merchant_payment.id,
            user_id=customer_id,
            amount=cashback_amount,
            status="Pending",
            eligible_at=now + timedelta(hours=24)
        )

        db.add(merchant_payment)
        db.flush()

        cashback.merchant_payment_id = merchant_payment.id
        db.add(cashback)

        record_transaction(
            db,
            transaction,
            [
                {
                    "account_id": customer_account.id,
                    "entry_type": "Debit",
                    "amount": amount
                },
                {
                    "account_id": merchant_account.id,
                    "entry_type": "Credit",
                    "amount": net_amount
                },
                {
                    "account_id": fee_account.id,
                    "entry_type": "Credit",
                    "amount": platform_fee
                }
            ]
        )

        response_data = {
            "message": "Merchant payment successful",
            "transaction_ref": transaction.transaction_ref,
            "merchant_name": merchant.business_name,
            "merchant_code": merchant.merchant_code,
            "amount": str(amount),
            "platform_fee": str(platform_fee),
            "merchant_received": str(net_amount),
            "cashback_pending": str(cashback_amount),
            "cashback_eligible_at": cashback.eligible_at.isoformat(),
            "status": transaction.status,
            "wallet_balance": str(customer_wallet.balance)
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
            detail="Invalid payment amount"
        )

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Merchant payment failed. No money was deducted."
        )

    finally:
        if auth_db is not None:
            auth_db.close()

        if lock_name:
            try:
                release_idempotency_lock(db, lock_name)
            except Exception:
                db.rollback()
