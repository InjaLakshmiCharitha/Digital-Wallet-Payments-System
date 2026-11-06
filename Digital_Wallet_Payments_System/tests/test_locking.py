from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models import Account, Wallet, LedgerEntry
from app.services.ledger_service import record_transaction


def test_accounts_are_locked_in_ascending_order():
    db = MagicMock()

    account_1 = SimpleNamespace(
        id=2,
        wallet_id=10,
        balance=Decimal("100.00")
    )

    account_2 = SimpleNamespace(
        id=4,
        wallet_id=20,
        balance=Decimal("500.00")
    )

    wallet_1 = SimpleNamespace(
        id=10,
        balance=Decimal("100.00")
    )

    wallet_2 = SimpleNamespace(
        id=20,
        balance=Decimal("500.00")
    )

    account_query = MagicMock()
    account_query.filter.return_value.order_by.return_value.with_for_update.return_value.all.return_value = [
        account_1,
        account_2
    ]

    ledger_query = MagicMock()
    ledger_query.filter.return_value.first.return_value = None

    wallet_query = MagicMock()
    wallet_query.filter.return_value.order_by.return_value.with_for_update.return_value.all.return_value = [
        wallet_1,
        wallet_2
    ]

    def query_side_effect(model):
        if model == Account:
            return account_query
        if model == LedgerEntry:
            return ledger_query
        if model == Wallet:
            return wallet_query

    db.query.side_effect = query_side_effect

    transaction = SimpleNamespace(
        id=1,
        status="Success",
        amount=Decimal("100.00")
    )

    entries = [
        {
            "account_id": 4,
            "entry_type": "Debit",
            "amount": Decimal("100.00")
        },
        {
            "account_id": 2,
            "entry_type": "Credit",
            "amount": Decimal("100.00")
        }
    ]

    record_transaction(db, transaction, entries)

    account_order = account_query.filter.return_value.order_by.call_args.args[0]
    wallet_order = wallet_query.filter.return_value.order_by.call_args.args[0]

    assert str(account_order) == "accounts.id ASC"
    assert str(wallet_order) == "wallets.id ASC"

    account_query.filter.return_value.order_by.return_value.with_for_update.assert_called_once()
    wallet_query.filter.return_value.order_by.return_value.with_for_update.assert_called_once()


def test_ledger_entries_are_created_after_ordered_locking():
    db = MagicMock()

    account_1 = SimpleNamespace(
        id=1,
        wallet_id=None,
        balance=Decimal("0.00")
    )

    account_2 = SimpleNamespace(
        id=2,
        wallet_id=None,
        balance=Decimal("0.00")
    )

    account_query = MagicMock()
    account_query.filter.return_value.order_by.return_value.with_for_update.return_value.all.return_value = [
        account_1,
        account_2
    ]

    ledger_query = MagicMock()
    ledger_query.filter.return_value.first.return_value = None

    db.query.side_effect = lambda model: (
        account_query if model == Account else ledger_query
    )

    transaction = SimpleNamespace(
        id=2,
        status="Success",
        amount=Decimal("250.00")
    )

    entries = [
        {
            "account_id": 2,
            "entry_type": "Debit",
            "amount": Decimal("250.00")
        },
        {
            "account_id": 1,
            "entry_type": "Credit",
            "amount": Decimal("250.00")
        }
    ]

    record_transaction(db, transaction, entries)

    assert db.add.call_count == 2
    db.flush.assert_called_once()
    db.refresh.assert_called_once_with(transaction)

    order_expression = account_query.filter.return_value.order_by.call_args.args[0]

    assert str(order_expression) == "accounts.id ASC"


def test_unbalanced_entries_are_rejected_before_locking():
    db = MagicMock()

    transaction = SimpleNamespace(
        id=3,
        status="Success",
        amount=Decimal("100.00")
    )

    entries = [
        {
            "account_id": 1,
            "entry_type": "Debit",
            "amount": Decimal("100.00")
        },
        {
            "account_id": 2,
            "entry_type": "Credit",
            "amount": Decimal("50.00")
        }
    ]

    from fastapi import HTTPException

    import pytest

    with pytest.raises(HTTPException) as exc:
        record_transaction(db, transaction, entries)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Ledger debits and credits must be equal"
    db.rollback.assert_called_once()
    db.query.assert_not_called()
