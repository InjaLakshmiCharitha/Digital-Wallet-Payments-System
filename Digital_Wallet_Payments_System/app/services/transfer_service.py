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
    LedgerEntry,
    IdempotencyKey
)
from app.routers.pin import verify_transaction_pin
from app.services.otp_service import verify_otp
from app.services.ledger_service import (
    create_transaction_reference,
    record_transaction
)
from app.services.idempotency_service import (
    create_request_hash,
    get_lock_name,
    acquire_idempotency_lock,
    release_idempotency_lock,
    complete_idempotency_key
)
from app.services.fraud_service import (
    should_flag_transaction,
    place_transaction_on_hold
)


KYC_BALANCE_LIMITS = {
    "Minimum": Decimal("10000.00"),
    "Full": Decimal("200000.00")
}

DAILY_TRANSFER_LIMITS = {
    "Minimum": Decimal("10000.00"),
    "Full": Decimal("25000.00")
}

MONTHLY_TRANSFER_LIMITS = {
    "Minimum": Decimal("25000.00"),
    "Full": Decimal("100000.00")
}

OUTGOING_TRANSACTION_TYPES = [
    "Transfer",
    "Merchant Payment",
    "Withdrawal"
]


def get_outgoing_total(
    db: Session,
    account_id: int,
    start_date: datetime
) -> Decimal:
    total = (
        db.query(func.coalesce(func.sum(LedgerEntry.amount), 0))
        .join(
            Transaction,
            Transaction.id == LedgerEntry.transaction_id
        )
        .filter(
            LedgerEntry.account_id == account_id,
            LedgerEntry.entry_type == "Debit",
            LedgerEntry.created_at >= start_date,
            Transaction.type.in_(OUTGOING_TRANSACTION_TYPES)
        )
        .scalar()
    )

    return Decimal(str(total or "0.00"))


def format_amount(amount: Decimal) -> str:
    return f"₹{amount:,.2f}"


