import logging
from decimal import Decimal

from app.database import SessionLocal
from app.models import Account, Wallet, LedgerEntry, User
from app.services.email_service import send_email


logger = logging.getLogger(__name__)


def reconcile_wallet_balances():
    db = SessionLocal()

    try:
        mismatches = []

        accounts = db.query(Account).all()

        for account in accounts:
            entries = db.query(LedgerEntry).filter(
                LedgerEntry.account_id == account.id
            ).all()

            ledger_balance = sum(
                (
                    Decimal(str(entry.amount))
                    if entry.entry_type == "Credit"
                    else -Decimal(str(entry.amount))
                    for entry in entries
                ),
                Decimal("0.00")
            )

            account_balance = Decimal(str(account.balance))

            if ledger_balance != account_balance:
                mismatches.append(
                    f"Account {account.account_code}: "
                    f"Account balance={account_balance}, "
                    f"Ledger balance={ledger_balance}"
                )

            if account.wallet_id is not None:
                wallet = db.query(Wallet).filter(
                    Wallet.id == account.wallet_id
                ).first()

                if wallet:
                    wallet_balance = Decimal(str(wallet.balance))

                    if wallet_balance != account_balance:
                        mismatches.append(
                            f"Wallet {wallet.wallet_number}: "
                            f"Wallet balance={wallet_balance}, "
                            f"Account balance={account_balance}"
                        )

        total_debits = sum(
            (
                Decimal(str(entry.amount))
                for entry in db.query(LedgerEntry).filter(
                    LedgerEntry.entry_type == "Debit"
                ).all()
            ),
            Decimal("0.00")
        )

        total_credits = sum(
            (
                Decimal(str(entry.amount))
                for entry in db.query(LedgerEntry).filter(
                    LedgerEntry.entry_type == "Credit"
                ).all()
            ),
            Decimal("0.00")
        )

        if total_debits != total_credits:
            mismatches.append(
                f"Global ledger imbalance: "
                f"Debits={total_debits}, Credits={total_credits}"
            )

        if mismatches:
            logger.error(
                "Ledger reconciliation found %s mismatch(es)",
                len(mismatches)
            )

            admins = db.query(User).filter(
                User.role == "Admin",
                User.is_active.is_(True)
            ).all()

            report = "\n".join(mismatches)

            for admin in admins:
                if admin.email:
                    send_email(
                        admin.email,
                        "Digital Wallet - Ledger Reconciliation Alert",
                        (
                            f"Hello {admin.full_name},\n\n"
                            "The daily ledger reconciliation detected "
                            "the following mismatches:\n\n"
                            f"{report}\n\n"
                            "Please investigate these discrepancies."
                        )
                    )

            return {
                "status": "Mismatch Found",
                "mismatches": mismatches
            }

        logger.info("Daily ledger reconciliation completed successfully")

        return {
            "status": "Reconciled",
            "mismatches": []
        }

    except Exception:
        logger.exception("Ledger reconciliation job failed")
        return {
            "status": "Failed",
            "mismatches": []
        }

    finally:
        db.close()