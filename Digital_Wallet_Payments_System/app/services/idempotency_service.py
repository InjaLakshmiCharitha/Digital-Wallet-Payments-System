import hashlib
import json

from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import IdempotencyKey


def create_request_hash(request_data: dict) -> str:
    request_json = json.dumps(
        request_data,
        sort_keys=True,
        default=str,
        separators=(",", ":")
    )

    return hashlib.sha256(
        request_json.encode()
    ).hexdigest()


def get_lock_name(
    user_id: int,
    endpoint: str,
    key: str
) -> str:
    value = f"{user_id}:{endpoint}:{key}"

    return "idem_" + hashlib.sha256(
        value.encode()
    ).hexdigest()[:58]


def acquire_idempotency_lock(
    db: Session,
    lock_name: str
) -> bool:
    result = db.execute(
        text("SELECT GET_LOCK(:lock_name, 0)"),
        {"lock_name": lock_name}
    ).scalar()

    return result == 1


def release_idempotency_lock(
    db: Session,
    lock_name: str
):
    result = db.execute(
        text("SELECT RELEASE_LOCK(:lock_name)"),
        {"lock_name": lock_name}
    ).scalar()

    return result == 1


def get_or_create_idempotency_key(
    db: Session,
    user_id: int,
    endpoint: str,
    idempotency_key: str,
    request_data: dict
):
    if user_id <= 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid user ID"
        )

    if not endpoint or not endpoint.strip():
        raise HTTPException(
            status_code=400,
            detail="Invalid endpoint"
        )

    if (
        not idempotency_key
        or not idempotency_key.strip()
        or len(idempotency_key) > 128
    ):
        raise HTTPException(
            status_code=400,
            detail="A valid Idempotency-Key header is required"
        )

    request_hash = create_request_hash(request_data)

    lock_name = get_lock_name(
        user_id,
        endpoint,
        idempotency_key
    )

    lock_acquired = acquire_idempotency_lock(
        db,
        lock_name
    )

    if not lock_acquired:
        raise HTTPException(
            status_code=409,
            detail="Request with this idempotency key is already processing"
        )

    try:
        record = (
            db.query(IdempotencyKey)
            .filter(
                IdempotencyKey.user_id == user_id,
                IdempotencyKey.endpoint == endpoint,
                IdempotencyKey.key == idempotency_key
            )
            .with_for_update()
            .first()
        )

        now = datetime.utcnow()

        if record:
            if record.expires_at <= now:
                record.request_hash = request_hash
                record.response_data = None
                record.status = "Processing"
                record.expires_at = now + timedelta(hours=24)

                db.flush()

                return record, None, lock_name

            if record.request_hash != request_hash:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Idempotency key was already used "
                        "with different request data"
                    )
                )

            if record.status == "Completed":
                return record, record.response_data, lock_name

            raise HTTPException(
                status_code=409,
                detail="Request with this idempotency key is already processing"
            )

        record = IdempotencyKey(
            user_id=user_id,
            key=idempotency_key,
            endpoint=endpoint,
            request_hash=request_hash,
            response_data=None,
            status="Processing",
            expires_at=now + timedelta(hours=24)
        )

        db.add(record)
        db.flush()

        return record, None, lock_name

    except Exception:
        try:
            db.rollback()
        finally:
            try:
                release_idempotency_lock(
                    db,
                    lock_name
                )
            except Exception:
                db.rollback()

        raise


def complete_idempotency_key(
    db: Session,
    record: IdempotencyKey,
    response_data: dict
):
    record.response_data = response_data
    record.status = "Completed"

    db.flush()

    return record



