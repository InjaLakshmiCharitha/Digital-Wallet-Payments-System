from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import User, Wallet, Account, Transaction, LedgerEntry


def get_user_wallet_account(db: Session, user_id: int):
    wallet = db.query(Wallet).filter(
        Wallet.owner_id == user_id
    ).first()

    if not wallet:
        raise HTTPException(
            status_code=404,
            detail="Wallet not found"
        )

    account = db.query(Account).filter(
        Account.wallet_id == wallet.id
    ).first()

    if not account:
        raise HTTPException(
            status_code=404,
            detail="Wallet account not found"
        )

    return wallet, account


def get_other_party(db: Session, transaction_id: int, own_account_id: int):
    entries = db.query(LedgerEntry).filter(
        LedgerEntry.transaction_id == transaction_id,
        LedgerEntry.account_id != own_account_id
    ).all()

    for entry in entries:
        account = db.query(Account).filter(
            Account.id == entry.account_id
        ).first()

        if not account:
            continue

        wallet = account.wallet

        if wallet:
            if wallet.merchant:
                merchant = wallet.merchant
                merchant_user = merchant.user

                return {
                    "name": merchant.business_name,
                    "phone": merchant_user.phone if merchant_user else None
                }

            if wallet.owner:
                return {
                    "name": wallet.owner.full_name,
                    "phone": wallet.owner.phone
                }

        return {
            "name": account.account_code,
            "phone": None
        }

    return {
        "name": "System Account",
        "phone": None
    }


def get_transaction_history(
    db: Session,
    current_user: User,
    skip: int = 0,
    limit: int = 20,
    transaction_type: str | None = None,
    status: str | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    sort_by: str = "date",
    order: str = "desc"
):
    if skip < 0 or limit < 1 or limit > 100:
        raise HTTPException(
            status_code=422,
            detail="Invalid pagination values"
        )

    if sort_by not in ("date", "amount"):
        raise HTTPException(
            status_code=422,
            detail="sort_by must be date or amount"
        )

    if order not in ("asc", "desc"):
        raise HTTPException(
            status_code=422,
            detail="order must be asc or desc"
        )

    if min_amount is not None:
        try:
            min_amount = Decimal(str(min_amount))
        except (InvalidOperation, TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="Invalid minimum amount"
            )

        if not min_amount.is_finite() or min_amount < 0:
            raise HTTPException(
                status_code=422,
                detail="Minimum amount must be a non-negative valid amount"
            )

    if max_amount is not None:
        try:
            max_amount = Decimal(str(max_amount))
        except (InvalidOperation, TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="Invalid maximum amount"
            )

        if not max_amount.is_finite() or max_amount < 0:
            raise HTTPException(
                status_code=422,
                detail="Maximum amount must be a non-negative valid amount"
            )

    if (
        min_amount is not None
        and max_amount is not None
        and min_amount > max_amount
    ):
        raise HTTPException(
            status_code=422,
            detail="Minimum amount cannot exceed maximum amount"
        )

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=422,
            detail="From date cannot be later than to date"
        )

    wallet, account = get_user_wallet_account(
        db,
        current_user.id
    )

    query = db.query(
        LedgerEntry,
        Transaction
    ).join(
        Transaction,
        LedgerEntry.transaction_id == Transaction.id
    ).filter(
        LedgerEntry.account_id == account.id
    )

    if transaction_type:
        query = query.filter(
            Transaction.type == transaction_type
        )

    if status:
        query = query.filter(
            Transaction.status == status
        )

    if min_amount is not None:
        query = query.filter(
            Transaction.amount >= min_amount
        )

    if max_amount is not None:
        query = query.filter(
            Transaction.amount <= max_amount
        )

    if from_date:
        query = query.filter(
            Transaction.created_at >= from_date
        )

    if to_date:
        query = query.filter(
            Transaction.created_at <= to_date
        )

    total = query.count()

    if sort_by == "amount":
        sort_column = Transaction.amount
    else:
        sort_column = Transaction.created_at

    if order == "asc":
        query = query.order_by(
            sort_column.asc(),
            Transaction.id.asc()
        )
    else:
        query = query.order_by(
            sort_column.desc(),
            Transaction.id.desc()
        )

    records = query.offset(skip).limit(limit).all()

    results = []

    for entry, transaction in records:
        other_party = get_other_party(
            db,
            transaction.id,
            account.id
        )

        results.append({
            "transaction_ref": transaction.transaction_ref,
            "type": transaction.type,
            "amount": transaction.amount,
            "other_party_name": other_party["name"],
            "other_party_phone": other_party["phone"],
            "status": transaction.status,
            "balance_after": entry.balance_after,
            "created_at": transaction.created_at
        })

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "transactions": results
    }


