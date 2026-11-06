import json
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    User,
    Wallet,
    Account,
    Transaction,
    LedgerEntry,
    AdminDecision
)

from app.services.ledger_service import (
    record_transaction,
    create_transaction_reference
)


def should_flag_transaction(db: Session, sender_account_id: int, amount: Decimal):
    if amount > Decimal("20000.00"):
        return True

    one_minute_ago = datetime.utcnow() - timedelta(minutes=1)

    recent_count = (
        db.query(LedgerEntry)
        .join(Transaction, LedgerEntry.transaction_id == Transaction.id)
        .filter(
            LedgerEntry.account_id == sender_account_id,
            LedgerEntry.entry_type == "Debit",
            Transaction.type == "Transfer",
            Transaction.created_at >= one_minute_ago
        )
        .count()
    )

    return recent_count >= 5


def place_transaction_on_hold(
    db: Session,
    transaction: Transaction,
    sender_wallet: Wallet,
    receiver_wallet: Wallet,
    amount: Decimal
):
    accounts = (
        db.query(Account)
        .filter(
            Account.wallet_id.in_([
                sender_wallet.id,
                receiver_wallet.id
            ])
        )
        .order_by(Account.id.asc())
        .with_for_update()
        .all()
    )

    account_map = {
        account.wallet_id: account
        for account in accounts
    }

    sender_account = account_map.get(sender_wallet.id)
    receiver_account = account_map.get(receiver_wallet.id)

    hold_account = (
        db.query(Account)
        .filter(Account.account_code == "HOLD-ACCOUNT")
        .with_for_update()
        .first()
    )

    if not sender_account or not receiver_account or not hold_account:
        raise HTTPException(
            status_code=404,
            detail="Required accounts not found"
        )

    if sender_account.balance < amount:
        raise HTTPException(
            status_code=400,
            detail="Insufficient balance"
        )

    transaction.description = json.dumps({
        "original_description": transaction.description,
        "receiver_account_id": receiver_account.id
    })

    transaction.is_flagged = True
    transaction.status = "Success"

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
                "account_id": hold_account.id,
                "entry_type": "Credit",
                "amount": amount
            }
        ]
    )

    transaction.status = "On Hold"

    return {
        "message": "Transaction flagged and placed on hold",
        "transaction_ref": transaction.transaction_ref,
        "status": transaction.status,
        "amount": amount
    }


def decide_flagged_transaction(
    db: Session,
    transaction_ref: str,
    admin_id: int,
    decision: str,
    reason: str
):
    if decision not in ["Approved", "Rejected"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid decision"
        )

    transaction = (
        db.query(Transaction)
        .filter(Transaction.transaction_ref == transaction_ref)
        .with_for_update()
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found"
        )

    if transaction.status != "On Hold":
        raise HTTPException(
            status_code=409,
            detail="Transaction is not on hold"
        )

    if transaction.type != "Transfer":
        raise HTTPException(
            status_code=400,
            detail="Only flagged transfers can be reviewed"
        )

    existing_decision = (
        db.query(AdminDecision)
        .filter(AdminDecision.transaction_id == transaction.id)
        .first()
    )

    if existing_decision:
        raise HTTPException(
            status_code=409,
            detail="Transaction already reviewed"
        )

    original_entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.transaction_id == transaction.id)
        .all()
    )

    sender_entry = next(
        (
            entry for entry in original_entries
            if entry.entry_type == "Debit"
        ),
        None
    )

    hold_entry = next(
        (
            entry for entry in original_entries
            if entry.entry_type == "Credit"
        ),
        None
    )

    if not sender_entry or not hold_entry:
        raise HTTPException(
            status_code=400,
            detail="Original hold ledger entries not found"
        )

    if hold_entry.account_id == sender_entry.account_id:
        raise HTTPException(
            status_code=400,
            detail="Invalid hold ledger entries"
        )

    try:
        description_data = json.loads(
            transaction.description or "{}"
        )
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail="Transaction receiver information is invalid"
        )

    if decision == "Approved":
        destination_account_id = description_data.get(
            "receiver_account_id"
        )

        if not destination_account_id:
            raise HTTPException(
                status_code=400,
                detail="Receiver account information is missing"
            )
    else:
        destination_account_id = sender_entry.account_id

    account_ids = sorted([
        hold_entry.account_id,
        destination_account_id
    ])

    if len(set(account_ids)) != 2:
        raise HTTPException(
            status_code=400,
            detail="Invalid destination account"
        )

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

    hold_account = account_map.get(hold_entry.account_id)
    destination_account = account_map.get(destination_account_id)

    if not hold_account or not destination_account:
        raise HTTPException(
            status_code=404,
            detail="Hold or destination account not found"
        )

    if hold_account.balance < transaction.amount:
        raise HTTPException(
            status_code=400,
            detail="Insufficient hold account balance"
        )

    release_transaction = Transaction(
        transaction_ref=create_transaction_reference(),
        type="Hold Release",
        amount=transaction.amount,
        status="Success",
        initiated_by=admin_id,
        description=(
            f"{decision} hold release for "
            f"{transaction.transaction_ref}"
        )
    )

    db.add(release_transaction)
    db.flush()

    record_transaction(
        db,
        release_transaction,
        [
            {
                "account_id": hold_account.id,
                "entry_type": "Debit",
                "amount": transaction.amount
            },
            {
                "account_id": destination_account.id,
                "entry_type": "Credit",
                "amount": transaction.amount
            }
        ]
    )

    transaction.status = (
        "Success" if decision == "Approved" else "Rejected"
    )

    admin_decision = AdminDecision(
        transaction_id=transaction.id,
        admin_id=admin_id,
        decision=decision,
        reason=reason
    )

    db.add(admin_decision)
    db.commit()
    db.refresh(transaction)

    return {
        "message": f"Transaction {decision.lower()} successfully",
        "transaction_ref": transaction.transaction_ref,
        "status": transaction.status,
        "decision": decision
    }

