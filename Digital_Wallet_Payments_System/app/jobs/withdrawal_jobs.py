import logging
from datetime import datetime, timedelta
from decimal import Decimal

from app.database import SessionLocal
from app.models import (
    Withdrawal,
    Transaction,
    Wallet,
    Account,
    User
)
from app.services.ledger_service import (
    create_transaction_reference,
    record_transaction
)
from app.services.notification_service import create_notification
from app.services.email_service import send_email
from app.utils.websocket_manager import manager


logger = logging.getLogger(__name__)


def notify_withdrawal(
    db,
    user_id,
    event,
    amount,
    transaction_ref,
    failure_reason=None
):
    user = db.query(User).filter(
        User.id == user_id
    ).first()

    if not user:
        logger.warning(
            "User %s not found for withdrawal notification",
            user_id
        )
        return

    if event == "Withdrawal Completed":
        message = (
            f"Your withdrawal of ₹{amount} has been completed. "
            f"Transaction Reference: {transaction_ref}"
        )
        event_type = "withdrawal_completed"
    else:
        message = (
            f"Your withdrawal of ₹{amount} has failed. "
            f"The amount has been refunded to your wallet. "
            f"Reason: {failure_reason}. "
            f"Transaction Reference: {transaction_ref}"
        )
        event_type = "withdrawal_failed"

    try:
        create_notification(
            db=db,
            user_id=user.id,
            notification_type=event,
            message=message
        )
        db.commit()

    except Exception:
        db.rollback()
        logger.exception(
            "Failed to create withdrawal notification for user %s",
            user.id
        )

    manager.send_from_background(
        user.id,
        {
            "type": event_type,
            "message": message,
            "amount": str(amount),
            "transaction_ref": transaction_ref
        }
    )

    if user.email:
        try:
            subject = f"Digital Wallet - {event}"

            content = (
                f"Hello {user.full_name},\n\n"
                f"{message}\n\n"
                "Thank you for using Digital Wallet."
            )

            send_email(
                user.email,
                subject,
                content
            )

        except Exception:
            logger.exception(
                "Withdrawal email failed for user %s",
                user.id
            )


def process_pending_withdrawals():
    db = SessionLocal()
    completed_count = 0
    failed_count = 0

    try:
        cutoff_time = datetime.utcnow() - timedelta(minutes=10)

        withdrawals = db.query(Withdrawal).filter(
            Withdrawal.status == "Pending",
            Withdrawal.created_at <= cutoff_time
        ).order_by(
            Withdrawal.id.asc()
        ).with_for_update(skip_locked=True).all()

        for withdrawal in withdrawals:
            try:
                transaction = db.query(Transaction).filter(
                    Transaction.id == withdrawal.transaction_id
                ).with_for_update().first()

                if not transaction:
                    logger.error(
                        "Transaction missing for withdrawal %s",
                        withdrawal.id
                    )
                    continue

                bank_account = withdrawal.bank_account
                amount = Decimal(str(withdrawal.amount))
                user_id = withdrawal.user_id
                transaction_ref = transaction.transaction_ref

                if bank_account and bank_account.is_active:
                    withdrawal.status = "Success"
                    withdrawal.processed_at = datetime.utcnow()
                    withdrawal.failure_reason = None

                    transaction.status = "Success"

                    db.commit()
                    completed_count += 1

                    notify_withdrawal(
                        db,
                        user_id,
                        "Withdrawal Completed",
                        amount,
                        transaction_ref
                    )

                    continue

                wallet = db.query(Wallet).filter(
                    Wallet.owner_id == user_id
                ).with_for_update().first()

                wallet_account = db.query(Account).filter(
                    Account.wallet_id == wallet.id
                ).with_for_update().first() if wallet else None

                clearing_account = db.query(Account).filter(
                    Account.account_code == "WITHDRAWAL-CLEARING"
                ).with_for_update().first()

                if not wallet_account or not clearing_account:
                    logger.error(
                        "Refund accounts missing for withdrawal %s",
                        withdrawal.id
                    )
                    continue

                refund_transaction = Transaction(
                    transaction_ref=create_transaction_reference(),
                    type="Withdrawal Refund",
                    amount=amount,
                    status="Success",
                    initiated_by=user_id,
                    description="Refund for failed bank withdrawal",
                    is_flagged=False
                )

                db.add(refund_transaction)
                db.flush()

                record_transaction(
                    db,
                    refund_transaction,
                    [
                        {
                            "account_id": clearing_account.id,
                            "entry_type": "Debit",
                            "amount": amount
                        },
                        {
                            "account_id": wallet_account.id,
                            "entry_type": "Credit",
                            "amount": amount
                        }
                    ]
                )

                withdrawal.status = "Failed"
                withdrawal.processed_at = datetime.utcnow()
                withdrawal.failure_reason = (
                    "Linked bank account is inactive. "
                    "Withdrawal amount refunded to wallet."
                )

                transaction.status = "Failed"

                db.commit()
                failed_count += 1

                notify_withdrawal(
                    db,
                    user_id,
                    "Withdrawal Failed",
                    amount,
                    transaction_ref,
                    withdrawal.failure_reason
                )

            except Exception:
                db.rollback()
                logger.exception(
                    "Withdrawal processing failed for ID %s",
                    withdrawal.id
                )

        logger.info(
            "Withdrawal job completed. Successful: %s, Failed: %s",
            completed_count,
            failed_count
        )

        return {
            "completed": completed_count,
            "failed": failed_count
        }

    except Exception:
        db.rollback()
        logger.exception("Withdrawal scheduled job failed")

        return {
            "completed": completed_count,
            "failed": failed_count
        }

    finally:
        db.close()