def get_transaction_detail(
    db: Session,
    current_user: User,
    transaction_ref: str
):
    account = None

    if current_user.role != "Admin":
        wallet, account = get_user_wallet_account(
            db,
            current_user.id
        )

    transaction = db.query(Transaction).filter(
        Transaction.transaction_ref == transaction_ref
    ).first()

    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found"
        )

    if current_user.role != "Admin":
        own_entry = db.query(LedgerEntry).filter(
            LedgerEntry.transaction_id == transaction.id,
            LedgerEntry.account_id == account.id
        ).first()

        if not own_entry:
            raise HTTPException(
                status_code=403,
                detail="Access denied"
            )
    else:
        own_entry = db.query(LedgerEntry).filter(
            LedgerEntry.transaction_id == transaction.id
        ).order_by(
            LedgerEntry.id.asc()
        ).first()

    other_party = get_other_party(
        db,
        transaction.id,
        own_entry.account_id if own_entry else -1
    )

    return {
        "transaction_ref": transaction.transaction_ref,
        "type": transaction.type,
        "amount": transaction.amount,
        "other_party_name": other_party["name"],
        "other_party_phone": other_party["phone"],
        "status": transaction.status,
        "balance_after": own_entry.balance_after if own_entry else None,
        "created_at": transaction.created_at,
        "description": transaction.description,
        "is_flagged": transaction.is_flagged
    }


def generate_statement_data(
    db: Session,
    user: User,
    month: str
):
    try:
        statement_month = datetime.strptime(month, "%Y-%m")

        if statement_month.strftime("%Y-%m") != month:
            raise ValueError

    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Month must be in YYYY-MM format"
        )

    next_month = (
        statement_month.replace(day=28) + timedelta(days=4)
    ).replace(day=1)

    wallet, account = get_user_wallet_account(
        db,
        user.id
    )

    previous_entry = db.query(LedgerEntry).join(
        Transaction,
        LedgerEntry.transaction_id == Transaction.id
    ).filter(
        LedgerEntry.account_id == account.id,
        Transaction.created_at < statement_month
    ).order_by(
        Transaction.created_at.desc(),
        LedgerEntry.id.desc()
    ).first()

    opening_balance = (
        previous_entry.balance_after
        if previous_entry else Decimal("0.00")
    )

    monthly_entries = db.query(
        LedgerEntry,
        Transaction
    ).join(
        Transaction,
        LedgerEntry.transaction_id == Transaction.id
    ).filter(
        LedgerEntry.account_id == account.id,
        Transaction.created_at >= statement_month,
        Transaction.created_at < next_month
    ).all()

    total_credits = sum(
        (
            entry.amount
            for entry, transaction in monthly_entries
            if entry.entry_type == "Credit"
        ),
        Decimal("0.00")
    )

    total_debits = sum(
        (
            entry.amount
            for entry, transaction in monthly_entries
            if entry.entry_type == "Debit"
        ),
        Decimal("0.00")
    )

    closing_balance = (
        opening_balance + total_credits - total_debits
    )

    return {
        "user_name": user.full_name,
        "wallet_number": wallet.wallet_number,
        "month": month,
        "opening_balance": opening_balance,
        "total_credits": total_credits,
        "total_debits": total_debits,
        "closing_balance": closing_balance
    }

