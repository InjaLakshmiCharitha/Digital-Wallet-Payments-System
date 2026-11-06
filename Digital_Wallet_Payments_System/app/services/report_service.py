from datetime import datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    User,
    Wallet,
    Account,
    Transaction,
    LedgerEntry,
    Merchant,
    MerchantPayment
)


def get_admin_dashboard(db: Session):
    total_users = db.query(User).count()
    active_users = db.query(User).filter(
        User.is_active.is_(True)
    ).count()

    total_wallets = db.query(Wallet).count()
    active_wallets = db.query(Wallet).filter(
        Wallet.status == "Active"
    ).count()

    total_transactions = db.query(Transaction).count()

    successful_transactions = db.query(Transaction).filter(
        Transaction.status == "Success"
    ).count()

    pending_transactions = db.query(Transaction).filter(
        Transaction.status == "Pending"
    ).count()

    flagged_transactions = db.query(Transaction).filter(
        Transaction.is_flagged.is_(True)
    ).count()

    transaction_volume = db.query(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).filter(
        Transaction.status == "Success"
    ).scalar()

    merchant_revenue = db.query(
        func.coalesce(func.sum(MerchantPayment.platform_fee), 0)
    ).join(
        Transaction,
        Transaction.id == MerchantPayment.transaction_id
    ).filter(
        Transaction.status == "Success"
    ).scalar()

    return {
        "total_users": total_users,
        "active_users": active_users,
        "total_wallets": total_wallets,
        "active_wallets": active_wallets,
        "total_transactions": total_transactions,
        "successful_transactions": successful_transactions,
        "pending_transactions": pending_transactions,
        "flagged_transactions": flagged_transactions,
        "transaction_volume": str(Decimal(str(transaction_volume))),
        "merchant_revenue": str(Decimal(str(merchant_revenue)))
    }


def get_ledger_summary(db: Session):
    total_debits = db.query(
        func.coalesce(func.sum(LedgerEntry.amount), 0)
    ).filter(
        LedgerEntry.entry_type == "Debit"
    ).scalar()

    total_credits = db.query(
        func.coalesce(func.sum(LedgerEntry.amount), 0)
    ).filter(
        LedgerEntry.entry_type == "Credit"
    ).scalar()

    accounts = db.query(Account).order_by(
        Account.id.asc()
    ).all()

    account_summaries = []

    for account in accounts:
        debit_total = db.query(
            func.coalesce(func.sum(LedgerEntry.amount), 0)
        ).filter(
            LedgerEntry.account_id == account.id,
            LedgerEntry.entry_type == "Debit"
        ).scalar()

        credit_total = db.query(
            func.coalesce(func.sum(LedgerEntry.amount), 0)
        ).filter(
            LedgerEntry.account_id == account.id,
            LedgerEntry.entry_type == "Credit"
        ).scalar()

        account_summaries.append({
            "account_id": account.id,
            "account_code": account.account_code,
            "account_type": account.account_type,
            "balance": str(Decimal(str(account.balance))),
            "total_debits": str(Decimal(str(debit_total))),
            "total_credits": str(Decimal(str(credit_total)))
        })

    return {
        "total_debits": str(Decimal(str(total_debits))),
        "total_credits": str(Decimal(str(total_credits))),
        "ledger_balanced": (
            Decimal(str(total_debits)) ==
            Decimal(str(total_credits))
        ),
        "accounts": account_summaries
    }


def get_merchant_sales(db: Session):
    merchants = db.query(Merchant).order_by(
        Merchant.id.asc()
    ).all()

    merchant_reports = []

    for merchant in merchants:
        payments = db.query(MerchantPayment).join(
            Transaction,
            Transaction.id == MerchantPayment.transaction_id
        ).filter(
            MerchantPayment.merchant_id == merchant.id,
            Transaction.status == "Success"
        )

        payment_summary = payments.with_entities(
            func.count(MerchantPayment.id),
            func.coalesce(func.sum(MerchantPayment.amount), 0),
            func.coalesce(func.sum(MerchantPayment.platform_fee), 0),
            func.coalesce(func.sum(MerchantPayment.net_amount), 0)
        ).first()

        merchant_reports.append({
            "merchant_id": merchant.id,
            "business_name": merchant.business_name,
            "merchant_code": merchant.merchant_code,
            "total_payments": payment_summary[0],
            "total_sales": str(Decimal(str(payment_summary[1]))),
            "total_platform_fees": str(Decimal(str(payment_summary[2]))),
            "total_net_amount": str(Decimal(str(payment_summary[3])))
        })

    return {
        "total_merchants": len(merchant_reports),
        "merchants": merchant_reports
    }


def get_my_spending(
    db: Session,
    user_id: int,
    from_date: datetime | None = None,
    to_date: datetime | None = None
):
    query = (
        db.query(
            Transaction.type,
            func.count(Transaction.id),
            func.coalesce(func.sum(LedgerEntry.amount), 0)
        )
        .join(
            LedgerEntry,
            LedgerEntry.transaction_id == Transaction.id
        )
        .join(
            Account,
            Account.id == LedgerEntry.account_id
        )
        .join(
            Wallet,
            Wallet.id == Account.wallet_id
        )
        .filter(
            Wallet.owner_id == user_id,
            LedgerEntry.entry_type == "Debit",
            Transaction.status == "Success"
        )
    )

    if from_date:
        query = query.filter(
            Transaction.created_at >= from_date
        )

    if to_date:
        query = query.filter(
            Transaction.created_at <= to_date
        )

    spending = query.group_by(
        Transaction.type
    ).order_by(
        Transaction.type.asc()
    ).all()

    total_spending = sum(
        (Decimal(str(item[2])) for item in spending),
        Decimal("0.00")
    )

    return {
        "user_id": user_id,
        "total_spending": str(total_spending),
        "spending_by_type": [
            {
                "transaction_type": item[0],
                "transaction_count": item[1],
                "total_amount": str(Decimal(str(item[2])))
            }
            for item in spending
        ]
    }
