import logging
from datetime import datetime

from app.database import SessionLocal
from app.models import MoneyRequest, OTP, IdempotencyKey


logger = logging.getLogger(__name__)


def expire_money_requests():
    db = SessionLocal()

    try:
        now = datetime.utcnow()

        expired_count = db.query(MoneyRequest).filter(
            MoneyRequest.status == "Pending",
            MoneyRequest.expires_at <= now
        ).update(
            {"status": "Expired"},
            synchronize_session=False
        )

        db.commit()

        logger.info(
            "Money request expiry job completed. Expired: %s",
            expired_count
        )

        return expired_count

    except Exception:
        db.rollback()
        logger.exception("Money request expiry job failed")
        return 0

    finally:
        db.close()


def cleanup_expired_records():
    db = SessionLocal()

    try:
        now = datetime.utcnow()

        deleted_otps = db.query(OTP).filter(
            OTP.expires_at < now
        ).delete(synchronize_session=False)

        deleted_idempotency_keys = db.query(IdempotencyKey).filter(
            IdempotencyKey.expires_at < now
        ).delete(synchronize_session=False)

        db.commit()

        logger.info(
            "Cleanup completed. OTPs deleted: %s, idempotency keys deleted: %s",
            deleted_otps,
            deleted_idempotency_keys
        )

        return {
            "deleted_otps": deleted_otps,
            "deleted_idempotency_keys": deleted_idempotency_keys
        }

    except Exception:
        db.rollback()
        logger.exception("Expired record cleanup failed")
        return {
            "deleted_otps": 0,
            "deleted_idempotency_keys": 0
        }

    finally:
        db.close()