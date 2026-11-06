import pytest
from unittest.mock import Mock
from fastapi import HTTPException

from app.services.idempotency_service import (
    create_request_hash,
    get_lock_name,
    get_or_create_idempotency_key
)


def test_same_request_generates_same_hash():
    first = create_request_hash({"amount": 100, "phone": "9876543210"})
    second = create_request_hash({"phone": "9876543210", "amount": 100})

    assert first == second


def test_different_requests_generate_different_hashes():
    first = create_request_hash({"amount": 100})
    second = create_request_hash({"amount": 200})

    assert first != second


def test_lock_name_is_consistent():
    first = get_lock_name(1, "/wallet/transfer", "key-123")
    second = get_lock_name(1, "/wallet/transfer", "key-123")

    assert first == second
    assert first.startswith("idem_")


def test_different_keys_generate_different_lock_names():
    first = get_lock_name(1, "/wallet/transfer", "key-123")
    second = get_lock_name(1, "/wallet/transfer", "key-456")

    assert first != second


def test_different_users_generate_different_lock_names():
    first = get_lock_name(1, "/wallet/transfer", "key-123")
    second = get_lock_name(2, "/wallet/transfer", "key-123")

    assert first != second


@pytest.mark.parametrize(
    "user_id, endpoint, key, expected_status",
    [
        (0, "/wallet/transfer", "key-123", 400),
        (-1, "/wallet/transfer", "key-123", 400),
        (1, "", "key-123", 400),
        (1, "   ", "key-123", 400),
        (1, "/wallet/transfer", "", 400),
        (1, "/wallet/transfer", "   ", 400),
        (1, "/wallet/transfer", "a" * 129, 400)
    ]
)
def test_invalid_idempotency_inputs(
    user_id,
    endpoint,
    key,
    expected_status
):
    db = Mock()

    with pytest.raises(HTTPException) as exc:
        get_or_create_idempotency_key(
            db=db,
            user_id=user_id,
            endpoint=endpoint,
            idempotency_key=key,
            request_data={"amount": 100}
        )

    assert exc.value.status_code == expected_status
    db.execute.assert_not_called()