def execute_safe_transfer(
    db: Session,
    sender_id: int,
    receiver_phone: str,
    amount: Decimal,
    idempotency_key: str,
    description: str = "Wallet transfer",
    pin: str = "",
    otp: str | None = None,
    preauthorized: bool = False
):
    lock_name = None
    auth_db = None

    try:
        amount = Decimal(str(amount))

        if not amount.is_finite() or amount <= Decimal("0.00"):
            raise HTTPException(
                status_code=422,
                detail="Transfer amount must be greater than zero"
            )

        if amount != amount.quantize(Decimal("0.01")):
            raise HTTPException(
                status_code=422,
                detail="Transfer amount cannot have more than two decimal places"
            )

        amount = amount.quantize(Decimal("0.01"))

        if preauthorized and amount > Decimal("5000.00"):
            raise HTTPException(
                status_code=400,
                detail="Scheduled transfers cannot exceed ₹5,000 per execution"
            )

        if (
            not receiver_phone
            or len(receiver_phone) != 10
            or not receiver_phone.isdigit()
        ):
            raise HTTPException(
                status_code=422,
                detail="Invalid receiver phone number"
            )

        if not idempotency_key or len(idempotency_key) > 128:
            raise HTTPException(
                status_code=400,
                detail="A valid Idempotency-Key is required"
            )

        if not preauthorized and (
            not pin or len(pin) != 4 or not pin.isdigit()
        ):
            raise HTTPException(
                status_code=422,
                detail="A valid four-digit transaction PIN is required"
            )

        request_data = {
            "receiver_phone": receiver_phone,
            "amount": str(amount),
            "description": description,
            "pin": "PREAUTHORIZED_SCHEDULE" if preauthorized else pin,
            "otp": otp,
            "preauthorized": preauthorized
        }

        request_hash = create_request_hash(request_data)

        lock_name = get_lock_name(
            sender_id,
            "/transfers",
            idempotency_key
        )

        if not acquire_idempotency_lock(db, lock_name):
            raise HTTPException(
                status_code=409,
                detail="This transfer request is already being processed"
            )

        existing_record = (
            db.query(IdempotencyKey)
            .filter(
                IdempotencyKey.user_id == sender_id,
                IdempotencyKey.endpoint == "/transfers",
                IdempotencyKey.key == idempotency_key
            )
            .with_for_update()
            .first()
        )

        now = datetime.utcnow()
        expired_record = False

        if existing_record:
            if existing_record.expires_at > now:
                if existing_record.request_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="This Idempotency-Key was already used with a different request"
                    )

                if existing_record.status == "Completed":
                    saved_response = existing_record.response_data
                    db.rollback()
                    return saved_response, True

                raise HTTPException(
                    status_code=409,
                    detail="This transfer request is already being processed"
                )

            expired_record = True

        auth_db = SessionLocal()

        auth_user = (
            auth_db.query(User)
            .filter(User.id == sender_id)
            .first()
        )

        if not auth_user or not auth_user.is_active:
            raise HTTPException(
                status_code=403,
                detail="Sender account not found or inactive"
            )

        if not preauthorized:
            verify_transaction_pin(
                auth_db,
                auth_user,
                pin
            )

            if amount > Decimal("5000.00"):
                if not otp:
                    raise HTTPException(
                        status_code=400,
                        detail="OTP is required for transfers above ₹5,000"
                    )

                verify_otp(
                    auth_db,
                    sender_id,
                    "High Value Transfer",
                    otp
                )

        auth_db.close()
        auth_db = None

        sender = (
            db.query(User)
            .filter(User.id == sender_id)
            .first()
        )

        if not sender or not sender.is_active:
            raise HTTPException(
                status_code=403,
                detail="Sender account not found or inactive"
            )

        receiver = (
            db.query(User)
            .filter(User.phone == receiver_phone)
            .first()
        )

        if not receiver or not receiver.is_active:
            raise HTTPException(
                status_code=404,
                detail="Receiver not found or inactive"
            )

        if sender.id == receiver.id:
            raise HTTPException(
                status_code=400,
                detail="You cannot transfer money to yourself"
            )

        sender_wallet_id = (
            db.query(Wallet.id)
            .filter(Wallet.owner_id == sender.id)
            .scalar()
        )

        receiver_wallet_id = (
            db.query(Wallet.id)
            .filter(Wallet.owner_id == receiver.id)
            .scalar()
        )

        if not sender_wallet_id or not receiver_wallet_id:
            raise HTTPException(
                status_code=404,
                detail="Sender or receiver wallet not found"
            )

        wallet_ids = sorted([
            sender_wallet_id,
            receiver_wallet_id
        ])

        locked_wallets = (
            db.query(Wallet)
            .filter(Wallet.id.in_(wallet_ids))
            .order_by(Wallet.id.asc())
            .with_for_update()
            .all()
        )

        if len(locked_wallets) != 2:
            raise HTTPException(
                status_code=404,
                detail="Required wallets not found"
            )

        wallet_map = {
            wallet.id: wallet
            for wallet in locked_wallets
        }

        sender_wallet = wallet_map[sender_wallet_id]
        receiver_wallet = wallet_map[receiver_wallet_id]

        if sender_wallet.status != "Active":
            raise HTTPException(
                status_code=403,
                detail="Sender wallet is not active"
            )

        if receiver_wallet.status != "Active":
            raise HTTPException(
                status_code=403,
                detail="Receiver wallet is not active"
            )

        sender_kyc_level = sender_wallet.kyc_level

        daily_limit = DAILY_TRANSFER_LIMITS.get(sender_kyc_level)
        monthly_limit = MONTHLY_TRANSFER_LIMITS.get(sender_kyc_level)

        if daily_limit is None or monthly_limit is None:
            raise HTTPException(
                status_code=400,
                detail="Invalid sender KYC level"
            )

        account_rows = (
            db.query(Account)
            .filter(Account.wallet_id.in_(wallet_ids))
            .order_by(Account.id.asc())
            .with_for_update()
            .all()
        )

        account_map = {
            account.wallet_id: account
            for account in account_rows
        }

        sender_account = account_map.get(sender_wallet_id)
        receiver_account = account_map.get(receiver_wallet_id)

        if not sender_account or not receiver_account:
            raise HTTPException(
                status_code=404,
                detail="Wallet ledger account not found"
            )

        if sender_wallet.balance < amount:
            raise HTTPException(
                status_code=400,
                detail="Insufficient wallet balance"
            )

        if sender_account.balance < amount:
            raise HTTPException(
                status_code=400,
                detail="Insufficient ledger account balance"
            )

        receiver_balance_limit = KYC_BALANCE_LIMITS.get(
            receiver_wallet.kyc_level
        )

        if receiver_balance_limit is None:
            raise HTTPException(
                status_code=400,
                detail="Invalid receiver KYC level"
            )

        if receiver_wallet.balance + amount > receiver_balance_limit:
            remaining_balance = max(
                receiver_balance_limit - receiver_wallet.balance,
                Decimal("0.00")
            )

            raise HTTPException(
                status_code=400,
                detail=(
                    "Receiver wallet balance limit would be exceeded. "
                    f"Receiver can receive only {format_amount(remaining_balance)} more."
                )
            )

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
            sender_account.id,
            day_start
        )

        monthly_used = get_outgoing_total(
            db,
            sender_account.id,
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
                    f"Daily limit of {format_amount(daily_limit)} would be exceeded. "
                    f"You can send {format_amount(daily_remaining)} more today."
                )
            )

        if amount > monthly_remaining:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Monthly limit of {format_amount(monthly_limit)} would be exceeded. "
                    f"You can send {format_amount(monthly_remaining)} more this month."
                )
            )

        if expired_record:
            idempotency_record = existing_record
            idempotency_record.request_hash = request_hash
            idempotency_record.response_data = None
            idempotency_record.status = "Processing"
            idempotency_record.expires_at = now + timedelta(hours=24)
        else:
            idempotency_record = IdempotencyKey(
                user_id=sender_id,
                key=idempotency_key,
                endpoint="/transfers",
                request_hash=request_hash,
                response_data=None,
                status="Processing",
                expires_at=now + timedelta(hours=24)
            )
            db.add(idempotency_record)

        db.flush()

        is_flagged = should_flag_transaction(
            db,
            sender_account.id,
            amount
        )

        transaction = Transaction(
            transaction_ref=create_transaction_reference(),
            type="Transfer",
            amount=amount,
            status="Success",
            initiated_by=sender_id,
            description=description,
            is_flagged=False
        )

        db.add(transaction)
        db.flush()

        if is_flagged:
            place_transaction_on_hold(
                db,
                transaction,
                sender_wallet,
                receiver_wallet,
                amount
            )

            message = "Transfer flagged and placed on hold"

        else:
            record_transaction(
                db,
                transaction,
                [
                    {
                        "account_id": sender_account.id,
                        "entry_type": "Debit",
                        "amount": amount
                    },
                    {
                        "account_id": receiver_account.id,
                        "entry_type": "Credit",
                        "amount": amount
                    }
                ]
            )

            message = "Money transferred successfully"

        response_data = {
            "message": message,
            "transaction_ref": transaction.transaction_ref,
            "sender_id": sender_id,
            "receiver_id": receiver.id,
            "amount": str(amount),
            "status": transaction.status,
            "sender_balance": str(sender_wallet.balance)
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
            detail="Invalid transfer amount"
        )

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Transfer failed. No money was deducted."
        )

    finally:
        if auth_db is not None:
            auth_db.close()

        if lock_name:
            try:
                release_idempotency_lock(db, lock_name)
            except Exception:
                db.rollback()


