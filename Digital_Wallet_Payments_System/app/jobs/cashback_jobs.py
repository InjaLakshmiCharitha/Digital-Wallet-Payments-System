import logging
from datetime import datetime
from decimal import Decimal

from app.database import SessionLocal
from app.models import Cashback, Wallet, Account, Transaction, User
from app.services.ledger_service import (
    create_transaction_reference,
    record_transaction
)
from app.services.notification_service import create_notification
from app.services.email_service import send_email
from app.utils.websocket_manager import manager


logger = logging.getLogger(__name__)


def process_pending_cashbacks():
    db = SessionLocal()
    credited_count = 0

    try:
        now = datetime.utcnow()

        cashbacks = db.query(Cashback).filter(
            Cashback.status == "Pending",
            Cashback.eligible_at <= now
        ).order_by(
            Cashback.id.asc()
        ).with_for_update(skip_locked=True).all()

        for cashback in cashbacks:
            try:
                wallet = db.query(Wallet).filter(
                    Wallet.owner_id == cashback.user_id
                ).with_for_update().first()

                if not wallet or wallet.status != "Active":
                    logger.warning(
                        "Cashback %s skipped because wallet is unavailable",
                        cashback.id
                    )
                    continue

                wallet_account = db.query(Account).filter(
                    Account.wallet_id == wallet.id
                ).first()

                cashback_account = db.query(Account).filter(
                    Account.account_code == "CASHBACK-POOL"
                ).first()

                if not wallet_account or not cashback_account:
                    logger.error(
                        "Required ledger account missing for cashback %s",
                        cashback.id
                    )
                    continue

                amount = Decimal(str(cashback.amount))

                transaction = Transaction(
                    transaction_ref=create_transaction_reference(),
                    type="Cashback",
                    amount=amount,
                    status="Success",
                    initiated_by=cashback.user_id,
                    description="Merchant payment cashback",
                    is_flagged=False
                )

                db.add(transaction)
                db.flush()

                record_transaction(
                    db,
                    transaction,
                    [
                        {
                            "account_id": cashback_account.id,
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

                cashback.status = "Credited"
                cashback.credited_at = now
                cashback.transaction_id = transaction.id

                db.commit()
                credited_count += 1

                user = db.query(User).filter(
                    User.id == cashback.user_id
                ).first()

                if user:
                    message = (
                        f"Cashback of ₹{amount} has been "
                        f"credited to your wallet. "
                        f"Transaction Reference: "
                        f"{transaction.transaction_ref}"
                    )

                    try:
                        create_notification(
                            db=db,
                            user_id=user.id,
                            notification_type="Cashback Credited",
                            message=message
                        )

                        db.commit()

                    except Exception:
                        db.rollback()
                        logger.exception(
                            "Failed to create cashback notification "
                            "for user %s",
                            user.id
                        )

                    manager.send_from_background(
                        user.id,
                        {
                            "type": "cashback_credited",
                            "message": message,
                            "amount": str(amount),
                            "transaction_ref": transaction.transaction_ref,
                            "wallet_balance": str(wallet.balance)
                        }
                    )

                    if user.email:
                        try:
                            send_email(
                                user.email,
                                "Digital Wallet - Cashback Credited",
                                (
                                    f"Hello {user.full_name},\n\n"
                                    f"Cashback of ₹{amount} has been "
                                    "credited to your wallet.\n\n"
                                    f"Transaction Reference: "
                                    f"{transaction.transaction_ref}\n\n"
                                    "Thank you for using Digital Wallet."
                                )
                            )

                        except Exception:
                            logger.exception(
                                "Cashback email failed for user %s",
                                user.id
                            )

            except Exception:
                db.rollback()
                logger.exception(
                    "Failed to process cashback ID %s",
                    cashback.id
                )

        logger.info(
            "Cashback job completed. Credited: %s",
            credited_count
        )

        return credited_count

    except Exception:
        db.rollback()
        logger.exception("Cashback scheduled job failed")
        return credited_count

    finally:
        db.close()
