import pytest
from unittest.mock import Mock
from fastapi import HTTPException

from app.services.transfer_service import execute_safe_transfer


@pytest.fixture
def db_session():
    return Mock()


@pytest.mark.parametrize(
    "amount",
    [
        "0",
        "-100",
        "NaN",
        "Infinity",
        "10.123"
    ]
)
def test_transfer_rejects_invalid_amount(db_session, amount):
    with pytest.raises(HTTPException) as exc:
        execute_safe_transfer(
            db=db_session,
            sender_id=1,
            receiver_phone="9876543210",
            amount=amount,
            idempotency_key="test-key-001",
            pin="1234"
        )

    assert exc.value.status_code == 422
    db_session.rollback.assert_called_once()


def test_transfer_rejects_invalid_receiver_phone(db_session):
    with pytest.raises(HTTPException) as exc:
        execute_safe_transfer(
            db=db_session,
            sender_id=1,
            receiver_phone="12345",
            amount="100",
            idempotency_key="test-key-002",
            pin="1234"
        )

    assert exc.value.status_code == 422
    db_session.rollback.assert_called_once()


def test_transfer_rejects_missing_idempotency_key(db_session):
    with pytest.raises(HTTPException) as exc:
        execute_safe_transfer(
            db=db_session,
            sender_id=1,
            receiver_phone="9876543210",
            amount="100",
            idempotency_key="",
            pin="1234"
        )

    assert exc.value.status_code == 400
    db_session.rollback.assert_called_once()


def test_transfer_rejects_invalid_pin(db_session):
    with pytest.raises(HTTPException) as exc:
        execute_safe_transfer(
            db=db_session,
            sender_id=1,
            receiver_phone="9876543210",
            amount="100",
            idempotency_key="test-key-003",
            pin="12"
        )

    assert exc.value.status_code == 422
    db_session.rollback.assert_called_once()


def test_scheduled_transfer_rejects_amount_above_5000(db_session):
    with pytest.raises(HTTPException) as exc:
        execute_safe_transfer(
            db=db_session,
            sender_id=1,
            receiver_phone="9876543210",
            amount="6000",
            idempotency_key="test-key-004",
            preauthorized=True
        )

    assert exc.value.status_code == 400
    db_session.rollback.assert_called_once()

