from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import User, BankAccount
from app.services.otp_service import verify_otp


def mask_account_number(account_number: str):
    return "*" * (len(account_number) - 4) + account_number[-4:]


def add_bank_account(
    db: Session,
    user_id: int,
    account_holder_name: str,
    account_number: str,
    ifsc_code: str,
    bank_name: str,
    otp: str
):
    auth_db = SessionLocal()

    try:
        user = auth_db.query(User).filter(
            User.id == user_id
        ).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if not user.is_active:
            raise HTTPException(
                status_code=403,
                detail="Your account is inactive"
            )

        verify_otp(
            auth_db,
            user_id,
            "Add Bank Account",
            otp
        )

    finally:
        auth_db.close()

    try:
        account_number = account_number.strip()
        ifsc_code = ifsc_code.strip().upper()
        account_holder_name = account_holder_name.strip()
        bank_name = bank_name.strip()

        existing_count = (
            db.query(BankAccount)
            .filter(BankAccount.user_id == user_id)
            .count()
        )

        if existing_count >= 3:
            raise HTTPException(
                status_code=400,
                detail="Maximum three bank accounts are allowed"
            )

        duplicate = (
            db.query(BankAccount)
            .filter(
                BankAccount.user_id == user_id,
                BankAccount.account_number == account_number,
                BankAccount.ifsc_code == ifsc_code
            )
            .first()
        )

        if duplicate:
            raise HTTPException(
                status_code=409,
                detail="This bank account is already linked"
            )

        bank_account = BankAccount(
            user_id=user_id,
            account_holder_name=account_holder_name,
            account_number=account_number,
            ifsc_code=ifsc_code,
            bank_name=bank_name,
            is_primary=existing_count == 0
        )

        db.add(bank_account)
        db.commit()
        db.refresh(bank_account)

        return {
            "message": "Bank account linked successfully",
            "id": bank_account.id,
            "account_holder_name": bank_account.account_holder_name,
            "account_number": mask_account_number(
                bank_account.account_number
            ),
            "ifsc_code": bank_account.ifsc_code,
            "bank_name": bank_account.bank_name,
            "is_primary": bank_account.is_primary
        }

    except HTTPException:
        db.rollback()
        raise

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This bank account could not be linked because it already exists"
        )

    except Exception:
        db.rollback()
        raise


def get_bank_accounts(db: Session, user_id: int):
    accounts = (
        db.query(BankAccount)
        .filter(BankAccount.user_id == user_id)
        .order_by(
            BankAccount.is_primary.desc(),
            BankAccount.id.asc()
        )
        .all()
    )

    return [
        {
            "id": account.id,
            "account_holder_name": account.account_holder_name,
            "account_number": mask_account_number(
                account.account_number
            ),
            "ifsc_code": account.ifsc_code,
            "bank_name": account.bank_name,
            "is_primary": account.is_primary
        }
        for account in accounts
    ]


def delete_bank_account(
    db: Session,
    user_id: int,
    bank_account_id: int
):
    if bank_account_id <= 0:
        raise HTTPException(
            status_code=422,
            detail="Invalid bank account ID"
        )

    try:
        account = (
            db.query(BankAccount)
            .filter(
                BankAccount.id == bank_account_id,
                BankAccount.user_id == user_id
            )
            .with_for_update()
            .first()
        )

        if not account:
            raise HTTPException(
                status_code=404,
                detail="Bank account not found"
            )

        db.delete(account)
        db.flush()

        remaining_accounts = (
            db.query(BankAccount)
            .filter(BankAccount.user_id == user_id)
            .order_by(BankAccount.id.asc())
            .all()
        )

        if remaining_accounts and not any(
            item.is_primary for item in remaining_accounts
        ):
            remaining_accounts[0].is_primary = True

        db.commit()

        return {
            "message": "Bank account deleted successfully",
            "bank_account_id": bank_account_id
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise

