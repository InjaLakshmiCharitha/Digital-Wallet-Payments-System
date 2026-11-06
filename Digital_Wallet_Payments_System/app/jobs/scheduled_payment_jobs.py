import logging
import calendar
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ScheduledPayment, Transaction
from app.services.transfer_service import execute_safe_transfer
from app.utils.websocket_manager import manager


logger = logging.getLogger(__name__)


def calculate_next_run(current_run: datetime, frequency: str) -> datetime:
    if frequency == "Daily":
        return current_run + timedelta(days=1)

    if frequency == "Weekly":
        return current_run + timedelta(days=7)

    if frequency == "Monthly":
        year = current_run.year
        month = current_run.month + 1

        if month > 12:
            month = 1
            year += 1

        day = min(
            current_run.day,
            calendar.monthrange(year, month)[1]
        )

        return current_run.replace(
            year=year,
            month=month,
            day=day
        )

    raise ValueError("Invalid scheduled payment frequency")


def advance_next_run(
    current_run: datetime,
    frequency: str,
    now: datetime
) -> datetime:
    next_run = calculate_next_run(current_run, frequency)

    while next_run <= now:
        next_run = calculate_next_run(next_run, frequency)

    return next_run


def process_scheduled_payments():
    db: Session = SessionLocal()
    processed_count = 0

    try:
        now = datetime.utcnow()

        payments = (
            db.query(ScheduledPayment)
            .filter(
                ScheduledPayment.is_active.is_(True),
                ScheduledPayment.next_run_at <= now
            )
            .order_by(
                ScheduledPayment.next_run_at.asc(),
                ScheduledPayment.id.asc()
            )
            .with_for_update(skip_locked=True)
            .all()
        )

        for payment in payments:
            scheduled_run = payment.next_run_at

            idempotency_key = (
                f"scheduled-{payment.id}-{scheduled_run.strftime('%Y%m%d%H%M%S')}"
            )

            transfer_db = SessionLocal()

            try:
                result, replayed = execute_safe_transfer(
                    db=transfer_db,
                    sender_id=payment.user_id,
                    receiver_phone=payment.recipient_phone,
                    amount=Decimal(str(payment.amount)),
                    idempotency_key=idempotency_key,
                    description=(
                        payment.note
                        or f"Scheduled {payment.frequency} payment"
                    ),
                    preauthorized=True
                )

                transaction = (
                    db.query(Transaction)
                    .filter(
                        Transaction.transaction_ref
                        == result.get("transaction_ref")
                    )
                    .first()
                )

                if transaction:
                    payment.last_transaction_id = transaction.id

                manager.send_from_background(
                    payment.user_id,
                    {
                        "type": (
                            "scheduled_payment_success"
                            if result.get("status") == "Success"
                            else "scheduled_payment_on_hold"
                        ),
                        "payment_id": payment.id,
                        "amount": str(payment.amount),
                        "recipient_phone": payment.recipient_phone,
                        "transaction_ref": result.get("transaction_ref"),
                        "message": result.get("message")
                    }
                )

                processed_count += 1

            except Exception as exc:
                logger.exception(
                    "Scheduled payment %s failed",
                    payment.id
                )

                manager.send_from_background(
                    payment.user_id,
                    {
                        "type": "scheduled_payment_failed",
                        "payment_id": payment.id,
                        "amount": str(payment.amount),
                        "recipient_phone": payment.recipient_phone,
                        "message": str(getattr(exc, "detail", exc))
                    }
                )

            finally:
                transfer_db.close()

            payment.next_run_at = advance_next_run(
                scheduled_run,
                payment.frequency,
                now
            )

        db.commit()

        logger.info(
            "Scheduled payment job completed. Processed: %s",
            processed_count
        )

    except Exception:
        db.rollback()
        logger.exception("Scheduled payment job failed")

    finally:
        db.close()
