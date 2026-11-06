from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.models import Account, LedgerEntry
from app.services.ledger_service import (
    record_transaction,
    validate_money_amount,
    prevent_ledger_update,
    prevent_ledger_delete
)


def test_valid_money_amount():
    result = validate_money_amount("1500.50", "Amount")

    assert result == Decimal("1500.50")


def test_zero_amount_rejected():
    with pytest.raises(HTTPException) as exc:
        validate_money_amount("0", "Amount")

    assert exc.value.status_code == 400


def test_negative_amount_rejected():
    with pytest.raises(HTTPException) as exc:
        validate_money_amount("-100", "Amount")

    assert exc.value.status_code == 400


def test_amount_with_more_than_two_decimals_rejected():
    with pytest.raises(HTTPException) as exc:
        validate_money_amount("100.123", "Amount")

    assert exc.value.status_code == 422


def test_invalid_amount_rejected():
    with pytest.raises(HTTPException) as exc:
        validate_money_amount("invalid", "Amount")

    assert exc.value.status_code == 422


def test_ledger_requires_saved_transaction():
    db = MagicMock()

    transaction = SimpleNamespace(
        id=None,
        status="Success",
        amount=Decimal("100.00")
    )

    with pytest.raises(HTTPException) as exc:
        record_transaction(db, transaction, [])

    assert exc.value.status_code == 400
    assert exc.value.detail == "Transaction must be saved before ledger posting"


def test_only_successful_transactions_can_be_posted():
    db = MagicMock()

    transaction = SimpleNamespace(
        id=1,
        status="Pending",
        amount=Decimal("100.00")
    )

    with pytest.raises(HTTPException) as exc:
        record_transaction(db, transaction, [])

    assert exc.value.status_code == 400
    assert exc.value.detail == "Only successful transactions can be posted to the ledger"


def test_ledger_requires_at_least_two_entries():
    db = MagicMock()

    transaction = SimpleNamespace(
        id=1,
        status="Success",
        amount=Decimal("100.00")
    )

    with pytest.raises(HTTPException) as exc:
        record_transaction(db, transaction, [
            {
                "account_id": 1,
                "entry_type": "Debit",
                "amount": Decimal("100.00")
            }
        ])

    assert exc.value.status_code == 400


def test_unbalanced_debit_and_credit_rejected():
    db = MagicMock()

    transaction = SimpleNamespace(
        id=1,
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

    with pytest.raises(HTTPException) as exc:
        record_transaction(db, transaction, entries)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Ledger debits and credits must be equal"
    db.query.assert_not_called()


def test_ledger_total_must_match_transaction_amount():
    db = MagicMock()

    transaction = SimpleNamespace(
        id=1,
        status="Success",
        amount=Decimal("100.00")
    )

    entries = [
        {
            "account_id": 1,
            "entry_type": "Debit",
            "amount": Decimal("200.00")
        },
        {
            "account_id": 2,
            "entry_type": "Credit",
            "amount": Decimal("200.00")
        }
    ]

    with pytest.raises(HTTPException) as exc:
        record_transaction(db, transaction, entries)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Ledger total must match transaction amount"
    db.query.assert_not_called()


def test_duplicate_ledger_entries_rejected():
    db = MagicMock()

    account_1 = SimpleNamespace(
        id=1,
        wallet_id=None,
        balance=Decimal("500.00")
    )

    account_2 = SimpleNamespace(
        id=2,
        wallet_id=None,
        balance=Decimal("500.00")
    )

    account_query = MagicMock()
    account_query.filter.return_value.order_by.return_value.with_for_update.return_value.all.return_value = [
        account_1,
        account_2
    ]

    existing_entry = SimpleNamespace(id=10)

    ledger_query = MagicMock()
    ledger_query.filter.return_value.first.return_value = existing_entry

    db.query.side_effect = lambda model: (
        account_query if model == Account else ledger_query
    )

    transaction = SimpleNamespace(
        id=1,
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
            "amount": Decimal("100.00")
        }
    ]

    with pytest.raises(HTTPException) as exc:
        record_transaction(db, transaction, entries)

    assert exc.value.status_code == 409
    assert exc.value.detail == "Ledger entries already exist for this transaction"
    db.rollback.assert_called_once()

def test_ledger_entry_update_is_protected():
    assert event.contains(
        LedgerEntry,
        "before_update",
        prevent_ledger_update
    )


def test_ledger_entry_delete_is_protected():
    assert event.contains(
        LedgerEntry,
        "before_delete",
        prevent_ledger_delete
    )
