from datetime import datetime
from secrets import token_hex
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import event

from app.models import Account, Wallet, Transaction, LedgerEntry


SYSTEM_ACCOUNTS = [
    ("BANK-SETTLEMENT", "Bank Settlement"),
    ("CASHBACK-POOL", "Cashback Pool"),
    ("PLATFORM-FEES", "Fees"),
    ("WITHDRAWAL-CLEARING", "Withdrawal Clearing"),
    ("HOLD-ACCOUNT", "Hold")
]


def create_transaction_reference():
    date_part = datetime.utcnow().strftime("%Y%m%d")
    random_part = token_hex(8).upper()

    return f"TXN-{date_part}-{random_part}"


def create_system_accounts(db: Session):
    try:
        for account_code, account_type in SYSTEM_ACCOUNTS:
            existing = db.query(Account).filter(
                Account.account_code == account_code
            ).first()

            if not existing:
                account = Account(
                    account_code=account_code,
                    account_type=account_type,
                    wallet_id=None,
                    balance=Decimal("0.00"),
                    is_system_account=True
                )

                db.add(account)

        db.commit()

    except Exception:
        db.rollback()
        raise


def get_account(
    db: Session,
    account_type: str,
    wallet_id=None
):
    query = db.query(Account).filter(
        Account.account_type == account_type
    )

    if wallet_id is None:
        query = query.filter(
            Account.wallet_id.is_(None),
            Account.is_system_account.is_(True)
        )
    else:
        query = query.filter(
            Account.wallet_id == wallet_id
        )

    account = query.first()

    if not account:
        raise HTTPException(
            status_code=404,
            detail=f"{account_type} account not found"
        )

    return account


def create_wallet_account(
    db: Session,
    wallet: Wallet,
    account_type: str
):
    account = db.query(Account).filter(
        Account.wallet_id == wallet.id
    ).first()

    if account:
        return account

    account = Account(
        account_code=f"WALLET-{wallet.id}",
        account_type=account_type,
        wallet_id=wallet.id,
        balance=Decimal("0.00"),
        is_system_account=False
    )

    db.add(account)
    db.flush()

    return account


def validate_money_amount(value, field_name):
    try:
        amount = Decimal(str(value))

    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}"
        )

    if not amount.is_finite():
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be a valid finite amount"
        )

    if amount <= Decimal("0.00"):
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be greater than zero"
        )

    if amount != amount.quantize(Decimal("0.01")):
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} cannot have more than two decimal places"
        )

    return amount.quantize(Decimal("0.01"))


def record_transaction(
    db: Session,
    transaction: Transaction,
    entries: list
):
    try:
        if not transaction.id:
            raise HTTPException(
                status_code=400,
                detail="Transaction must be saved before ledger posting"
            )

        if transaction.status != "Success":
            raise HTTPException(
                status_code=400,
                detail="Only successful transactions can be posted to the ledger"
            )

        transaction_amount = validate_money_amount(
            transaction.amount,
            "Transaction amount"
        )

        if not isinstance(entries, list) or len(entries) < 2:
            raise HTTPException(
                status_code=400,
                detail="At least two ledger entries are required"
            )

        validated_entries = []

        for entry in entries:
            if not isinstance(entry, dict):
                raise HTTPException(
                    status_code=422,
                    detail="Invalid ledger entry"
                )

            account_id = entry.get("account_id")
            entry_type = entry.get("entry_type")

            if not isinstance(account_id, int) or account_id <= 0:
                raise HTTPException(
                    status_code=422,
                    detail="Invalid ledger account ID"
                )

            if entry_type not in ("Debit", "Credit"):
                raise HTTPException(
                    status_code=422,
                    detail="Entry type must be Debit or Credit"
                )

            amount = validate_money_amount(
                entry.get("amount"),
                "Ledger entry amount"
            )

            validated_entries.append({
                "account_id": account_id,
                "entry_type": entry_type,
                "amount": amount
            })

        total_debits = sum(
            (
                entry["amount"]
                for entry in validated_entries
                if entry["entry_type"] == "Debit"
            ),
            Decimal("0.00")
        )

        total_credits = sum(
            (
                entry["amount"]
                for entry in validated_entries
                if entry["entry_type"] == "Credit"
            ),
            Decimal("0.00")
        )

        if total_debits != total_credits:
            raise HTTPException(
                status_code=400,
                detail="Ledger debits and credits must be equal"
            )

        if total_debits != transaction_amount:
            raise HTTPException(
                status_code=400,
                detail="Ledger total must match transaction amount"
            )

        account_ids = sorted({
            entry["account_id"]
            for entry in validated_entries
        })

        accounts = (
            db.query(Account)
            .filter(Account.id.in_(account_ids))
            .order_by(Account.id.asc())
            .with_for_update()
            .all()
        )

        account_map = {
            account.id: account
            for account in accounts
        }

        if len(account_map) != len(account_ids):
            raise HTTPException(
                status_code=404,
                detail="One or more ledger accounts were not found"
            )

        existing_entries = db.query(LedgerEntry).filter(
            LedgerEntry.transaction_id == transaction.id
        ).first()

        if existing_entries:
            raise HTTPException(
                status_code=409,
                detail="Ledger entries already exist for this transaction"
            )

        wallet_ids = sorted({
            account.wallet_id
            for account in accounts
            if account.wallet_id is not None
        })

        wallets = []

        if wallet_ids:
            wallets = (
                db.query(Wallet)
                .filter(Wallet.id.in_(wallet_ids))
                .order_by(Wallet.id.asc())
                .with_for_update()
                .all()
            )

        wallet_map = {
            wallet.id: wallet
            for wallet in wallets
        }

        for entry in validated_entries:
            account = account_map[entry["account_id"]]
            amount = entry["amount"]

            current_balance = Decimal(
                str(account.balance)
            )

            if entry["entry_type"] == "Debit":
                new_balance = current_balance - amount
            else:
                new_balance = current_balance + amount

            if account.wallet_id is not None and new_balance < 0:
                raise HTTPException(
                    status_code=400,
                    detail="Insufficient wallet balance"
                )

            account.balance = new_balance

            if account.wallet_id is not None:
                wallet = wallet_map.get(account.wallet_id)

                if not wallet:
                    raise HTTPException(
                        status_code=404,
                        detail="Wallet not found for ledger account"
                    )

                wallet.balance = new_balance

            ledger_entry = LedgerEntry(
                transaction_id=transaction.id,
                account_id=account.id,
                entry_type=entry["entry_type"],
                amount=amount,
                balance_after=new_balance
            )

            db.add(ledger_entry)

        db.flush()
        db.refresh(transaction)

        return transaction

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise


@event.listens_for(LedgerEntry, "before_update")
def prevent_ledger_update(mapper, connection, target):
    raise ValueError("Ledger entries cannot be updated")


@event.listens_for(LedgerEntry, "before_delete")
def prevent_ledger_delete(mapper, connection, target):
    raise ValueError("Ledger entries cannot be deleted")
